#!/usr/bin/env python3
"""
Re-scrapes pages in the inventory that have no title and fills them in
using h1 / h2 / og:title fallbacks. Updates content_inventory.csv in place.

Usage:
    python3 fix_titles.py --output ../output
"""

import argparse
import csv
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "CityMigrationBot/1.0 (content audit; contact zubeid.hendricks@gmail.com)",
    "Accept": "text/html,application/xhtml+xml",
}

INVENTORY_FIELDS = [
    "sharepoint_url", "final_url", "http_status", "redirected",
    "sharepoint_path", "umbraco_path", "doc_type",
    "title", "description", "keywords", "og_title",
    "headings", "content_snippet",
]


def log(msg):
    print(msg, flush=True)


def extract_best_title(soup):
    # 1. <title> tag (strip site name suffix)
    tag = soup.find("title")
    if tag:
        t = tag.get_text(strip=True)
        # Strip common SharePoint suffix "- City of Cape Town"
        t = re.sub(r'\s*[-|]\s*City of Cape Town.*$', '', t, flags=re.IGNORECASE).strip()
        if t:
            return t

    # 2. og:title
    og = soup.find("meta", property="og:title")
    if og and og.get("content", "").strip():
        return og["content"].strip()

    # 3. First h1
    h1 = soup.find("h1")
    if h1:
        t = h1.get_text(strip=True)
        if t:
            return t

    # 4. First h2
    h2 = soup.find("h2")
    if h2:
        t = h2.get_text(strip=True)
        if t:
            return t

    return ""


def extract_description(soup):
    tag = soup.find("meta", attrs={"name": "description"})
    if tag and tag.get("content", "").strip():
        return tag["content"].strip()
    # Fallback: first paragraph
    p = soup.find("p")
    if p:
        return p.get_text(strip=True)[:200]
    return ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="../output")
    parser.add_argument("--delay", type=float, default=0.4)
    args = parser.parse_args()

    out_dir = Path(args.output)
    csv_path = out_dir / "content_inventory.csv"

    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # Find rows needing a title fix
    needs_fix = [r for r in rows if not r.get("title", "").strip()]
    log(f"Rows needing title fix: {len(needs_fix)} / {len(rows)}")

    if not needs_fix:
        log("Nothing to fix.")
        return

    session = requests.Session()
    session.headers.update(HEADERS)

    fixed = 0
    for i, row in enumerate(needs_fix, 1):
        url = row["sharepoint_url"]
        try:
            resp = session.get(url, timeout=15, allow_redirects=True)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "lxml")
            title = extract_best_title(soup)
            desc = extract_description(soup) if not row.get("description", "").strip() else row["description"]

            if title:
                row["title"] = title
                row["description"] = desc
                fixed += 1

        except Exception as exc:
            log(f"  ERROR {url}: {exc}")
            continue

        if i % 25 == 0:
            log(f"  {i}/{len(needs_fix)} processed, {fixed} titles fixed")

        time.sleep(args.delay)

    log(f"\nFixed {fixed} titles. Writing updated inventory...")

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=INVENTORY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    log(f"Inventory updated → {csv_path}")

    # Show sample of fixed department and news titles
    dept_fixed = [r for r in rows if r["doc_type"] == "DepartmentPage" and r["title"]]
    news_fixed = [r for r in rows if r["doc_type"] == "NewsArticlePage" and r["title"]]
    log(f"\nDepartment pages with titles now: {len(dept_fixed)}")
    for r in dept_fixed[:6]:
        log(f"  {r['title']}")
    log(f"\nNews pages with titles now: {len(news_fixed)}")
    for r in news_fixed[:6]:
        log(f"  {r['title'][:80]}")

    log("\nDone.")


if __name__ == "__main__":
    main()

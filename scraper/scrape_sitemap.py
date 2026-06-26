#!/usr/bin/env python3
"""
Sitemap-based crawler for capetown.gov.za.
Fetches sitemap0.xml, extracts all URLs, crawls each page not already
in the inventory, then merges into output files.

Also directly crawls known department URLs (not in sitemap).

Usage:
    python3 scrape_sitemap.py --output ../output
"""

import argparse
import csv
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse, unquote
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

SITEMAP_URLS = [
    "https://www.capetown.gov.za/sitemap0.xml",
    "https://www.capetown.gov.za/sitemap_mobile0.xml",
]

# Known department slugs to try directly (site doesn't link them)
KNOWN_DEPARTMENTS = [
    "Budget-Office",
    "City-Health",
    "Community-Arts-and-Culture-Development",
    "Customer-Relations",
    "Development-Management",
    "Disaster-Risk-Management-Centre",
    "Electricity-Generation-and-Distribution",
    "Enterprise-and-Investment",
    "Environmental-Management",
    "Fire-and-Rescue-Service",
    "Human-Resources",
    "Law-Enforcement-Traffic-and-Coordination",
    "Metropolitan-Police-Services",
    "Office-of-the-City-Manager",
    "Public-Housing",
    "Safety-and-Security",
    "Treasury",
    "Urban-Planning-and-Design",
    "Water-and-Sanitation",
    "Rates-and-Valuations",
    "Corporate-Services",
    "Transport",
    "Social-Development-and-Early-Childhood-Development",
]

HEADERS = {
    "User-Agent": "CityMigrationBot/1.0 (content audit; contact zubeid.hendricks@gmail.com)",
    "Accept": "text/html,application/xhtml+xml,application/xml",
}

INVENTORY_FIELDS = [
    "sharepoint_url", "final_url", "http_status", "redirected",
    "sharepoint_path", "umbraco_path", "doc_type",
    "title", "description", "keywords", "og_title",
    "headings", "content_snippet",
]


def log(msg):
    print(msg, flush=True)


def to_umbraco_slug(raw_path: str) -> str:
    decoded = unquote(raw_path).strip("/")
    slug = decoded.lower()
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"\.aspx$", "", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    slug = re.sub(r"[^a-z0-9\-/]", "", slug)
    return "/" + slug.strip("/")


def infer_doctype(umbraco_path: str) -> str:
    top = umbraco_path.strip("/").split("/")[0]
    mapping = {
        "city-connect":           "CitizenServicesPage",
        "departments":            "DepartmentPage",
        "documents-and-policies": "DocumentPage",
        "explore-and-enjoy":      "ExploreContentPage",
        "family-and-home":        "ResidentialServicesPage",
        "local-and-communities":  "CommunityPage",
        "media-and-news":         "NewsArticlePage",
        "work-and-business":      "BusinessServicesPage",
    }
    return mapping.get(top, "ContentPage")


def normalise(url: str) -> str:
    p = urlparse(url)
    return p.scheme + "://" + p.netloc + p.path.rstrip("/")


def load_existing(csv_path: Path):
    if not csv_path.exists():
        return [], set()
    rows = []
    seen = set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
            seen.add(normalise(row["sharepoint_url"]))
    return rows, seen


def fetch_sitemap_urls(sitemap_url: str, session: requests.Session) -> list:
    urls = []
    try:
        resp = session.get(sitemap_url, timeout=20)
        if resp.status_code != 200:
            log(f"  Sitemap fetch failed: {resp.status_code} {sitemap_url}")
            return urls
        root = ElementTree.fromstring(resp.content)
        # Handle both sitemap index and regular sitemap
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        for loc in root.findall(".//sm:loc", ns):
            if loc.text:
                urls.append(loc.text.strip())
        log(f"  {sitemap_url}: {len(urls)} URLs found")
    except Exception as exc:
        log(f"  Sitemap error {sitemap_url}: {exc}")
    return urls


def scrape_page(url: str, session: requests.Session):
    try:
        resp = session.get(url, timeout=15, allow_redirects=True)
        if resp.status_code != 200:
            return None
        if "text/html" not in resp.headers.get("Content-Type", ""):
            return None
    except Exception as exc:
        log(f"  ERROR {url}: {exc}")
        return None

    soup = BeautifulSoup(resp.text, "lxml")

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    desc_tag = soup.find("meta", attrs={"name": "description"})
    description = desc_tag["content"].strip() if desc_tag and desc_tag.get("content") else ""

    kw_tag = soup.find("meta", attrs={"name": "keywords"})
    keywords = kw_tag["content"].strip() if kw_tag and kw_tag.get("content") else ""

    og_tag = soup.find("meta", property="og:title")
    og_title = og_tag["content"].strip() if og_tag and og_tag.get("content") else ""

    headings = [h.get_text(strip=True) for h in soup.find_all(["h1", "h2", "h3"])][:10]

    content = ""
    for selector in ("#DeltaPlaceHolderMain", ".ms-rtestate-field",
                     "main", "[role='main']", ".page-content", "body"):
        el = soup.select_one(selector)
        if el:
            content = el.get_text(separator=" ", strip=True)[:500]
            if content.strip():
                break

    parsed_orig = urlparse(url)
    parsed_final = urlparse(resp.url)
    umbraco_path = to_umbraco_slug(parsed_orig.path or "/")

    return {
        "sharepoint_url":  url,
        "final_url":       resp.url,
        "http_status":     str(resp.status_code),
        "redirected":      str(url != resp.url),
        "sharepoint_path": parsed_orig.path,
        "umbraco_path":    umbraco_path,
        "doc_type":        infer_doctype(umbraco_path),
        "title":           title,
        "description":     description,
        "keywords":        keywords,
        "og_title":        og_title,
        "headings":        " | ".join(h for h in headings if h),
        "content_snippet": content,
    }


def write_outputs(all_rows: list, out_dir: Path):
    csv_path = out_dir / "content_inventory.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=INVENTORY_FIELDS)
        writer.writeheader()
        writer.writerows(all_rows)
    log(f"Inventory written → {csv_path} ({len(all_rows)} rows)")

    mapping = {}
    nginx_lines = []
    iis_lines = []
    for p in all_rows:
        sp = p["sharepoint_path"].rstrip("/") or "/"
        ub = p["umbraco_path"]
        if sp == ub or not sp:
            continue
        mapping[sp] = ub
        nginx_lines.append(f'rewrite ^{re.escape(sp)}$ {ub} permanent;')
        iis_lines.append(
            f'<add input="{{REQUEST_URI}}" pattern="^{re.escape(sp)}$" negate="false" />'
        )

    with open(out_dir / "url_map.json", "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)
    (out_dir / "redirects_nginx.conf").write_text("\n".join(nginx_lines), encoding="utf-8")
    (out_dir / "redirects_iis_fragments.xml").write_text("\n".join(iis_lines), encoding="utf-8")
    log(f"URL map + redirects written ({len(mapping)} mappings)")

    nodes = []
    for p in all_rows:
        path_parts = p["umbraco_path"].strip("/").split("/")
        nodes.append({
            "key":        p["umbraco_path"],
            "parentPath": "/" + "/".join(path_parts[:-1]) if len(path_parts) > 1 else "/",
            "name":       path_parts[-1].replace("-", " ").title() if path_parts else p["title"],
            "docType":    p["doc_type"],
            "properties": {
                "pageTitle":      p["title"],
                "seoDescription": p["description"],
                "keywords":       p["keywords"],
                "legacyUrl":      p["sharepoint_url"],
            },
        })
    with open(out_dir / "umbraco_import.json", "w", encoding="utf-8") as f:
        json.dump(nodes, f, indent=2, ensure_ascii=False)
    log(f"Umbraco import JSON written ({len(nodes)} nodes)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="../output")
    parser.add_argument("--delay", type=float, default=0.4)
    args = parser.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    existing_rows, existing_urls = load_existing(out_dir / "content_inventory.csv")
    log(f"Loaded {len(existing_rows)} existing pages from inventory")

    session = requests.Session()
    session.headers.update(HEADERS)

    # --- Step 1: collect all URLs from sitemaps ---
    log("\n=== Step 1: Fetching sitemaps ===")
    sitemap_urls = []
    for sm in SITEMAP_URLS:
        sitemap_urls.extend(fetch_sitemap_urls(sm, session))

    # Deduplicate
    sitemap_urls = list(dict.fromkeys(sitemap_urls))
    log(f"Total unique sitemap URLs: {len(sitemap_urls)}")

    # --- Step 2: add known department URLs ---
    log("\n=== Step 2: Adding known department URLs ===")
    dept_urls = [
        f"https://www.capetown.gov.za/Departments/{name}"
        for name in KNOWN_DEPARTMENTS
    ]
    all_target_urls = sitemap_urls + dept_urls

    # Filter out already-crawled
    new_urls = [u for u in all_target_urls if normalise(u) not in existing_urls]
    log(f"New URLs to crawl: {len(new_urls)} (skipping {len(all_target_urls) - len(new_urls)} already in inventory)")

    # --- Step 3: crawl each new URL ---
    log("\n=== Step 3: Crawling new pages ===")
    new_rows = []
    for i, url in enumerate(new_urls, 1):
        data = scrape_page(url, session)
        if data:
            norm = normalise(url)
            if norm not in existing_urls:
                new_rows.append(data)
                existing_urls.add(norm)

        if i % 50 == 0:
            log(f"  Progress: {i}/{len(new_urls)} crawled, {len(new_rows)} new pages added")

        time.sleep(args.delay)

    log(f"\nNew pages collected: {len(new_rows)}")

    # --- Step 4: write merged output ---
    if new_rows:
        log("\n=== Step 4: Writing merged output ===")
        all_rows = existing_rows + new_rows
        write_outputs(all_rows, out_dir)

        # Summary by section
        from collections import Counter
        sections = Counter(r["umbraco_path"].strip("/").split("/")[0] for r in new_rows)
        log("\nNew pages by section:")
        for section, count in sections.most_common():
            log(f"  /{section}: {count}")

        log(f"\nTotal pages in inventory: {len(all_rows)}")
    else:
        log("No new pages found — inventory unchanged.")

    log("\nDone.")


if __name__ == "__main__":
    main()

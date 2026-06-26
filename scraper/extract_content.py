#!/usr/bin/env python3
"""
Phase 3 content extractor.
Re-visits every page in content_inventory.csv and pulls:
  - Full cleaned body HTML
  - Publish date (for news articles)
  - Tags/categories (from SharePoint taxonomy metadata)
  - Contact details (for department pages)

Output: output/content_extracted.jsonl  (one JSON object per line)
        output/content_extracted.csv    (summary for review)

Usage:
    python3 extract_content.py --output ../output --delay 0.4
"""

import argparse
import csv
import json
import re
import time
from pathlib import Path
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup, Comment

HEADERS = {
    "User-Agent": "CityMigrationBot/1.0 (content audit; contact zubeid.hendricks@gmail.com)",
    "Accept": "text/html,application/xhtml+xml",
}

# SharePoint taxonomy tag pattern: "GP0|#xxxxxxxx|Tag Name"
TAG_PATTERN = re.compile(r'L0\|#[0-9a-f-]+\|([^;|]+)', re.IGNORECASE)
# ISO date pattern
DATE_PATTERN = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}')

# Selectors to try for main content, in priority order
CONTENT_SELECTORS = [
    ".ms-rtestate-field",
    "#DeltaPlaceHolderMain",
    ".ms-core-contentBox",
    "#contentBox",
    "main",
    "[role='main']",
    ".page-content",
    "#ctl00_PlaceHolderMain_RichHtmlField1_ctl00",
]

# Elements to strip from body HTML before saving
STRIP_TAGS = ["script", "style", "noscript", "link", "meta",
              "svg", "iframe", "form", "input", "button"]

SUMMARY_FIELDS = [
    "umbraco_path", "doc_type", "title", "publish_date",
    "tags", "has_body", "body_length", "contact_email", "contact_phone",
]


def log(msg):
    print(msg, flush=True)


# -------------------------------------------------------------------------
# HTML cleaning
# -------------------------------------------------------------------------

def clean_html(soup_el) -> str:
    """Return clean inner HTML with SharePoint boilerplate stripped."""
    if soup_el is None:
        return ""

    clone = BeautifulSoup(str(soup_el), "lxml")

    # Remove noise tags
    for tag in clone.find_all(STRIP_TAGS):
        tag.decompose()

    # Remove HTML comments
    for comment in clone.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    # Remove SharePoint web part wrappers (empty divs with ms- classes)
    for tag in clone.find_all(True):
        cls = " ".join(tag.get("class", []))
        if any(c.startswith("ms-") for c in tag.get("class", [])):
            tag.unwrap()

    # Remove empty block elements
    for tag in clone.find_all(["div", "span", "p"]):
        if not tag.get_text(strip=True):
            tag.decompose()

    # Return inner HTML of the first body/div element
    body = clone.find("body") or clone
    return body.decode_contents().strip()


def extract_text(soup_el) -> str:
    if soup_el is None:
        return ""
    return soup_el.get_text(separator=" ", strip=True)


# -------------------------------------------------------------------------
# Field extractors
# -------------------------------------------------------------------------

def extract_body(soup) -> tuple:
    """Returns (html, text) of the main content zone."""
    for selector in CONTENT_SELECTORS:
        el = soup.select_one(selector)
        if el and el.get_text(strip=True):
            return clean_html(el), extract_text(el)
    # Fallback: body minus nav/header/footer
    body = soup.find("body")
    if body:
        for unwanted in body.find_all(["nav", "header", "footer", "aside"]):
            unwanted.decompose()
        return clean_html(body), extract_text(body)
    return "", ""


def extract_publish_date(soup) -> str:
    """Find an ISO date string anywhere on the page (news articles)."""
    # Check og:article:published_time first
    og = soup.find("meta", property="article:published_time")
    if og and og.get("content"):
        return og["content"][:10]

    # Scan all text nodes for ISO date pattern
    for el in soup.find_all(string=DATE_PATTERN):
        m = DATE_PATTERN.search(el)
        if m:
            return m.group()[:10]
    return ""


def extract_tags(soup) -> list:
    """Parse SharePoint taxonomy metadata fields for tag names."""
    tags = set()
    # Look in hidden input fields (SharePoint stores taxonomy here)
    for inp in soup.find_all("input", attrs={"type": "hidden"}):
        val = inp.get("value", "")
        for match in TAG_PATTERN.finditer(val):
            tag = match.group(1).strip()
            if tag and len(tag) < 60:
                tags.add(tag)
    # Also look in meta keywords
    kw = soup.find("meta", attrs={"name": "keywords"})
    if kw and kw.get("content"):
        for k in kw["content"].split(","):
            k = k.strip()
            if k:
                tags.add(k)
    return sorted(tags)


def extract_contact(text: str) -> tuple:
    """Extract email and phone from plain text."""
    email_m = re.search(r'[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}', text)
    phone_m = re.search(r'(?:\+27|0)\s*\d[\d\s-]{7,}', text)
    email = email_m.group() if email_m else ""
    phone = re.sub(r'\s+', ' ', phone_m.group()).strip() if phone_m else ""
    return email, phone


# -------------------------------------------------------------------------
# Main
# -------------------------------------------------------------------------

def process_page(url: str, doc_type: str, session: requests.Session):
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
    body_html, body_text = extract_body(soup)
    tags = extract_tags(soup)
    email, phone = extract_contact(body_text)
    publish_date = extract_publish_date(soup) if doc_type == "NewsArticlePage" else ""

    return {
        "sharepoint_url": url,
        "body_html":      body_html,
        "body_text":      body_text[:1000],
        "publish_date":   publish_date,
        "tags":           tags,
        "contact_email":  email,
        "contact_phone":  phone,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="../output")
    parser.add_argument("--delay",  type=float, default=0.4)
    parser.add_argument("--limit",  type=int,   default=0, help="0 = no limit")
    parser.add_argument("--resume", action="store_true", help="Skip URLs already in output JSONL")
    args = parser.parse_args()

    out_dir  = Path(args.output)
    csv_path = out_dir / "content_inventory.csv"
    jsonl_path = out_dir / "content_extracted.jsonl"
    sum_path   = out_dir / "content_extracted_summary.csv"

    # Load inventory
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    log(f"Loaded {len(rows)} pages from inventory")

    # Resume support — skip already extracted URLs
    already_done: set = set()
    if args.resume and jsonl_path.exists():
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    already_done.add(obj.get("sharepoint_url", ""))
                except Exception:
                    pass
        log(f"Resuming — {len(already_done)} URLs already extracted")

    session = requests.Session()
    session.headers.update(HEADERS)

    targets = rows
    if args.limit:
        targets = rows[:args.limit]

    extracted = 0
    summary_rows = []

    with open(jsonl_path, "a" if args.resume else "w", encoding="utf-8") as jsonl_f:
        for i, row in enumerate(targets, 1):
            url      = row["sharepoint_url"]
            doc_type = row["doc_type"]
            title    = row["title"]
            upath    = row["umbraco_path"]

            if url in already_done:
                continue

            data = process_page(url, doc_type, session)
            if data:
                data["umbraco_path"] = upath
                data["doc_type"]     = doc_type
                data["title"]        = title
                jsonl_f.write(json.dumps(data, ensure_ascii=False) + "\n")
                extracted += 1

                summary_rows.append({
                    "umbraco_path":   upath,
                    "doc_type":       doc_type,
                    "title":          title,
                    "publish_date":   data["publish_date"],
                    "tags":           "|".join(data["tags"]),
                    "has_body":       "yes" if data["body_html"] else "no",
                    "body_length":    len(data["body_html"]),
                    "contact_email":  data["contact_email"],
                    "contact_phone":  data["contact_phone"],
                })

            if i % 100 == 0:
                log(f"  {i}/{len(targets)} processed, {extracted} extracted")

            time.sleep(args.delay)

    log(f"\nExtracted content for {extracted} pages → {jsonl_path}")

    # Write summary CSV
    if summary_rows:
        with open(sum_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
            writer.writeheader()
            writer.writerows(summary_rows)
        log(f"Summary CSV → {sum_path}")

    # Stats
    has_body  = sum(1 for r in summary_rows if r["has_body"] == "yes")
    has_date  = sum(1 for r in summary_rows if r["publish_date"])
    has_tags  = sum(1 for r in summary_rows if r["tags"])
    has_email = sum(1 for r in summary_rows if r["contact_email"])
    log(f"\nStats: body={has_body}, dates={has_date}, tags={has_tags}, emails={has_email}")
    log("Done.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Post-processes content_extracted.jsonl in place:

  1. Strips SharePoint nav/header/footer boilerplate from body HTML,
     leaving only the article/page content zone.
  2. Filters out the 'matrix@capetown.gov' system email false positive.
  3. Re-extracts publish dates from human-readable date strings
     (e.g. "24 June 2026") rather than the dynamic ISO timestamp.
  4. Re-extracts tags from visible tag lists (SharePoint renders them
     as links in a .article-tags or .field-tags zone).

Reads  : output/content_extracted.jsonl
Writes : output/content_extracted.jsonl  (overwritten in place)
         output/content_extracted_summary.csv (refreshed)

Usage:
    python3 clean_content.py --output ../output
"""

import argparse
import csv
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

MONTH_MAP = {
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
    "jan":1,"feb":2,"mar":3,"apr":4,"jun":6,"jul":7,"aug":8,
    "sep":9,"oct":10,"nov":11,"dec":12,
}

# "24 June 2026" / "24 Jun 2026" / "June 24, 2026"
HUMAN_DATE = re.compile(
    r'(?:(\d{1,2})\s+([A-Za-z]+)\s+(\d{4}))'   # 24 June 2026
    r'|(?:([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4}))',# June 24, 2026
    re.IGNORECASE
)

SYSTEM_EMAILS = {"matrix@capetown.gov", "noreply@capetown.gov.za"}

SUMMARY_FIELDS = [
    "umbraco_path","doc_type","title","publish_date",
    "tags","has_body","body_length","contact_email","contact_phone",
]

# Nav/chrome selectors to remove before saving body
STRIP_SELECTORS = [
    "header", "footer", "nav",
    ".header-container", ".footer-container",
    ".ms-siteactionsmenu", "#suiteBar", "#suiteBarLeft", "#suiteBarRight",
    ".ms-globalNavBox", ".ms-core-overlay",
    "#sideNavBox", "#contentBox > nav",
    ".breadcrumb", ".bread-crumb",
    '[role="navigation"]', '[role="banner"]', '[role="contentinfo"]',
    ".cookie-banner", "#cookie-consent",
    ".search-bar", ".site-search",
]


def log(msg):
    print(msg, flush=True)


def clean_body(raw_html: str) -> tuple:
    """Strip nav chrome from raw HTML, return (clean_html, clean_text)."""
    if not raw_html:
        return "", ""

    soup = BeautifulSoup(raw_html, "lxml")

    # Remove nav/header/footer elements
    for sel in STRIP_SELECTORS:
        for el in soup.select(sel):
            el.decompose()

    # Remove script/style
    for tag in soup.find_all(["script", "style", "noscript", "link"]):
        tag.decompose()

    # Try to find the tightest content zone that has real text
    for selector in [
        ".ms-rtestate-field",
        "article",
        ".article-body",
        ".page-content",
        ".content-area",
        "#contentBox",
        "main",
        '[role="main"]',
    ]:
        el = soup.select_one(selector)
        if el:
            text = el.get_text(" ", strip=True)
            if len(text) > 100:
                return str(el), text

    # Fallback: whatever's left after stripping nav
    body = soup.find("body") or soup
    text = body.get_text(" ", strip=True)
    return str(body), text


def extract_human_date(html: str) -> str:
    """Find the first human-readable date like '24 June 2026'."""
    for m in HUMAN_DATE.finditer(html):
        try:
            if m.group(1):  # DD Month YYYY
                day, month_str, year = m.group(1), m.group(2), m.group(3)
            else:            # Month DD, YYYY
                month_str, day, year = m.group(4), m.group(5), m.group(6)
            month = MONTH_MAP.get(month_str.lower())
            if month:
                return f"{int(year):04d}-{month:02d}-{int(day):02d}"
        except Exception:
            continue
    return ""


def extract_tags_from_html(html: str) -> list:
    """Extract visible tag/category links from rendered HTML."""
    soup = BeautifulSoup(html, "lxml")
    tags = set()
    for sel in [".article-tags a", ".field-tags a", ".tags a",
                ".category a", ".topics a", '[rel="tag"]']:
        for el in soup.select(sel):
            t = el.get_text(strip=True)
            if t and 2 < len(t) < 60:
                tags.add(t)
    return sorted(tags)


def clean_email(email: str) -> str:
    if not email:
        return ""
    if email.lower() in SYSTEM_EMAILS:
        return ""
    # Must look like a real government address
    if "@capetown.gov.za" in email.lower() or "@capetown.gov" == email.lower().split("@")[-1]:
        return ""  # generic system domain — skip unless specific dept
    return email


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="../output")
    args = parser.parse_args()

    out_dir   = Path(args.output)
    jsonl_in  = out_dir / "content_extracted.jsonl"
    jsonl_tmp = out_dir / "content_extracted_clean.jsonl"
    sum_path  = out_dir / "content_extracted_summary.csv"

    lines = jsonl_in.read_text(encoding="utf-8").splitlines()
    log(f"Loaded {len(lines)} records from {jsonl_in}")

    cleaned_rows = []
    summary_rows = []

    for i, line in enumerate(lines, 1):
        if not line.strip():
            continue
        obj = json.loads(line)

        raw_html = obj.get("body_html", "")
        clean_html, clean_text = clean_body(raw_html)

        # Re-extract date from human-readable strings in clean HTML
        date = extract_human_date(clean_html) or extract_human_date(raw_html)

        # Re-extract tags from visible HTML
        tags = extract_tags_from_html(clean_html) or obj.get("tags", [])

        # Clean email
        email = clean_email(obj.get("contact_email", ""))

        obj["body_html"]     = clean_html
        obj["body_text"]     = clean_text[:1000]
        obj["publish_date"]  = date
        obj["tags"]          = tags
        obj["contact_email"] = email

        cleaned_rows.append(obj)

        summary_rows.append({
            "umbraco_path":  obj.get("umbraco_path",""),
            "doc_type":      obj.get("doc_type",""),
            "title":         obj.get("title",""),
            "publish_date":  date,
            "tags":          "|".join(tags),
            "has_body":      "yes" if clean_html else "no",
            "body_length":   len(clean_html),
            "contact_email": email,
            "contact_phone": obj.get("contact_phone",""),
        })

        if i % 500 == 0:
            log(f"  {i}/{len(lines)} cleaned")

    # Write cleaned JSONL
    with open(jsonl_tmp, "w", encoding="utf-8") as f:
        for obj in cleaned_rows:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    # Replace original
    jsonl_tmp.replace(jsonl_in)
    log(f"Cleaned JSONL written → {jsonl_in}")

    # Write summary
    with open(sum_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(summary_rows)
    log(f"Summary CSV written → {sum_path}")

    # Stats
    has_body  = sum(1 for r in summary_rows if r["has_body"]=="yes")
    has_date  = sum(1 for r in summary_rows if r["publish_date"])
    has_tags  = sum(1 for r in summary_rows if r["tags"])
    has_email = sum(1 for r in summary_rows if r["contact_email"])
    log(f"\nFinal stats: body={has_body}, dates={has_date}, tags={has_tags}, real emails={has_email}")
    log("Done.")


if __name__ == "__main__":
    main()

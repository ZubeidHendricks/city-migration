#!/usr/bin/env python3
"""
For pages where the title is a useless SharePoint generic value
('City of Cape Town Link', 'Media and News', etc.), derive the title
from the URL path — which for news articles literally IS the article title.
Also cleans up department names from slugs.

Usage:
    python3 fix_titles_from_url.py --output ../output
"""

import argparse
import csv
import re
from pathlib import Path
from urllib.parse import unquote

INVENTORY_FIELDS = [
    "sharepoint_url", "final_url", "http_status", "redirected",
    "sharepoint_path", "umbraco_path", "doc_type",
    "title", "description", "keywords", "og_title",
    "headings", "content_snippet",
]

GENERIC_TITLES = {
    "city of cape town link",
    "media and news",
    "city of cape town",
    "capetown.gov.za",
    "",
}


def log(msg):
    print(msg, flush=True)


def title_from_path(path: str) -> str:
    """Extract a human-readable title from a URL path."""
    decoded = unquote(path).strip("/")
    # Take the last path segment
    last_segment = decoded.split("/")[-1] if "/" in decoded else decoded
    # Remove .aspx
    last_segment = re.sub(r"\.aspx$", "", last_segment, flags=re.IGNORECASE)
    # Replace hyphens/underscores with spaces and title-case
    title = last_segment.replace("-", " ").replace("_", " ")
    # Title-case only if it's all lowercase (slugs); preserve mixed-case (real titles)
    if title == title.lower():
        title = title.title()
    return title.strip()


def clean_department_title(path: str) -> str:
    """Turn /Departments/City-Health → 'City Health Department'"""
    decoded = unquote(path).strip("/")
    parts = decoded.split("/")
    if len(parts) >= 2 and parts[0].lower() == "departments":
        name = parts[-1].replace("-", " ").replace("_", " ").title()
        # Avoid double "Department Department"
        if not name.lower().endswith("department"):
            name = name + " Department"
        return name
    return title_from_path(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="../output")
    args = parser.parse_args()

    out_dir = Path(args.output)
    csv_path = out_dir / "content_inventory.csv"

    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    fixed = 0
    for row in rows:
        current_title = row.get("title", "").strip()
        if current_title.lower() not in GENERIC_TITLES:
            continue  # already has a real title

        path = row.get("sharepoint_path", "")
        doc_type = row.get("doc_type", "")

        if doc_type == "DepartmentPage":
            new_title = clean_department_title(path)
        else:
            new_title = title_from_path(path)

        if new_title:
            row["title"] = new_title
            fixed += 1

    log(f"Fixed {fixed} titles from URL paths")

    # Write back
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=INVENTORY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    log(f"Inventory updated → {csv_path}")

    # Show samples
    dept = [r for r in rows if r["doc_type"] == "DepartmentPage"]
    news = [r for r in rows if r["doc_type"] == "NewsArticlePage"]
    empty = [r for r in rows if not r["title"].strip()]

    log(f"\nSample department titles:")
    for r in dept[:8]:
        log(f"  {r['title']}")

    log(f"\nSample news titles:")
    for r in news[:8]:
        log(f"  {r['title'][:80]}")

    log(f"\nRows still missing a title: {len(empty)}")
    log("\nDone.")


if __name__ == "__main__":
    main()

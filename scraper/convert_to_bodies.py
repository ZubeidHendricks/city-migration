#!/usr/bin/env python3
"""
Converts output/content_extracted.jsonl into the bodies.json format used by
BodyContentMigrator in capetown-umbraco.

Merges with the EXISTING bodies.json (dedup by matchKey so Frontify entries
win over scraped entries where both cover the same page title).

Output: writes directly to capetown-umbraco/src/CapeTown.Web/SeedData/bodies.json

Usage:
    python3 convert_to_bodies.py \
        --jsonl  ../output/content_extracted.jsonl \
        --existing ../../capetown-umbraco/src/CapeTown.Web/SeedData/bodies.json \
        --output   ../../capetown-umbraco/src/CapeTown.Web/SeedData/bodies.json
"""

import argparse
import json
import re
import unicodedata
from pathlib import Path

DEDUP_SUFFIX = re.compile(r'\s*\(\d+\)\s*$')
NON_ALNUM    = re.compile(r'[^a-z0-9]+')
SPACES_RE    = re.compile(r'\s+')

# Maps our doc_type → content set name (mirrors ActionPagesMigrator / BodyContentMigrator)
DOCTYPE_SET_MAP = {
    "NewsArticlePage":         "MediaReleases",
    "DepartmentPage":          "Departments",
    "CitizenServicesPage":     "ActionPages",
    "ResidentialServicesPage": "ResidentialServices",
    "ExploreContentPage":      "ExploreAndEnjoy",
    "BusinessServicesPage":    "WorkAndBusiness",
    "CommunityPage":           "LocalAndCommunities",
    "DocumentPage":            "Documents",
    "ContentPage":             "General",
}


def log(msg):
    print(msg, flush=True)


def match_key(s: str) -> str:
    """Normalise a title to a lookup key — MUST mirror MatchKey() in BodyContentMigrator.cs."""
    if not s:
        return ""
    # NFKD normalisation + strip diacritics
    d = unicodedata.normalize("NFKD", s)
    cleaned = "".join(c for c in d if unicodedata.category(c) != "Mn"
                      and c not in ("​", "﻿"))
    t = DEDUP_SUFFIX.sub("", cleaned.strip())
    t = t.replace("&", " and ")
    t = NON_ALNUM.sub(" ", t.lower())
    return SPACES_RE.sub(" ", t).strip()


def build_body_entry(obj: dict) -> dict:
    """Convert a content_extracted.jsonl record to a bodies.json entry."""
    upath    = obj.get("umbraco_path", "")
    title    = obj.get("title", "").strip()
    doc_type = obj.get("doc_type", "ContentPage")
    body_html = obj.get("body_html", "")

    # Split body into intro (first block) + content (rest)
    intro   = ""
    content = body_html

    # For news articles: wrap with article metadata
    if doc_type == "NewsArticlePage":
        date = obj.get("publish_date", "")
        if date:
            intro = f'<p class="article-date">{date}</p>'

    tags     = obj.get("tags", [])
    summary  = obj.get("description", "")[:300] if obj.get("description") else ""

    # Derive a compact summary from body text if description is empty
    if not summary and obj.get("body_text"):
        words = obj["body_text"].split()[:40]
        summary = " ".join(words) + ("…" if len(words) == 40 else "")

    return {
        "key":      upath,
        "matchKey": match_key(title),
        "title":    title,
        "nav":      obj.get("sharepoint_path", ""),
        "set":      DOCTYPE_SET_MAP.get(doc_type, "General"),
        "summary":  summary,
        "keywords": tags[:8],   # controlled tags (from scraped taxonomy)
        "freeform": [],         # no freeform tags from scraper
        "image":    "",
        "intro":    intro,
        "content":  content,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--jsonl",    default="../output/content_extracted.jsonl")
    parser.add_argument("--existing", default="../../capetown-umbraco/src/CapeTown.Web/SeedData/bodies.json")
    parser.add_argument("--output",   default="../../capetown-umbraco/src/CapeTown.Web/SeedData/bodies.json")
    parser.add_argument("--min-body", type=int, default=100,
                        help="Skip entries whose body HTML is shorter than this (likely nav-only pages)")
    args = parser.parse_args()

    # Load existing bodies.json — Frontify entries take priority
    existing_path = Path(args.existing)
    existing: list = []
    existing_keys: set = set()
    if existing_path.exists():
        with open(existing_path, encoding="utf-8") as f:
            existing = json.load(f)
        existing_keys = {e.get("matchKey") or match_key(e.get("title", "")) for e in existing}
        log(f"Loaded {len(existing)} existing bodies.json entries ({len(existing_keys)} unique keys)")
    else:
        log("No existing bodies.json found — creating fresh")

    # Load and convert scraped content
    jsonl_path = Path(args.jsonl)
    if not jsonl_path.exists():
        log(f"ERROR: {jsonl_path} not found. Run extract_content.py first.")
        return

    new_entries = []
    skipped_short = 0
    skipped_dup   = 0
    skipped_notitle = 0

    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)

            # Skip pages without a meaningful title
            title = obj.get("title", "").strip()
            if not title or title.lower() in ("media and news", "city of cape town link",
                                               "media and news - city of cape town", ""):
                skipped_notitle += 1
                continue

            # Skip pages with very little body content (nav-only pages)
            if len(obj.get("body_html", "")) < args.min_body:
                skipped_short += 1
                continue

            mk = match_key(title)

            # Frontify entries win — don't overwrite with scraped content
            if mk in existing_keys:
                skipped_dup += 1
                continue

            entry = build_body_entry(obj)
            new_entries.append(entry)
            existing_keys.add(mk)

    log(f"Scraped entries to add: {len(new_entries)}")
    log(f"Skipped — duplicate (Frontify wins): {skipped_dup}")
    log(f"Skipped — body too short (<{args.min_body} chars): {skipped_short}")
    log(f"Skipped — no usable title: {skipped_notitle}")

    # Merge: existing Frontify entries first, then new scraped entries
    merged = existing + new_entries
    log(f"Total merged bodies.json: {len(merged)} entries")

    # Breakdown by set
    from collections import Counter
    sets = Counter(e.get("set", "Unknown") for e in new_entries)
    log("\nNew entries by content set:")
    for s, c in sets.most_common():
        log(f"  {s}: {c}")

    # Write output
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    log(f"\nWritten → {out_path} ({out_path.stat().st_size / 1_048_576:.1f} MB)")
    log("Done.")


if __name__ == "__main__":
    main()

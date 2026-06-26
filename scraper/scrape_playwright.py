#!/usr/bin/env python3
"""
Targeted Playwright crawler for JS-rendered sections of capetown.gov.za.
Covers /Departments and /Media-and-news which require JavaScript to render.
Merges results into the existing content_inventory.csv and output files.

Usage:
    python3 scrape_playwright.py --output ../output
"""

import argparse
import csv
import json
import re
import time
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE_URL = "https://www.capetown.gov.za"

TARGET_SECTIONS = [
    "https://www.capetown.gov.za/Departments",
    "https://www.capetown.gov.za/Media-and-news",
]

EXCLUDED_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                        ".zip", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".css", ".js")

SECTION_DOCTYPE_MAP = {
    "departments":    "DepartmentPage",
    "media-and-news": "NewsArticlePage",
}


def to_umbraco_slug(raw_path: str) -> str:
    decoded = unquote(raw_path).strip("/")
    slug = decoded.lower()
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"\.aspx$", "", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    slug = re.sub(r"[^a-z0-9\-/]", "", slug)
    return "/" + slug.strip("/")


def infer_doctype(umbraco_path: str) -> str:
    parts = umbraco_path.strip("/").split("/")
    if parts:
        top = parts[0]
        for key, dtype in SECTION_DOCTYPE_MAP.items():
            if top == key:
                return dtype
    return "ContentPage"


def log(msg: str):
    print(msg, flush=True)


def is_crawlable(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc and "capetown.gov.za" not in parsed.netloc:
        return False
    path = parsed.path.lower()
    if any(path.endswith(ext) for ext in EXCLUDED_EXTENSIONS):
        return False
    if any(x in path for x in ("/_layouts/", "/_api/", "/_vti_bin/", "/style%20library/")):
        return False
    return True


def normalise(url: str) -> str:
    p = urlparse(url)
    return p.scheme + "://" + p.netloc + p.path.rstrip("/")


def extract_links(page, base_url: str) -> list:
    links = []
    try:
        anchors = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
        for href in anchors:
            if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue
            absolute = urljoin(base_url, href)
            norm = normalise(absolute)
            if is_crawlable(norm):
                links.append(norm)
    except Exception:
        pass
    return links


def extract_page_data(page, url: str) -> dict:
    title = ""
    description = ""
    headings = []
    content = ""

    try:
        title = page.title() or ""
    except Exception:
        pass

    try:
        desc_el = page.query_selector('meta[name="description"]')
        if desc_el:
            description = desc_el.get_attribute("content") or ""
    except Exception:
        pass

    try:
        headings = page.eval_on_selector_all(
            "h1, h2, h3",
            "els => els.slice(0,10).map(e => e.innerText.trim())"
        )
    except Exception:
        pass

    # Try SharePoint content zones, then fall back
    for selector in ("#DeltaPlaceHolderMain", ".ms-rtestate-field",
                     "main", "[role='main']", ".page-content", "body"):
        try:
            el = page.query_selector(selector)
            if el:
                content = (el.inner_text() or "")[:500]
                if content.strip():
                    break
        except Exception:
            pass

    parsed = urlparse(url)
    umbraco_path = to_umbraco_slug(parsed.path or "/")

    return {
        "sharepoint_url":  url,
        "final_url":       url,
        "http_status":     "200",
        "redirected":      "False",
        "sharepoint_path": parsed.path,
        "umbraco_path":    umbraco_path,
        "doc_type":        infer_doctype(umbraco_path),
        "title":           title.strip(),
        "description":     description.strip(),
        "keywords":        "",
        "og_title":        "",
        "headings":        " | ".join(h for h in headings if h),
        "content_snippet": content.strip(),
    }


INVENTORY_FIELDS = [
    "sharepoint_url", "final_url", "http_status", "redirected",
    "sharepoint_path", "umbraco_path", "doc_type",
    "title", "description", "keywords", "og_title",
    "headings", "content_snippet",
]


def load_existing(csv_path: Path) -> tuple[list[dict], set[str]]:
    if not csv_path.exists():
        return [], set()
    rows = []
    seen = set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
            seen.add(normalise(row["sharepoint_url"]))
    return rows, seen


def crawl_section(playwright, start_url: str, visited: set, max_pages: int = 500, delay: float = 0.8) -> list[dict]:
    pages_data = []
    queue = deque([normalise(start_url)])
    section_visited = set()

    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="CityMigrationBot/1.0 (content audit; contact zubeid.hendricks@gmail.com)",
        viewport={"width": 1280, "height": 800},
    )
    page = context.new_page()
    # Block images/fonts/media to speed up rendering
    page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,mp4,webm}", lambda r: r.abort())

    log(f"\n--- Crawling section: {start_url} (max {max_pages} pages) ---")

    while queue and len(section_visited) < max_pages:
        url = queue.popleft()
        norm = normalise(url)

        if norm in section_visited or norm in visited:
            continue
        section_visited.add(norm)

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            # Wait for any dynamic content to render
            page.wait_for_timeout(1200)
        except PWTimeout:
            log(f"  TIMEOUT {url}")
            continue
        except Exception as exc:
            log(f"  ERROR {url}: {exc}")
            continue

        final_url = page.url
        data = extract_page_data(page, final_url)
        pages_data.append(data)

        new_links = extract_links(page, final_url)
        # Only follow links that stay within the same section
        section_prefix = urlparse(start_url).path.rstrip("/").lower()
        for link in new_links:
            link_path = urlparse(link).path.lower()
            if link_path.startswith(section_prefix) and normalise(link) not in section_visited:
                queue.append(link)

        count = len(section_visited)
        if count % 10 == 0:
            log(f"  Crawled {count} pages in section, queue={len(queue)}")

        time.sleep(delay)

    context.close()
    browser.close()
    log(f"  Section done: {len(pages_data)} pages collected")
    return pages_data


def write_outputs(all_rows: list[dict], out_dir: Path):
    # CSV inventory
    csv_path = out_dir / "content_inventory.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=INVENTORY_FIELDS)
        writer.writeheader()
        writer.writerows(all_rows)
    log(f"Inventory written → {csv_path} ({len(all_rows)} rows)")

    # URL map + redirect rules
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

    # Umbraco import JSON
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
    parser = argparse.ArgumentParser(description="Playwright crawler for JS-rendered sections")
    parser.add_argument("--output", default="../output")
    parser.add_argument("--max-pages", type=int, default=500)
    parser.add_argument("--delay", type=float, default=0.8)
    args = parser.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load what the basic scraper already collected
    existing_rows, existing_urls = load_existing(out_dir / "content_inventory.csv")
    log(f"Loaded {len(existing_rows)} existing pages from inventory")

    new_rows = []
    with sync_playwright() as playwright:
        for section_url in TARGET_SECTIONS:
            section_rows = crawl_section(
                playwright,
                section_url,
                visited=existing_urls,
                max_pages=args.max_pages,
                delay=args.delay,
            )
            # Only add pages not already in the inventory
            for row in section_rows:
                norm = normalise(row["sharepoint_url"])
                if norm not in existing_urls:
                    new_rows.append(row)
                    existing_urls.add(norm)

    log(f"\nNew pages discovered: {len(new_rows)}")

    if new_rows:
        all_rows = existing_rows + new_rows
        write_outputs(all_rows, out_dir)
        log(f"\nMerge complete. Total pages in inventory: {len(all_rows)}")
    else:
        log("No new pages found — inventory unchanged.")

    log("\nDone.")


if __name__ == "__main__":
    main()

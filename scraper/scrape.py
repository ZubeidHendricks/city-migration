#!/usr/bin/env python3
"""
Cape Town SharePoint → Umbraco migration scraper.
Crawls capetown.gov.za, extracts page structure, content, and metadata,
then writes a content inventory CSV and a URL mapping JSON.

Usage:
    pip install requests beautifulsoup4 lxml
    python scrape.py
    python scrape.py --max-pages 500 --output ../output
"""

import argparse
import csv
import json
import re
import sys
import time
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup

# Force unbuffered output so progress shows in background runs
def log(msg):
    print(msg, flush=True)

BASE_URL = "https://www.capetown.gov.za"
ALLOWED_DOMAIN = "capetown.gov.za"
EXCLUDED_PREFIXES = (
    "/_layouts/",
    "/Style%20Library/",
    "/SiteAssets/",
    "/Document-centre/",      # binary downloads — handle separately
    "/_api/",
    "/_vti_bin/",
)
EXCLUDED_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                        ".zip", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".css", ".js")

HEADERS = {
    "User-Agent": "CityMigrationBot/1.0 (content audit; contact zubeid.hendricks@gmail.com)",
    "Accept": "text/html,application/xhtml+xml",
}

# ---------------------------------------------------------------------------
# Umbraco-friendly slug conversion
# ---------------------------------------------------------------------------

def to_umbraco_slug(raw_path: str) -> str:
    """Convert a raw SharePoint URL path to a clean Umbraco-friendly slug."""
    decoded = unquote(raw_path).strip("/")
    # Lowercase, replace spaces and underscores with hyphens
    slug = decoded.lower()
    slug = re.sub(r"[\s_]+", "-", slug)
    # Remove .aspx extension
    slug = re.sub(r"\.aspx$", "", slug)
    # Strip multiple hyphens
    slug = re.sub(r"-{2,}", "-", slug)
    # Strip non-alphanumeric except hyphens and slashes
    slug = re.sub(r"[^a-z0-9\-/]", "", slug)
    return "/" + slug.strip("/")


# ---------------------------------------------------------------------------
# Section → Umbraco Document Type mapping
# ---------------------------------------------------------------------------

SECTION_DOCTYPE_MAP = {
    "city-connect":          "CitizenServicesPage",
    "departments":           "DepartmentPage",
    "documents-and-policies":"DocumentPage",
    "explore-and-enjoy":     "ExploreContentPage",
    "family-and-home":       "ResidentialServicesPage",
    "local-and-communities": "CommunityPage",
    "media-and-news":        "NewsArticlePage",
    "work-and-business":     "BusinessServicesPage",
}

def infer_doctype(umbraco_path: str) -> str:
    parts = umbraco_path.strip("/").split("/")
    if parts:
        top = parts[0]
        for key, dtype in SECTION_DOCTYPE_MAP.items():
            if top == key:
                return dtype
    return "ContentPage"


# ---------------------------------------------------------------------------
# Core crawler
# ---------------------------------------------------------------------------

class SiteCrawler:
    def __init__(self, base_url: str, max_pages: int = 2000, delay: float = 0.5):
        self.base_url = base_url
        self.max_pages = max_pages
        self.delay = delay
        self.visited: set[str] = set()
        self.queue: deque[str] = deque([base_url])
        self.pages: list[dict] = []
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def _is_crawlable(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.netloc and ALLOWED_DOMAIN not in parsed.netloc:
            return False
        path = parsed.path.lower()
        if any(path.startswith(p.lower()) for p in EXCLUDED_PREFIXES):
            return False
        if any(path.endswith(ext) for ext in EXCLUDED_EXTENSIONS):
            return False
        return True

    def _normalise(self, url: str) -> str:
        parsed = urlparse(url)
        # Drop query string and fragment for dedup
        return parsed.scheme + "://" + parsed.netloc + parsed.path.rstrip("/")

    def _extract_links(self, soup: BeautifulSoup, page_url: str) -> list[str]:
        links = []
        for tag in soup.find_all("a", href=True):
            href = tag["href"].strip()
            if href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            absolute = urljoin(page_url, href)
            norm = self._normalise(absolute)
            if self._is_crawlable(norm) and norm not in self.visited:
                links.append(norm)
        return links

    def _extract_meta(self, soup: BeautifulSoup) -> dict:
        meta = {}
        title_tag = soup.find("title")
        meta["title"] = title_tag.get_text(strip=True) if title_tag else ""

        for name in ("description", "keywords"):
            tag = soup.find("meta", attrs={"name": name})
            meta[name] = tag["content"].strip() if tag and tag.get("content") else ""

        # SharePoint page layout hint
        layout_tag = soup.find("meta", attrs={"name": "Microsoft Border"})
        meta["sharepoint_layout"] = layout_tag["content"] if layout_tag else ""

        # OG tags
        og_title = soup.find("meta", property="og:title")
        meta["og_title"] = og_title["content"] if og_title and og_title.get("content") else ""

        return meta

    def _extract_headings(self, soup: BeautifulSoup) -> list[str]:
        return [h.get_text(strip=True) for h in soup.find_all(["h1", "h2", "h3"])][:10]

    def _extract_main_content(self, soup: BeautifulSoup) -> str:
        # Try common SharePoint content zones first
        for selector in ("#DeltaPlaceHolderMain", ".ms-rtestate-field",
                         "main", "[role='main']", "#contentBox", ".page-content"):
            el = soup.select_one(selector)
            if el:
                return el.get_text(separator=" ", strip=True)[:2000]
        # Fallback: body text
        body = soup.find("body")
        return body.get_text(separator=" ", strip=True)[:2000] if body else ""

    def crawl(self):
        log(f"Starting crawl of {self.base_url} (max {self.max_pages} pages)")
        while self.queue and len(self.visited) < self.max_pages:
            url = self.queue.popleft()
            norm = self._normalise(url)
            if norm in self.visited:
                continue
            self.visited.add(norm)

            try:
                resp = self.session.get(url, timeout=15, allow_redirects=True)
                final_url = resp.url
                if resp.status_code != 200:
                    log(f"  SKIP {resp.status_code} {url}")
                    continue
                if "text/html" not in resp.headers.get("Content-Type", ""):
                    continue
            except Exception as exc:
                log(f"  ERROR {url}: {exc}")
                continue

            soup = BeautifulSoup(resp.text, "lxml")
            meta = self._extract_meta(soup)
            parsed_orig = urlparse(url)
            parsed_final = urlparse(final_url)

            umbraco_path = to_umbraco_slug(parsed_orig.path or "/")

            record = {
                "sharepoint_url":   url,
                "final_url":        final_url,
                "http_status":      resp.status_code,
                "redirected":       url != final_url,
                "sharepoint_path":  parsed_orig.path,
                "umbraco_path":     umbraco_path,
                "doc_type":         infer_doctype(umbraco_path),
                "title":            meta["title"],
                "description":      meta["description"],
                "keywords":         meta["keywords"],
                "og_title":         meta["og_title"],
                "headings":         " | ".join(self._extract_headings(soup)),
                "content_snippet":  self._extract_main_content(soup)[:500],
            }
            self.pages.append(record)

            new_links = self._extract_links(soup, final_url)
            self.queue.extend(new_links)

            count = len(self.visited)
            if count % 25 == 0:
                log(f"  Crawled {count} pages, queue={len(self.queue)}")

            time.sleep(self.delay)

        log(f"Crawl complete. {len(self.pages)} pages collected.")
        return self.pages


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

INVENTORY_FIELDS = [
    "sharepoint_url", "final_url", "http_status", "redirected",
    "sharepoint_path", "umbraco_path", "doc_type",
    "title", "description", "keywords", "og_title",
    "headings", "content_snippet",
]

def write_inventory(pages: list[dict], out_dir: Path):
    path = out_dir / "content_inventory.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=INVENTORY_FIELDS)
        writer.writeheader()
        writer.writerows(pages)
    log(f"Inventory written → {path}")


def write_url_map(pages: list[dict], out_dir: Path):
    """
    Produces two artefacts:
      url_map.json  – machine-readable { sharepoint_path: umbraco_path }
      redirects.txt – nginx/IIS rewrite rules (one per line)
    """
    mapping = {}
    nginx_lines = []
    iis_lines = []

    for p in pages:
        sp = p["sharepoint_path"].rstrip("/") or "/"
        ub = p["umbraco_path"]
        if sp == ub or not sp:
            continue
        mapping[sp] = ub

        # nginx rewrite (301)
        # Escape spaces still present in original paths
        nginx_sp = sp.replace(" ", r"\s")
        nginx_lines.append(f'rewrite ^{re.escape(sp)}$ {ub} permanent;')

        # IIS URL rewrite (web.config fragment)
        iis_lines.append(
            f'<add input="{{REQUEST_URI}}" pattern="^{re.escape(sp)}$" '
            f'negate="false" />'
        )

    json_path = out_dir / "url_map.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)
    log(f"URL map written → {json_path}")

    nginx_path = out_dir / "redirects_nginx.conf"
    nginx_path.write_text("\n".join(nginx_lines), encoding="utf-8")
    log(f"Nginx redirects written → {nginx_path}")

    iis_path = out_dir / "redirects_iis_fragments.xml"
    iis_path.write_text("\n".join(iis_lines), encoding="utf-8")
    log(f"IIS redirect fragments written → {iis_path}")


def write_umbraco_import(pages: list[dict], out_dir: Path):
    """
    JSON structure Umbraco's uSync or a custom import tool can consume.
    Each entry maps to one Umbraco node.
    """
    nodes = []
    for p in pages:
        path_parts = p["umbraco_path"].strip("/").split("/")
        nodes.append({
            "key":        p["umbraco_path"],
            "parentPath": "/" + "/".join(path_parts[:-1]) if len(path_parts) > 1 else "/",
            "name":       path_parts[-1].replace("-", " ").title() if path_parts else p["title"],
            "docType":    p["doc_type"],
            "properties": {
                "pageTitle":   p["title"],
                "seoDescription": p["description"],
                "keywords":    p["keywords"],
                "legacyUrl":   p["sharepoint_url"],
            },
        })
    out_path = out_dir / "umbraco_import.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(nodes, f, indent=2, ensure_ascii=False)
    log(f"Umbraco import JSON written → {out_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Cape Town SharePoint scraper")
    parser.add_argument("--max-pages", type=int, default=2000,
                        help="Maximum pages to crawl (default 2000)")
    parser.add_argument("--delay", type=float, default=0.5,
                        help="Seconds between requests (default 0.5)")
    parser.add_argument("--output", default="../output",
                        help="Output directory (default ../output)")
    args = parser.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    crawler = SiteCrawler(BASE_URL, max_pages=args.max_pages, delay=args.delay)
    pages = crawler.crawl()

    write_inventory(pages, out_dir)
    write_url_map(pages, out_dir)
    write_umbraco_import(pages, out_dir)

    log("\nDone. Next steps:")
    log("  1. Review output/content_inventory.csv — fix any doc_type assignments")
    log("  2. Review output/url_map.json — adjust slugs as needed")
    log("  3. Import output/umbraco_import.json via the Umbraco migration tool")
    log("  4. Deploy output/redirects_nginx.conf (or IIS equivalent) to the old server")


if __name__ == "__main__":
    main()

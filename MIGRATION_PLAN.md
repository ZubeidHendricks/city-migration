# Cape Town SharePoint → Umbraco Migration Plan

## Overview

Migrating **capetown.gov.za** from Microsoft SharePoint 2013/Online to Umbraco CMS.
The site has ~8 top-level sections, ~30 departments, and hundreds of content pages.

---

## Phase 1 — Content Audit & Scrape

### What the scraper does

`scraper/scrape.py` crawls the live SharePoint site and produces three files in `output/`:

| File | Purpose |
|---|---|
| `content_inventory.csv` | Every crawled page: URL, title, doc type, content snippet |
| `url_map.json` | `{ sharepoint_path: umbraco_path }` mapping for every page |
| `redirects_nginx.conf` | Ready-to-deploy 301 redirect rules |
| `redirects_iis_fragments.xml` | IIS URL-rewrite equivalents |
| `umbraco_import.json` | Node tree for Umbraco bulk import |

### Run the scraper

```bash
cd scraper
pip install -r requirements.txt
python scrape.py --max-pages 3000 --delay 0.5 --output ../output
```

Options:
- `--max-pages` — raise if the crawl seems incomplete (default 2000)
- `--delay` — be respectful to the server; 0.5 s is safe for overnight runs

### What to review after scraping

1. Open `output/content_inventory.csv` in Excel / LibreOffice.
2. Filter `doc_type = ContentPage` — these are pages the scraper couldn't classify automatically. Assign the correct doc type manually.
3. Flag rows where `redirected = True` — the old URL already redirects; trace to the canonical URL.
4. Mark pages with empty `title` — likely JS-rendered content needing Playwright (see Phase 1b below).

### Phase 1b — JS-rendered pages (optional)

If pages return empty content (React/Angular widgets), swap the requests + BS4 approach
for Playwright:

```bash
pip install playwright
playwright install chromium
# Then change SiteCrawler to use playwright.sync_api instead of requests
```

---

## Phase 2 — Umbraco Setup

### Content tree structure

```
/ (Home)
├── /city-connect
│   ├── /city-connect/apply
│   ├── /city-connect/pay
│   ├── /city-connect/register
│   ├── /city-connect/report
│   └── /city-connect/have-your-say
├── /departments
│   ├── /departments/budget-office
│   ├── /departments/city-health
│   ├── /departments/community-arts-and-culture
│   ├── /departments/customer-relations
│   ├── /departments/development-management
│   ├── /departments/disaster-risk-management
│   ├── /departments/electricity-generation-and-distribution
│   ├── /departments/enterprise-and-investment
│   ├── /departments/environmental-management
│   ├── /departments/fire-and-rescue-service
│   ├── /departments/human-resources
│   ├── /departments/law-enforcement-traffic-and-coordination
│   ├── /departments/metropolitan-police-services
│   ├── /departments/office-of-the-city-manager
│   ├── /departments/public-housing
│   ├── /departments/treasury
│   ├── /departments/urban-planning-and-design
│   └── /departments/water-and-sanitation
├── /documents-and-policies
├── /explore-and-enjoy
├── /family-and-home
│   └── /family-and-home/utilities
│       ├── /family-and-home/utilities/electricity
│       └── /family-and-home/utilities/water-and-sanitation
├── /local-and-communities
├── /media-and-news
│   ├── /media-and-news/press-releases
│   └── /media-and-news/speeches
└── /work-and-business
    └── /work-and-business/planning-portal
        └── /work-and-business/planning-portal/spatial-plans
            └── /work-and-business/planning-portal/spatial-plans/district-plans
```

### Document Types

Defined in `umbraco/document-types.json`. Create these in Umbraco backoffice first:

| Alias | Used for |
|---|---|
| `homePage` | Root node |
| `sectionLanding` | The 8 top-level sections |
| `contentPage` | General interior pages |
| `departmentPage` | Department-specific pages (30+ departments) |
| `newsArticlePage` | Press releases and news items |
| `documentPage` | Policy/bylaw documents linking to PDFs |

Every document type includes a `legacyUrl` property to store the original SharePoint URL — useful for auditing and for automated redirect testing.

### URL slug rules

`umbraco/url-slug-rules.json` defines transformations applied per section:

- `%20` and spaces → `-`
- Everything lowercased
- `.aspx` stripped
- Double hyphens collapsed

Umbraco's built-in URL provider should be configured to match: lowercase, hyphens, no trailing slash.

---

## Phase 3 — Content Migration

### Step-by-step

1. **Import the node skeleton** — run the bulk import using `output/umbraco_import.json`.
   This creates empty nodes with correct paths and doc types.
   Use uSync, Umbraco Deploy, or a custom C# controller.

2. **Migrate content per section** — work section by section (departments first, then
   media/news, then the large sections like family-and-home).

3. **Migrate documents** — copy PDFs from SharePoint document libraries to Umbraco Media.
   Update `documentPage` nodes to reference the new media items.
   The SharePoint REST API can bulk-export document libraries:
   ```
   GET https://capetown.sharepoint.com/sites/<site>/_api/web/lists/getbytitle('Documents')/items
   ```

4. **Migrate news articles** — export from SharePoint list to JSON, then import into
   `newsArticlePage` nodes under `/media-and-news`.

### Content not to migrate

- `/_layouts/15/` — system SharePoint assets, not content
- `/_vti_bin/` — SharePoint web services
- Redirect chains that already lead elsewhere (flagged by `redirected = True` in the inventory)

---

## Phase 4 — Redirects

When the new Umbraco site goes live, the old SharePoint URLs must 301 redirect to
the new Umbraco paths.

### Nginx (if fronting with nginx)

```nginx
# Generated by scraper — deploy to your nginx server block
include /etc/nginx/conf.d/capetown_redirects.conf;
```

Copy `output/redirects_nginx.conf` to that path.

### IIS (if running behind IIS / SharePoint)

Use the fragments in `output/redirects_iis_fragments.xml` inside a `<rewrite>` rule
in `web.config`.

### Umbraco built-in redirects

For any URLs missed by the scraper, enable Umbraco's **Redirect URL Management**
(built into Umbraco 8+). When an editor moves a node, Umbraco automatically creates
a 301 redirect from the old path.

### Critical redirects to verify manually

These high-traffic pages must be tested before go-live:

- `/City-Connect` → `/city-connect`
- `/Departments` → `/departments`
- `/Family%20and%20home/...` → `/family-and-home/...`
- `/Pages/Sitemap.aspx` → `/sitemap`
- `/Document-centre` → `/documents-and-policies`

---

## Phase 5 — QA & Go-live

### Pre-launch checklist

- [ ] All 301 redirects tested with `curl -I` or a redirect checker
- [ ] No broken internal links (run Screaming Frog or similar after launch)
- [ ] All PDF attachments accessible at new Umbraco Media URLs
- [ ] News articles appear with correct publish dates
- [ ] Department pages have contact details populated
- [ ] Search works (Umbraco Examine / Elasticsearch)
- [ ] Google Search Console verified and old sitemap submitted
- [ ] New XML sitemap at `/sitemap.xml` submitted to Google
- [ ] 404 page configured and monitored for first 30 days

### Monitoring after go-live

- Watch Google Search Console for crawl errors
- Monitor `output/content_inventory.csv` rows against live site for missing pages
- Check analytics for traffic drops to key sections

---

## File Structure

```
city-migration/
├── MIGRATION_PLAN.md          ← this file
├── scraper/
│   ├── scrape.py              ← site crawler
│   └── requirements.txt
├── umbraco/
│   ├── document-types.json    ← Umbraco document type definitions
│   └── url-slug-rules.json    ← SharePoint → Umbraco path mappings
└── output/                    ← generated by scrape.py (git-ignored)
    ├── content_inventory.csv
    ├── url_map.json
    ├── umbraco_import.json
    ├── redirects_nginx.conf
    └── redirects_iis_fragments.xml
```

---

## Key decisions

| Decision | Rationale |
|---|---|
| New URLs are clean lowercase slugs | SharePoint's `%20`-encoded URLs are fragile; clean slugs improve SEO and are easier to manage |
| `legacyUrl` property on every doc type | Allows automated validation: scrape Umbraco, compare against SharePoint inventory |
| News articles as a separate doc type | Enables date-based routing (`/media-and-news/2024/press-release-title`) and RSS feeds |
| Documents kept in Umbraco Media | Keeps PDFs in one place; avoids re-uploading to SharePoint |
| 301 redirects on the old server, not Umbraco | Faster response; the old SharePoint instance can serve redirects while Umbraco warms up |

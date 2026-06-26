# Umbraco Phase 2 Setup Guide

## Prerequisites

- Umbraco 10+ (.NET 6+) project created and database connected
- SQL Server or SQLite database provisioned
- Umbraco installed and admin account created via `/install`

## Files to copy into your Umbraco project

```
city-migration/umbraco/src/Migration/  →  YourProject/Migration/
city-migration/output/url_map.json     →  YourProject/migration/url_map.json
city-migration/output/umbraco_import.json → YourProject/migration/umbraco_import.json
```

## Step-by-step

### 1. Add NuGet reference

The migration classes use only Umbraco's built-in packages — no extra NuGet packages needed.

### 2. Copy the Migration folder

Copy all four `.cs` files into your Umbraco project under a `Migration/` folder:

- `DocumentTypeSeeder.cs`  — creates the 6 document types
- `ContentImporter.cs`     — imports 3,510 content nodes from JSON
- `LegacyRedirectMiddleware.cs` — 301-redirects old SharePoint URLs
- `MigrationComposer.cs`   — auto-wires everything on startup
- `UrlSegmentProvider.cs`  — ensures clean lowercase slugs

### 3. Patch Program.cs

Apply the changes in `Program.cs.patch`:
- Register `CityUrlSegmentProvider`
- Register `LegacyRedirectMiddleware` before `UseUmbraco()`

### 4. Place data files

```bash
mkdir -p YourProject/migration
cp city-migration/output/url_map.json        YourProject/migration/
cp city-migration/output/umbraco_import.json YourProject/migration/
```

### 5. First startup

On first run Umbraco will:

1. `DocumentTypeSeeder` — create 6 document types (homePage, sectionLanding, contentPage, departmentPage, newsArticlePage, documentPage)
2. `ContentImporter` — create 3,510 content nodes in the correct tree hierarchy
3. Write `App_Data/migration_complete.flag` to prevent re-running

Monitor the Umbraco log (`umbraco/Logs/UmbracoTraceLog.txt`) for:
```
=== City of Cape Town Migration: Step 1 — Document Types ===
=== City of Cape Town Migration: Step 2 — Content Import ===
=== Migration complete ===
```

### 6. Verify in backoffice

After startup, log into `/umbraco` and check:

- **Settings → Document Types** — 6 types should be present
- **Content** — tree should show the 8 section landing nodes under Home
- **Settings → URL Redirects** — legacy URLs will be handled by the middleware

## Expected content tree after import

```
Home  (homePage)
├── city-connect          (sectionLanding)  — 537 pages
├── departments           (sectionLanding)  — 24 pages
├── documents-and-policies(sectionLanding)
├── explore-and-enjoy     (sectionLanding)  — 1,418 pages
├── family-and-home       (sectionLanding)  — 1,012 pages
├── local-and-communities (sectionLanding)  — 3 pages
├── media-and-news        (sectionLanding)  — 483 news articles
└── work-and-business     (sectionLanding)  — 5 pages
```

**Total: 3,510 nodes**

## Redirect behaviour

The `LegacyRedirectMiddleware` handles these patterns automatically:

| Old SharePoint URL | New Umbraco URL |
|---|---|
| `/Family%20and%20home/...` | `/family-and-home/...` |
| `/City-Connect/Apply` | `/city-connect/apply` |
| `/Departments/City-Health` | `/departments/city-health` |
| `/Pages/Sitemap.aspx` | `/sitemap` |
| `/Document-centre` | `/documents-and-policies` |

## Phase 3 — Content population

After the skeleton is imported, editors populate content manually or via a second migration pass. Priority order:

1. **Department pages** (24) — highest traffic, most important
2. **News articles** (483) — can be bulk-imported from SharePoint list export
3. **City Connect** (537) — citizen-facing services
4. **Family and Home** (1,012) — residential services
5. **Explore and Enjoy** (1,418) — tourism/facilities

## Troubleshooting

| Problem | Fix |
|---|---|
| Doc type already exists error | Safe to ignore — seeder checks before creating |
| Parent not found for node X | Check the node's `parentPath` in `umbraco_import.json` — create parent manually first |
| Migration ran but nodes missing | Delete `App_Data/migration_complete.flag` and restart to re-run |
| Redirect not firing | Check middleware order in `Program.cs` — must be before `UseUmbraco()` |

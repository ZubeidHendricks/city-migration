using System.Text.Json;
using Umbraco.Cms.Core.Models;
using Umbraco.Cms.Core.Services;
using Microsoft.Extensions.Logging;

namespace CityOfCapeTown.Migration;

/// <summary>
/// Phase 3: reads content_extracted.jsonl and populates body content,
/// publish dates, tags, and contact details on existing Umbraco nodes.
///
/// Safe to re-run — only updates nodes whose bodyContent is still empty.
/// Invoke manually via the backoffice trigger endpoint or from a migration step.
/// </summary>
public class ContentPopulator
{
    private readonly IContentService _contentService;
    private readonly ILogger<ContentPopulator> _logger;

    public ContentPopulator(IContentService contentService, ILogger<ContentPopulator> logger)
    {
        _contentService = contentService;
        _logger         = logger;
    }

    public void Populate(string jsonlPath)
    {
        if (!File.Exists(jsonlPath))
            throw new FileNotFoundException($"Extracted content file not found: {jsonlPath}");

        // Build lookup: umbracoPath → IContent (by legacyUrl property)
        _logger.LogInformation("Building content index by legacyUrl...");
        var index = BuildIndex();
        _logger.LogInformation("Index built: {Count} nodes", index.Count);

        int updated = 0, skipped = 0, notFound = 0;

        foreach (var line in File.ReadLines(jsonlPath))
        {
            if (string.IsNullOrWhiteSpace(line)) continue;

            ExtractedPage? page;
            try { page = JsonSerializer.Deserialize<ExtractedPage>(line, JsonOpts); }
            catch { continue; }
            if (page == null) continue;

            if (!index.TryGetValue(page.SharepointUrl ?? "", out var node) &&
                !index.TryGetValue(page.UmbracoPath ?? "", out node))
            {
                notFound++;
                continue;
            }

            // Skip if already populated
            var existing = node.GetValue<string>("bodyContent");
            if (!string.IsNullOrWhiteSpace(existing))
            {
                skipped++;
                continue;
            }

            SetProperties(node, page);
            var result = _contentService.Save(node);

            if (result.Success)
                updated++;
            else
                _logger.LogWarning("Save failed for {Path}", page.UmbracoPath);

            if ((updated + skipped) % 100 == 0)
                _logger.LogInformation("Progress: {Updated} updated, {Skipped} skipped, {NotFound} not found",
                    updated, skipped, notFound);
        }

        _logger.LogInformation(
            "ContentPopulator done. Updated: {Updated}, Already populated: {Skipped}, Not found: {NotFound}",
            updated, skipped, notFound);
    }

    // -------------------------------------------------------------------------
    // Property mapping
    // -------------------------------------------------------------------------

    private static void SetProperties(IContent node, ExtractedPage page)
    {
        var docType = node.ContentType.Alias;

        // Body content — all types
        if (!string.IsNullOrWhiteSpace(page.BodyHtml))
            TrySet(node, "bodyContent", page.BodyHtml);

        // News article specific
        if (docType == "newsArticlePage")
        {
            if (!string.IsNullOrWhiteSpace(page.Headline))
                TrySet(node, "headline", page.Headline);

            if (!string.IsNullOrWhiteSpace(page.PublishDate) &&
                DateTime.TryParse(page.PublishDate, out var dt))
                TrySet(node, "publishDate", dt);

            if (page.Tags?.Any() == true)
                TrySet(node, "category", string.Join(",", page.Tags));
        }

        // Department page specific
        if (docType == "departmentPage")
        {
            TrySet(node, "overview", page.BodyHtml);
            if (!string.IsNullOrWhiteSpace(page.ContactEmail))
                TrySet(node, "contactEmail", page.ContactEmail);
            if (!string.IsNullOrWhiteSpace(page.ContactPhone))
                TrySet(node, "contactPhone", page.ContactPhone);
        }

        // Tags for any page type
        if (page.Tags?.Any() == true && docType != "newsArticlePage")
            TrySet(node, "keywords", string.Join(", ", page.Tags));
    }

    private static void TrySet(IContent node, string alias, object value)
    {
        try { node.SetValue(alias, value); }
        catch { /* property may not exist on this doc type */ }
    }

    // -------------------------------------------------------------------------
    // Index builder
    // -------------------------------------------------------------------------

    private Dictionary<string, IContent> BuildIndex()
    {
        var index   = new Dictionary<string, IContent>(StringComparer.OrdinalIgnoreCase);
        long total  = _contentService.Count();
        int pageSize = 500;

        for (long page = 0; page * pageSize < total; page++)
        {
            var items = _contentService.GetPagedDescendants(-1, page, pageSize, out _);
            foreach (var item in items)
            {
                // Index by legacyUrl (SharePoint URL)
                var legacy = item.GetValue<string>("legacyUrl");
                if (!string.IsNullOrWhiteSpace(legacy))
                    index.TryAdd(legacy, item);

                // Also index by Umbraco path
                var path = item.Path;
                if (!string.IsNullOrWhiteSpace(path))
                    index.TryAdd(path, item);
            }
        }
        return index;
    }

    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        PropertyNameCaseInsensitive = true,
    };
}

// -------------------------------------------------------------------------
// JSON model matching extract_content.py output
// -------------------------------------------------------------------------

public class ExtractedPage
{
    public string?       SharepointUrl  { get; set; }
    public string?       UmbracoPath    { get; set; }
    public string?       DocType        { get; set; }
    public string?       Title          { get; set; }
    public string?       Headline       { get; set; }
    public string?       BodyHtml       { get; set; }
    public string?       BodyText       { get; set; }
    public string?       PublishDate    { get; set; }
    public List<string>? Tags           { get; set; }
    public string?       ContactEmail   { get; set; }
    public string?       ContactPhone   { get; set; }
}

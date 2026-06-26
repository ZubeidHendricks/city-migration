using System.Text.Json;
using Umbraco.Cms.Core.Models;
using Umbraco.Cms.Core.Services;
using Umbraco.Cms.Core.Strings;
using Microsoft.Extensions.Logging;

namespace CityOfCapeTown.Migration;

/// <summary>
/// Reads umbraco_import.json and creates the full content tree in Umbraco.
/// Each node stores its legacyUrl so editors can trace back to SharePoint.
/// Safe to re-run — existing nodes (matched by legacyUrl) are skipped.
/// </summary>
public class ContentImporter
{
    private readonly IContentService _contentService;
    private readonly IContentTypeService _contentTypeService;
    private readonly IShortStringHelper _shortStringHelper;
    private readonly ILogger<ContentImporter> _logger;

    public ContentImporter(
        IContentService contentService,
        IContentTypeService contentTypeService,
        IShortStringHelper shortStringHelper,
        ILogger<ContentImporter> logger)
    {
        _contentService      = contentService;
        _contentTypeService  = contentTypeService;
        _shortStringHelper   = shortStringHelper;
        _logger              = logger;
    }

    public void Import(string jsonPath)
    {
        if (!File.Exists(jsonPath))
            throw new FileNotFoundException($"Import file not found: {jsonPath}");

        var json    = File.ReadAllText(jsonPath);
        var nodes   = JsonSerializer.Deserialize<List<ImportNode>>(json,
                          new JsonSerializerOptions { PropertyNameCaseInsensitive = true })
                      ?? throw new InvalidOperationException("Failed to deserialise import file.");

        _logger.LogInformation("Starting content import: {Count} nodes", nodes.Count);

        // Index existing nodes by legacyUrl to skip duplicates
        var existingByLegacy = BuildLegacyIndex();

        // Sort by path depth so parents are always created before children
        var sorted = nodes.OrderBy(n => n.Key.Count(c => c == '/')).ToList();

        // Track created nodes: umbracoPath → IContent (for parent lookup)
        var created = new Dictionary<string, IContent>(StringComparer.OrdinalIgnoreCase);

        // Seed the root content node as the anchor for "/" parent
        var root = _contentService.GetRootContent().FirstOrDefault();
        if (root != null)
            created["/"] = root;

        int imported = 0, skipped = 0, failed = 0;

        foreach (var node in sorted)
        {
            // Skip if already imported
            var legacyUrl = node.Properties?.GetValueOrDefault("legacyUrl") ?? "";
            if (legacyUrl != "" && existingByLegacy.ContainsKey(legacyUrl))
            {
                skipped++;
                continue;
            }

            // Resolve parent
            var parentPath  = node.ParentPath?.TrimEnd('/') ?? "/";
            var parentNode  = ResolveParent(parentPath, created);
            if (parentNode == null)
            {
                _logger.LogWarning("Parent not found for {Key}, skipping", node.Key);
                failed++;
                continue;
            }

            // Resolve doc type
            var ct = _contentTypeService.Get(node.DocType ?? "contentPage");
            if (ct == null)
            {
                _logger.LogWarning("Doc type '{DocType}' not found for {Key}", node.DocType, node.Key);
                failed++;
                continue;
            }

            var name    = (node.Name ?? PathToName(node.Key)).Trim();
            if (string.IsNullOrWhiteSpace(name)) name = "Untitled";

            var content = _contentService.Create(name, parentNode.Id, ct.Alias);

            // Set properties
            if (node.Properties != null)
            {
                foreach (var (propAlias, value) in node.Properties)
                {
                    try { content.SetValue(propAlias, value); }
                    catch (Exception ex)
                    {
                        _logger.LogDebug("Could not set {Alias} on {Key}: {Ex}", propAlias, node.Key, ex.Message);
                    }
                }
            }

            // Override the URL segment to match the planned Umbraco path
            var slug = node.Key.Split('/').Last();
            content.SetUrlSegment(_shortStringHelper, slug);

            var result = _contentService.Save(content);
            if (result.Success)
            {
                created[node.Key.TrimEnd('/')] = content;
                imported++;

                if (imported % 100 == 0)
                    _logger.LogInformation("Imported {Count}/{Total} nodes", imported, sorted.Count);
            }
            else
            {
                _logger.LogWarning("Save failed for {Key}: {Events}",
                    node.Key, string.Join(", ", result.EventMessages.GetAll().Select(e => e.Message)));
                failed++;
            }
        }

        _logger.LogInformation(
            "Import complete. Imported: {Imported}, Skipped (duplicate): {Skipped}, Failed: {Failed}",
            imported, skipped, failed);
    }

    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------

    private Dictionary<string, IContent> BuildLegacyIndex()
    {
        var index   = new Dictionary<string, IContent>(StringComparer.OrdinalIgnoreCase);
        long total  = _contentService.Count();
        int pageSize = 500;

        for (long page = 0; page * pageSize < total; page++)
        {
            var items = _contentService.GetPagedDescendants(-1, page, pageSize, out _);
            foreach (var item in items)
            {
                var legacy = item.GetValue<string>("legacyUrl");
                if (!string.IsNullOrWhiteSpace(legacy))
                    index.TryAdd(legacy, item);
            }
        }
        return index;
    }

    private IContent? ResolveParent(string parentPath, Dictionary<string, IContent> created)
    {
        if (string.IsNullOrEmpty(parentPath) || parentPath == "/")
            return created.GetValueOrDefault("/");

        if (created.TryGetValue(parentPath, out var node))
            return node;

        // Try without trailing slash variations
        var normalised = parentPath.TrimEnd('/');
        if (created.TryGetValue(normalised, out node))
            return node;

        return null;
    }

    private static string PathToName(string key) =>
        (key.Split('/').LastOrDefault() ?? key)
            .Replace("-", " ")
            .Replace("_", " ")
            .Trim();
}

// -------------------------------------------------------------------------
// JSON model
// -------------------------------------------------------------------------

public class ImportNode
{
    public string? Key        { get; set; }
    public string? ParentPath { get; set; }
    public string? Name       { get; set; }
    public string? DocType    { get; set; }
    public Dictionary<string, string>? Properties { get; set; }
}

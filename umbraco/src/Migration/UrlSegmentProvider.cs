using Umbraco.Cms.Core.Routing;
using Umbraco.Cms.Core.Models.PublishedContent;
using Umbraco.Cms.Core.Strings;

namespace CityOfCapeTown.Migration;

/// <summary>
/// Ensures Umbraco URL segments are lowercase, hyphenated, and match the
/// planned Umbraco paths exactly (no %20 encoding).
/// Register in MigrationComposer or Program.cs:
///   builder.SetDefaultUrlSegmentProvider&lt;CityUrlSegmentProvider&gt;();
/// </summary>
public class CityUrlSegmentProvider : DefaultUrlSegmentProvider
{
    public CityUrlSegmentProvider(IShortStringHelper shortStringHelper)
        : base(shortStringHelper) { }

    public override string? GetUrlSegment(IPublishedContent content, string? culture = null)
    {
        // Use the stored URL segment if available (set during import)
        var stored = content.UrlSegment;
        if (!string.IsNullOrWhiteSpace(stored))
            return Sanitise(stored);

        // Fallback: convert content name to slug
        return Sanitise(base.GetUrlSegment(content, culture) ?? content.Name);
    }

    private static string Sanitise(string input)
    {
        var slug = input.ToLowerInvariant()
                        .Replace(" ", "-")
                        .Replace("_", "-");

        // Collapse multiple hyphens
        while (slug.Contains("--"))
            slug = slug.Replace("--", "-");

        return slug.Trim('-');
    }
}

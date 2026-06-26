using Umbraco.Cms.Core.Models;
using Umbraco.Cms.Core.Services;
using Umbraco.Cms.Core.Strings;

namespace CityOfCapeTown.Migration;

/// <summary>
/// Creates all document types required for the SharePoint migration.
/// Run once on first startup via MigrationComposer.
/// </summary>
public class DocumentTypeSeeder
{
    private readonly IContentTypeService _contentTypeService;
    private readonly IDataTypeService _dataTypeService;
    private readonly IShortStringHelper _shortStringHelper;

    private int _tinyMce;
    private int _textBox;
    private int _textArea;
    private int _dateTime;
    private int _mediaPicker;
    private int _multiUrlPicker;
    private int _tags;
    private int _contentPicker;

    public DocumentTypeSeeder(
        IContentTypeService contentTypeService,
        IDataTypeService dataTypeService,
        IShortStringHelper shortStringHelper)
    {
        _contentTypeService = contentTypeService;
        _dataTypeService = dataTypeService;
        _shortStringHelper = shortStringHelper;
    }

    public void Seed()
    {
        ResolveDataTypes();

        EnsureDocType("homePage",              "Home Page",               "icon-home",        allowedAtRoot: true,  CreateHomePageProps());
        EnsureDocType("sectionLanding",        "Section Landing Page",    "icon-section",     allowedAtRoot: false, CreateSectionLandingProps());
        EnsureDocType("contentPage",           "Content Page",            "icon-document",    allowedAtRoot: false, CreateContentPageProps());
        EnsureDocType("departmentPage",        "Department Page",         "icon-building",    allowedAtRoot: false, CreateDepartmentPageProps());
        EnsureDocType("newsArticlePage",       "News Article Page",       "icon-newspaper",   allowedAtRoot: false, CreateNewsArticleProps());
        EnsureDocType("documentPage",          "Document / Policy Page",  "icon-pdf",         allowedAtRoot: false, CreateDocumentPageProps());

        SetAllowedChildren();
    }

    // -------------------------------------------------------------------------
    // Property group definitions per doc type
    // -------------------------------------------------------------------------

    private List<PropertyDef> CreateHomePageProps() => new()
    {
        new("heroHeading",      "Hero Heading",       _textBox,       "Content"),
        new("heroSubtitle",     "Hero Subtitle",      _textBox,       "Content"),
        new("quickLinks",       "Quick Links",        _multiUrlPicker,"Content"),
        new("seoTitle",         "SEO Title",          _textBox,       "SEO"),
        new("seoDescription",   "SEO Description",    _textArea,      "SEO"),
    };

    private List<PropertyDef> CreateSectionLandingProps() => new()
    {
        new("pageTitle",        "Page Title",         _textBox,       "Content"),
        new("introText",        "Intro Text",         _tinyMce,       "Content"),
        new("sectionIcon",      "Section Icon",       _mediaPicker,   "Content"),
        new("subSections",      "Sub-sections",       _multiUrlPicker,"Content"),
        new("seoTitle",         "SEO Title",          _textBox,       "SEO"),
        new("seoDescription",   "SEO Description",    _textArea,      "SEO"),
        new("legacyUrl",        "Legacy SharePoint URL", _textBox,    "Migration"),
    };

    private List<PropertyDef> CreateContentPageProps() => new()
    {
        new("pageTitle",        "Page Title",         _textBox,       "Content"),
        new("bodyContent",      "Body Content",       _tinyMce,       "Content"),
        new("relatedLinks",     "Related Links",      _multiUrlPicker,"Content"),
        new("attachments",      "Attachments",        _mediaPicker,   "Content"),
        new("lastUpdated",      "Last Updated",       _dateTime,      "Content"),
        new("seoTitle",         "SEO Title",          _textBox,       "SEO"),
        new("seoDescription",   "SEO Description",    _textArea,      "SEO"),
        new("legacyUrl",        "Legacy SharePoint URL", _textBox,    "Migration"),
    };

    private List<PropertyDef> CreateDepartmentPageProps() => new()
    {
        new("departmentName",   "Department Name",    _textBox,       "Content"),
        new("overview",         "Overview",           _tinyMce,       "Content"),
        new("headOfDept",       "Head of Department", _textBox,       "Content"),
        new("services",         "Services Offered",   _multiUrlPicker,"Content"),
        new("documents",        "Department Documents",_mediaPicker,  "Content"),
        new("seoTitle",         "SEO Title",          _textBox,       "SEO"),
        new("seoDescription",   "SEO Description",    _textArea,      "SEO"),
        new("legacyUrl",        "Legacy SharePoint URL", _textBox,    "Migration"),
    };

    private List<PropertyDef> CreateNewsArticleProps() => new()
    {
        new("headline",         "Headline",           _textBox,       "Content"),
        new("summary",          "Summary",            _textArea,      "Content"),
        new("bodyContent",      "Body Content",       _tinyMce,       "Content"),
        new("publishDate",      "Publish Date",       _dateTime,      "Content"),
        new("category",         "Category",           _tags,          "Content"),
        new("heroImage",        "Hero Image",         _mediaPicker,   "Content"),
        new("author",           "Author",             _textBox,       "Content"),
        new("seoTitle",         "SEO Title",          _textBox,       "SEO"),
        new("seoDescription",   "SEO Description",    _textArea,      "SEO"),
        new("legacyUrl",        "Legacy SharePoint URL", _textBox,    "Migration"),
    };

    private List<PropertyDef> CreateDocumentPageProps() => new()
    {
        new("documentTitle",    "Document Title",     _textBox,       "Content"),
        new("description",      "Description",        _textArea,      "Content"),
        new("documentFile",     "Document File",      _mediaPicker,   "Content"),
        new("documentCategory", "Category",           _tags,          "Content"),
        new("effectiveDate",    "Effective Date",     _dateTime,      "Content"),
        new("department",       "Owning Department",  _contentPicker, "Content"),
        new("legacyUrl",        "Legacy SharePoint URL", _textBox,    "Migration"),
    };

    // -------------------------------------------------------------------------
    // Allowed children
    // -------------------------------------------------------------------------

    private void SetAllowedChildren()
    {
        var home        = _contentTypeService.Get("homePage");
        var section     = _contentTypeService.Get("sectionLanding");
        var content     = _contentTypeService.Get("contentPage");
        var department  = _contentTypeService.Get("departmentPage");
        var news        = _contentTypeService.Get("newsArticlePage");
        var document    = _contentTypeService.Get("documentPage");

        if (home != null)
        {
            home.AllowedContentTypes = new[] { new ContentTypeSort(section!.Key, 0, section.Alias) };
            _contentTypeService.Save(home);
        }

        if (section != null)
        {
            section.AllowedContentTypes = new[]
            {
                new ContentTypeSort(content!.Key,    0, content.Alias),
                new ContentTypeSort(department!.Key, 1, department.Alias),
                new ContentTypeSort(news!.Key,       2, news.Alias),
                new ContentTypeSort(document!.Key,   3, document.Alias),
            };
            _contentTypeService.Save(section);
        }

        if (content != null)
        {
            content.AllowedContentTypes = new[] { new ContentTypeSort(content.Key, 0, content.Alias) };
            _contentTypeService.Save(content);
        }
    }

    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------

    private void ResolveDataTypes()
    {
        _tinyMce       = GetDataTypeId("Richtext editor");
        _textBox       = GetDataTypeId("Textstring");
        _textArea      = GetDataTypeId("Textarea");
        _dateTime      = GetDataTypeId("Date Picker");
        _mediaPicker   = GetDataTypeId("Media Picker");
        _multiUrlPicker = GetDataTypeId("Multi URL Picker");
        _tags          = GetDataTypeId("Tags");
        _contentPicker = GetDataTypeId("Content Picker");
    }

    private int GetDataTypeId(string name)
    {
        var dt = _dataTypeService.GetDataType(name);
        if (dt == null)
            throw new InvalidOperationException($"Data type '{name}' not found. Ensure Umbraco is fully installed.");
        return dt.Id;
    }

    private void EnsureDocType(string alias, string name, string icon, bool allowedAtRoot, List<PropertyDef> props)
    {
        if (_contentTypeService.Get(alias) != null)
            return; // already exists

        var ct = new ContentType(_shortStringHelper, -1)
        {
            Alias          = alias,
            Name           = name,
            Icon           = icon,
            AllowedAsRoot  = allowedAtRoot,
            IsContainer    = false,
        };

        // Group properties
        var groups = props.GroupBy(p => p.Group);
        int sortOrder = 0;
        foreach (var group in groups)
        {
            var pg = new PropertyGroup(new PropertyTypeCollection(true))
            {
                Name      = group.Key,
                SortOrder = sortOrder++,
            };
            foreach (var def in group)
            {
                pg.PropertyTypes!.Add(new PropertyType(_shortStringHelper, _dataTypeService.GetDataType(def.DataTypeId)!)
                {
                    Alias       = def.Alias,
                    Name        = def.Name,
                    Mandatory   = false,
                });
            }
            ct.PropertyGroups.Add(pg);
        }

        _contentTypeService.Save(ct);
    }

    private record PropertyDef(string Alias, string Name, int DataTypeId, string Group);
}

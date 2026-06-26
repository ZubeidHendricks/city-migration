using Microsoft.Extensions.DependencyInjection;
using Umbraco.Cms.Core.Composing;
using Umbraco.Cms.Core.DependencyInjection;
using Umbraco.Cms.Core.Notifications;
using Umbraco.Cms.Core.Events;
using Microsoft.Extensions.Logging;

namespace CityOfCapeTown.Migration;

/// <summary>
/// Wires the migration services into Umbraco's IoC container and
/// triggers DocumentTypeSeeder + ContentImporter on first run.
///
/// Umbraco discovers this automatically via IComposer scan.
/// </summary>
public class MigrationComposer : IComposer
{
    public void Compose(IUmbracoBuilder builder)
    {
        builder.Services.AddSingleton<DocumentTypeSeeder>();
        builder.Services.AddSingleton<ContentImporter>();

        builder.AddNotificationHandler<UmbracoApplicationStartingNotification, MigrationStartupHandler>();
    }
}

public class MigrationStartupHandler : INotificationHandler<UmbracoApplicationStartingNotification>
{
    private readonly DocumentTypeSeeder _docTypeSeeder;
    private readonly ContentImporter    _contentImporter;
    private readonly IWebHostEnvironment _env;
    private readonly ILogger<MigrationStartupHandler> _logger;

    public MigrationStartupHandler(
        DocumentTypeSeeder docTypeSeeder,
        ContentImporter contentImporter,
        IWebHostEnvironment env,
        ILogger<MigrationStartupHandler> logger)
    {
        _docTypeSeeder   = docTypeSeeder;
        _contentImporter = contentImporter;
        _env             = env;
        _logger          = logger;
    }

    public void Handle(UmbracoApplicationStartingNotification notification)
    {
        // Guard flag — only run once
        var flagPath = Path.Combine(_env.ContentRootPath, "App_Data", "migration_complete.flag");
        if (File.Exists(flagPath))
        {
            _logger.LogInformation("Migration already run (flag file present). Skipping.");
            return;
        }

        try
        {
            _logger.LogInformation("=== City of Cape Town Migration: Step 1 — Document Types ===");
            _docTypeSeeder.Seed();

            _logger.LogInformation("=== City of Cape Town Migration: Step 2 — Content Import ===");
            var importFile = Path.Combine(_env.ContentRootPath, "migration", "umbraco_import.json");
            _contentImporter.Import(importFile);

            // Write flag so we don't re-run
            Directory.CreateDirectory(Path.GetDirectoryName(flagPath)!);
            File.WriteAllText(flagPath, DateTime.UtcNow.ToString("O"));
            _logger.LogInformation("=== Migration complete ===");
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Migration failed — check logs and re-run after fixing the issue");
            // Do NOT write the flag on failure so a restart retries
        }
    }
}

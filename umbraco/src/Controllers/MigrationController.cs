using CityOfCapeTown.Migration;
using Microsoft.AspNetCore.Mvc;
using Umbraco.Cms.Web.BackOffice.Controllers;
using Umbraco.Cms.Web.Common.Attributes;

namespace CityOfCapeTown.Controllers;

/// <summary>
/// Backoffice API controller — lets editors trigger Phase 3 content population
/// without a redeployment.
///
/// Endpoints (requires backoffice login):
///   POST /umbraco/backoffice/migration/populate
///   GET  /umbraco/backoffice/migration/status
/// </summary>
[IsBackOffice]
[ApiController]
[Route("umbraco/backoffice/migration")]
public class MigrationController : UmbracoAuthorizedApiController
{
    private readonly ContentPopulator _populator;
    private readonly IWebHostEnvironment _env;
    private readonly ILogger<MigrationController> _logger;

    // Shared state so /status can report progress
    private static volatile string _status = "idle";
    private static volatile int _lastUpdated = 0;

    public MigrationController(
        ContentPopulator populator,
        IWebHostEnvironment env,
        ILogger<MigrationController> logger)
    {
        _populator = populator;
        _env       = env;
        _logger    = logger;
    }

    /// <summary>Trigger Phase 3 content population (runs in background thread).</summary>
    [HttpPost("populate")]
    public IActionResult Populate()
    {
        if (_status == "running")
            return Conflict(new { message = "Population already running.", status = _status });

        var jsonlPath = Path.Combine(_env.ContentRootPath, "migration", "content_extracted.jsonl");
        if (!System.IO.File.Exists(jsonlPath))
            return BadRequest(new
            {
                message = "content_extracted.jsonl not found. Run extract_content.py first.",
                expectedPath = jsonlPath,
            });

        _status = "running";
        _lastUpdated = 0;

        // Run on background thread so the HTTP response returns immediately
        _ = Task.Run(() =>
        {
            try
            {
                _populator.Populate(jsonlPath);
                _status = "complete";
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "ContentPopulator failed");
                _status = $"failed: {ex.Message}";
            }
        });

        return Accepted(new { message = "Content population started.", statusEndpoint = "/umbraco/backoffice/migration/status" });
    }

    /// <summary>Check current population status.</summary>
    [HttpGet("status")]
    public IActionResult Status()
    {
        var jsonlPath = Path.Combine(_env.ContentRootPath, "migration", "content_extracted.jsonl");
        long lineCount = 0;
        if (System.IO.File.Exists(jsonlPath))
            lineCount = System.IO.File.ReadLines(jsonlPath).LongCount();

        return Ok(new
        {
            status          = _status,
            extractedPages  = lineCount,
            jsonlPath       = jsonlPath,
            jsonlExists     = System.IO.File.Exists(jsonlPath),
        });
    }
}

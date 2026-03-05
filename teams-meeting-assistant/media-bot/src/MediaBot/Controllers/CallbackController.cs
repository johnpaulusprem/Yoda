using Microsoft.AspNetCore.Mvc;
using MediaBot.Services;

namespace MediaBot.Controllers;

/// <summary>
/// Receives Graph Communications SDK callback notifications and routes them
/// to the ICommunicationsClient for processing. This is how Graph notifies
/// the bot about call state changes, participant updates, etc.
/// </summary>
[ApiController]
[Route("api/callbacks")]
public class CallbackController : ControllerBase
{
    private readonly BotService _botService;
    private readonly ILogger<CallbackController> _logger;

    public CallbackController(BotService botService, ILogger<CallbackController> logger)
    {
        _botService = botService;
        _logger = logger;
    }

    [HttpPost]
    public async Task<IActionResult> HandleCallback()
    {
        using var reader = new StreamReader(Request.Body, leaveOpen: true);
        var body = await reader.ReadToEndAsync();
        _logger.LogDebug(
            "Graph callback received ({Length} bytes)", body.Length);

        // Route notification to Graph Communications SDK for processing.
        // The SDK will fire appropriate events on ICall (OnUpdated, etc.)
        // which BotService has subscribed to.
        if (_botService.CommsClient != null)
        {
            try
            {
                await _botService.CommsClient.ProcessNotificationAsync(
                    Request.Headers.ToDictionary(
                        h => h.Key,
                        h => (IEnumerable<string>)h.Value!),
                    body);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error processing Graph notification");
                // Return 200 anyway — Graph will retry on non-2xx, which can cause
                // duplicate processing. Better to log and investigate.
            }
        }
        else
        {
            _logger.LogDebug("Graph callback received but CommsClient not initialized (stub mode)");
        }

        return Ok();
    }
}

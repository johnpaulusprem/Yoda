using Microsoft.AspNetCore.Mvc;

namespace MediaBot.Controllers;

/// <summary>
/// Receives Graph Communications SDK callback notifications.
/// In the full implementation, these are processed by the Graph Communications client
/// to trigger call state changes.
/// </summary>
[ApiController]
[Route("api/callbacks")]
public class CallbackController : ControllerBase
{
    private readonly ILogger<CallbackController> _logger;

    public CallbackController(ILogger<CallbackController> logger)
    {
        _logger = logger;
    }

    [HttpPost]
    public async Task<IActionResult> HandleCallback()
    {
        using var reader = new StreamReader(Request.Body, leaveOpen: true);
        var body = await reader.ReadToEndAsync();
        _logger.LogDebug(
            "Graph callback received ({Length} bytes)", body.Length);

        // In production with Graph Communications SDK:
        // 1. Validate JWT token from Authorization header
        // 2. Process notification: await _botService.Client.ProcessNotificationAsync(Request.Headers, body);

        return Ok();
    }
}

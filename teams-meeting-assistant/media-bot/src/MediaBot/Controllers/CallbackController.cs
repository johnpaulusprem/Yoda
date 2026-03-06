using Microsoft.AspNetCore.Http.Extensions;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Graph.Communications.Client;
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
                // Build an HttpRequestMessage from the incoming ASP.NET Core request
                // so the Graph Communications SDK extension method can process it.
                var httpRequestMessage = new HttpRequestMessage(HttpMethod.Post, Request.GetEncodedUrl());
                foreach (var header in Request.Headers)
                {
                    httpRequestMessage.Headers.TryAddWithoutValidation(header.Key, header.Value.ToArray());
                }
                httpRequestMessage.Content = new StringContent(body, System.Text.Encoding.UTF8, "application/json");

                await _botService.CommsClient.ProcessNotificationAsync(httpRequestMessage);
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

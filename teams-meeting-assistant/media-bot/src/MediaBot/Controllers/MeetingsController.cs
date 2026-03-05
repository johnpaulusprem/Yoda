using Microsoft.AspNetCore.Mvc;
using MediaBot.Models;
using MediaBot.Services;

namespace MediaBot.Controllers;

[ServiceFilter(typeof(HmacValidationFilter))]
[ApiController]
[Route("api/meetings")]
public class MeetingsController : ControllerBase
{
    private readonly BotService _botService;
    private readonly ILogger<MeetingsController> _logger;

    public MeetingsController(BotService botService, ILogger<MeetingsController> logger)
    {
        _botService = botService;
        _logger = logger;
    }

    [HttpPost("join")]
    public async Task<ActionResult<JoinMeetingResponse>> JoinMeeting(
        [FromBody] JoinMeetingRequest request)
    {
        if (!_botService.CanAccept)
        {
            _logger.LogWarning(
                "Rejected join for {MeetingId}: at capacity ({ActiveCount}/{MaxCapacity})",
                request.MeetingId, _botService.ActiveMeetingCount, BotService.MaxCapacity);
            return StatusCode(503, new { error = "Bot at capacity" });
        }

        try
        {
            var callId = await _botService.JoinMeetingAsync(request);
            return Accepted(new JoinMeetingResponse(callId, "joining"));
        }
        catch (InvalidOperationException ex)
        {
            _logger.LogWarning(ex, "Cannot join meeting {MeetingId}", request.MeetingId);
            return Conflict(new { error = ex.Message });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to join meeting {MeetingId}", request.MeetingId);
            return StatusCode(500, new { error = "Internal server error" });
        }
    }

    [HttpPost("{callId}/leave")]
    public async Task<IActionResult> LeaveMeeting(string callId)
    {
        try
        {
            await _botService.LeaveMeetingAsync(callId);
            return Ok(new { status = "leaving" });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error leaving meeting with callId {CallId}", callId);
            return StatusCode(500, new { error = "Internal server error" });
        }
    }

    [HttpGet("capacity")]
    public ActionResult<CapacityResponse> GetCapacity()
    {
        return Ok(new CapacityResponse(
            _botService.ActiveMeetingCount,
            BotService.MaxCapacity,
            _botService.CanAccept));
    }
}

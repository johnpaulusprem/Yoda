using System.Text;
using System.Text.Json;
using MediaBot.Models;

namespace MediaBot.Services;

/// <summary>
/// HTTP client for sending transcript chunks and lifecycle events to the Python FastAPI backend.
/// Uses HmacAuthHandler for request signing.
/// </summary>
public class PythonBackendClient
{
    private readonly HttpClient _http;
    private readonly ILogger<PythonBackendClient> _logger;

    public PythonBackendClient(HttpClient http, ILogger<PythonBackendClient> logger)
    {
        _http = http;
        _logger = logger;
    }

    public async Task SendTranscriptAsync(TranscriptChunk chunk, CancellationToken ct = default)
    {
        try
        {
            var json = JsonSerializer.Serialize(chunk);
            var content = new StringContent(json, Encoding.UTF8, "application/json");
            var response = await _http.PostAsync("/api/bot-events/transcript", content, ct);
            if (!response.IsSuccessStatusCode)
            {
                var body = await response.Content.ReadAsStringAsync(ct);
                _logger.LogError(
                    "Failed to send transcript for {MeetingId}: {Status} {Body}",
                    chunk.MeetingId, response.StatusCode, body);
            }
            else
            {
                _logger.LogDebug(
                    "Sent {Count} transcript segments for {MeetingId}",
                    chunk.Segments.Count, chunk.MeetingId);
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error sending transcript for {MeetingId}", chunk.MeetingId);
            throw;
        }
    }

    public async Task SendLifecycleEventAsync(BotLifecycleEvent evt, CancellationToken ct = default)
    {
        try
        {
            var json = JsonSerializer.Serialize(evt);
            var content = new StringContent(json, Encoding.UTF8, "application/json");
            var response = await _http.PostAsync("/api/bot-events/lifecycle", content, ct);
            if (!response.IsSuccessStatusCode)
            {
                var body = await response.Content.ReadAsStringAsync(ct);
                _logger.LogError(
                    "Failed to send lifecycle event {EventType} for {MeetingId}: {Status} {Body}",
                    evt.EventType, evt.MeetingId, response.StatusCode, body);
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex,
                "Error sending lifecycle event {EventType} for {MeetingId}",
                evt.EventType, evt.MeetingId);
            throw;
        }
    }
}

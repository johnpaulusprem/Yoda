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
        var json = JsonSerializer.Serialize(chunk);
        var content = new StringContent(json, Encoding.UTF8, "application/json");
        var response = await _http.PostAsync("/api/bot-events/transcript", content, ct);
        if (!response.IsSuccessStatusCode)
        {
            var body = await response.Content.ReadAsStringAsync(ct);
            _logger.LogError(
                "Failed to send transcript for {MeetingId}: {Status} {Body}",
                chunk.MeetingId, response.StatusCode, body);
            // Throw so SpeechTranscriber re-buffers the segments for retry
            response.EnsureSuccessStatusCode();
        }

        _logger.LogDebug(
            "Sent {Count} transcript segments for {MeetingId}",
            chunk.Segments.Count, chunk.MeetingId);
    }

    /// <summary>
    /// Send a lifecycle event with retry. Critical events (bot_joined, meeting_ended)
    /// must reach the Python backend or the meeting state machine gets stuck.
    /// </summary>
    public async Task SendLifecycleEventAsync(BotLifecycleEvent evt, CancellationToken ct = default)
    {
        const int maxRetries = 3;
        for (var attempt = 0; attempt <= maxRetries; attempt++)
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
                    response.EnsureSuccessStatusCode();
                }

                _logger.LogDebug(
                    "Sent lifecycle event {EventType} for {MeetingId}",
                    evt.EventType, evt.MeetingId);
                return;
            }
            catch (Exception ex) when (attempt < maxRetries)
            {
                _logger.LogWarning(ex,
                    "Lifecycle event {EventType} for {MeetingId} failed (attempt {Attempt}/{MaxRetries}), retrying...",
                    evt.EventType, evt.MeetingId, attempt + 1, maxRetries);
                await Task.Delay(TimeSpan.FromSeconds(2 * (attempt + 1)), ct);
            }
        }
    }
}

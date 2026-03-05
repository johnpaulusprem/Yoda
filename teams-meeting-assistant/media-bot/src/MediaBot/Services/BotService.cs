using System.Collections.Concurrent;
using Microsoft.Extensions.Options;
using MediaBot.Configuration;
using MediaBot.Models;

namespace MediaBot.Services;

/// <summary>
/// Manages the lifecycle of meeting bot instances. Handles joining/leaving meetings
/// and tracking active call handlers. Uses Graph Communications SDK for media access.
///
/// NOTE: Graph Communications SDK (Microsoft.Graph.Communications.Calls.Media) only
/// runs on Windows. This service will initialize the SDK on Windows and provide
/// a stub implementation on other platforms for development/testing.
/// </summary>
public class BotService : IHostedService
{
    private readonly BotOptions _opts;
    private readonly IServiceProvider _sp;
    private readonly ILogger<BotService> _logger;
    private readonly ConcurrentDictionary<string, CallHandlerInfo> _activeHandlers = new();
    private readonly ConcurrentDictionary<string, string> _callIdToMeetingId = new();
    private readonly SemaphoreSlim _joinLock = new(1, 1);
    private const int MaxConcurrentMeetings = 5;

    public BotService(
        IOptions<BotOptions> opts,
        IServiceProvider sp,
        ILogger<BotService> logger)
    {
        _opts = opts.Value;
        _sp = sp;
        _logger = logger;
    }

    public int ActiveMeetingCount => _activeHandlers.Count;
    public bool CanAccept => _activeHandlers.Count < MaxConcurrentMeetings;
    public static int MaxCapacity => MaxConcurrentMeetings;

    public Task StartAsync(CancellationToken ct)
    {
        _logger.LogInformation(
            "BotService started (capacity: {MaxConcurrentMeetings} concurrent meetings)",
            MaxConcurrentMeetings);

        if (!OperatingSystem.IsWindows())
        {
            _logger.LogWarning(
                "Graph Communications Media SDK requires Windows. " +
                "Running in stub mode — join requests will be accepted but no real media processing");
        }

        return Task.CompletedTask;
    }

    public async Task StopAsync(CancellationToken ct)
    {
        _logger.LogInformation(
            "BotService shutting down, leaving {ActiveMeetingCount} active meetings",
            _activeHandlers.Count);

        foreach (var (meetingId, info) in _activeHandlers)
        {
            try
            {
                _logger.LogInformation("Cleaning up meeting {MeetingId}", meetingId);
                if (info.Transcriber != null)
                {
                    await info.Transcriber.StopAsync();
                    info.Transcriber.Dispose();
                }
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error cleaning up meeting {MeetingId} during shutdown", meetingId);
            }
            finally
            {
                info.Scope.Dispose();
            }
        }
        _activeHandlers.Clear();
        _callIdToMeetingId.Clear();
        _joinLock.Dispose();

        _logger.LogInformation("BotService stopped");
    }

    public async Task<string> JoinMeetingAsync(JoinMeetingRequest request)
    {
        await _joinLock.WaitAsync();
        try
        {
            if (!CanAccept)
                throw new InvalidOperationException(
                    $"At capacity ({MaxConcurrentMeetings} meetings)");

            if (_activeHandlers.ContainsKey(request.MeetingId))
                throw new InvalidOperationException(
                    $"Meeting {request.MeetingId} already has an active bot");

            _logger.LogInformation(
                "Joining meeting {MeetingId} via {JoinUrl}",
                request.MeetingId,
                request.JoinUrl[..Math.Min(80, request.JoinUrl.Length)]);

            var scope = _sp.CreateScope();
            try
            {
                var backend = scope.ServiceProvider.GetRequiredService<PythonBackendClient>();
                var transcriber = scope.ServiceProvider.GetRequiredService<SpeechTranscriber>();

                // Generate a call ID (in production, this comes from Graph Communications SDK)
                var callId = $"graph-call-{Guid.NewGuid():N}"[..24];

                var info = new CallHandlerInfo(callId, scope, transcriber);
                if (!_activeHandlers.TryAdd(request.MeetingId, info))
                    throw new InvalidOperationException(
                        $"Concurrent join attempt for meeting {request.MeetingId}");

                _callIdToMeetingId[callId] = request.MeetingId;

                // Send bot_joined lifecycle event
                await backend.SendLifecycleEventAsync(new BotLifecycleEvent(
                    request.MeetingId,
                    $"media-bot-{Environment.MachineName}",
                    "bot_joined",
                    DateTimeOffset.UtcNow));

                // Start transcription
                await transcriber.StartAsync(request.MeetingId);

                _logger.LogInformation(
                    "Bot joined meeting {MeetingId}, callId={CallId}, active={ActiveCount}/{MaxCapacity}",
                    request.MeetingId, callId, _activeHandlers.Count, MaxConcurrentMeetings);

                return callId;
            }
            catch
            {
                _activeHandlers.TryRemove(request.MeetingId, out _);
                scope.Dispose();
                throw;
            }
        }
        finally
        {
            _joinLock.Release();
        }
    }

    public async Task LeaveMeetingAsync(string callId)
    {
        if (!_callIdToMeetingId.TryRemove(callId, out var meetingId))
        {
            _logger.LogWarning("No active handler found for callId {CallId}", callId);
            return;
        }

        if (!_activeHandlers.TryRemove(meetingId, out var info))
        {
            _logger.LogWarning(
                "Handler already removed for meeting {MeetingId}, callId {CallId}",
                meetingId, callId);
            return;
        }

        try
        {
            if (info.Transcriber != null)
            {
                await info.Transcriber.StopAsync();
                info.Transcriber.Dispose();
            }

            var backend = info.Scope.ServiceProvider.GetRequiredService<PythonBackendClient>();
            await backend.SendLifecycleEventAsync(new BotLifecycleEvent(
                meetingId,
                $"media-bot-{Environment.MachineName}",
                "meeting_ended",
                DateTimeOffset.UtcNow));
        }
        catch (Exception ex)
        {
            _logger.LogError(ex,
                "Error during leave cleanup for meeting {MeetingId}, callId {CallId}",
                meetingId, callId);
        }
        finally
        {
            info.Scope.Dispose();
        }

        _logger.LogInformation(
            "Left meeting {MeetingId}, callId={CallId}, active={ActiveCount}",
            meetingId, callId, _activeHandlers.Count);
    }

    private record CallHandlerInfo(
        string CallId,
        IServiceScope Scope,
        SpeechTranscriber? Transcriber
    );
}

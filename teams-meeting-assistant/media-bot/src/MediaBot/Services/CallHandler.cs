using System.Collections.Concurrent;
using System.Runtime.InteropServices;
using MediaBot.Models;

namespace MediaBot.Services;

/// <summary>
/// Manages a single active call/meeting. Receives audio frames from the
/// Graph Communications Media Platform via IAudioSocket, extracts active
/// speaker info, and feeds PCM audio to the SpeechTranscriber.
///
/// On Windows with the Graph Communications SDK, this class subscribes to:
/// - AudioSocket.AudioMediaReceived — raw PCM audio at 50fps (20ms frames)
/// - Call state changes — established, terminated
/// - Participant updates — joins, leaves, speaker changes
///
/// On non-Windows (dev/test), operates in stub mode.
/// </summary>
public class CallHandler : IDisposable
{
    private readonly SpeechTranscriber _transcriber;
    private readonly PythonBackendClient _backend;
    private readonly string _meetingId;
    private readonly string _botInstanceId;
    private readonly ILogger<CallHandler> _logger;
    private bool _disposed;
    private int _audioErrorCount;

    // Participant tracking — maps media stream ID (MSI) to participant identity.
    // The Graph Communications SDK provides MSI in audio frames; we map that to
    // the participant's Graph User ID and display name.
    private readonly ConcurrentDictionary<uint, ParticipantInfo> _msiToParticipant = new();

    public CallHandler(
        SpeechTranscriber transcriber,
        PythonBackendClient backend,
        string meetingId,
        ILogger<CallHandler> logger)
    {
        _transcriber = transcriber;
        _backend = backend;
        _meetingId = meetingId;
        _botInstanceId = $"media-bot-{Environment.MachineName}";
        _logger = logger;
    }

    /// <summary>
    /// Called when the Graph Communications SDK receives an audio frame.
    /// This is the hot path — called 50 times/second per meeting.
    ///
    /// The AudioMediaReceivedEventArgs contains:
    /// - Buffer.Data: IntPtr to raw PCM audio (16kHz, 16-bit, mono)
    /// - Buffer.Length: byte count (typically 640 bytes = 20ms of audio)
    /// - Buffer.ActiveSpeakers: uint[] of MSI values for currently speaking participants
    /// </summary>
    public void OnAudioReceived(IntPtr audioData, int length, uint[] activeSpeakers)
    {
        if (_disposed) return;

        try
        {
            // Update active speaker on the transcriber from media platform data
            if (activeSpeakers.Length > 0)
            {
                var primaryMsi = activeSpeakers[0];
                if (_msiToParticipant.TryGetValue(primaryMsi, out var speaker))
                {
                    _transcriber.SetActiveSpeaker(speaker.UserId, speaker.DisplayName);
                }
            }

            // Copy audio from unmanaged memory to managed byte array and push to Speech SDK
            var bytes = new byte[length];
            Marshal.Copy(audioData, bytes, 0, length);
            _transcriber.PushAudio(bytes);
        }
        catch (Exception ex)
        {
            HandleAudioError(ex);
        }
    }

    /// <summary>
    /// Overload accepting a managed byte array directly (for testing or
    /// when audio is already in managed memory).
    /// </summary>
    public void OnAudioReceived(byte[] audioData, uint[] activeSpeakers)
    {
        if (_disposed) return;

        try
        {
            if (activeSpeakers.Length > 0)
            {
                var primaryMsi = activeSpeakers[0];
                if (_msiToParticipant.TryGetValue(primaryMsi, out var speaker))
                {
                    _transcriber.SetActiveSpeaker(speaker.UserId, speaker.DisplayName);
                }
            }

            _transcriber.PushAudio(audioData);
        }
        catch (Exception ex)
        {
            HandleAudioError(ex);
        }
    }

    private void HandleAudioError(Exception ex)
    {
        var count = Interlocked.Increment(ref _audioErrorCount);
        _logger.LogError(ex,
            "Error processing audio frame for meeting {MeetingId} (consecutive: {Count})",
            _meetingId, count);

        // After 50 consecutive errors, notify Python backend so the meeting
        // doesn't appear healthy when transcription is actually broken.
        if (count == 50)
        {
            _ = _backend.SendLifecycleEventAsync(new BotLifecycleEvent(
                _meetingId, _botInstanceId, "bot_error", DateTimeOffset.UtcNow,
                new Dictionary<string, object>
                {
                    ["error"] = $"Audio processing failed after {count} consecutive errors: {ex.Message}",
                }));
        }
    }

    /// <summary>
    /// Update participant roster when the media platform reports changes.
    /// Called by BotService when IParticipantCollection.OnUpdated fires.
    /// Maps media stream IDs (MSI) to participant identities for speaker attribution.
    /// </summary>
    public void UpdateParticipant(uint msi, string userId, string displayName)
    {
        _msiToParticipant[msi] = new ParticipantInfo(userId, displayName);
        _logger.LogDebug(
            "Participant mapped: MSI {Msi} → {DisplayName} ({UserId}) for meeting {MeetingId}",
            msi, displayName, userId, _meetingId);
    }

    /// <summary>
    /// Remove a participant when they leave.
    /// </summary>
    public void RemoveParticipant(uint msi)
    {
        _msiToParticipant.TryRemove(msi, out _);
    }

    /// <summary>
    /// Handle call state transition to Established.
    /// Called by BotService when Graph Communications SDK reports call is active.
    /// </summary>
    public async Task OnCallEstablishedAsync()
    {
        await _transcriber.StartAsync(_meetingId);
        await _backend.SendLifecycleEventAsync(new BotLifecycleEvent(
            _meetingId, _botInstanceId, "bot_joined", DateTimeOffset.UtcNow));

        _logger.LogInformation(
            "Call established for meeting {MeetingId}, transcription started", _meetingId);
    }

    /// <summary>
    /// Handle call state transition to Terminated.
    /// Called by BotService when Graph Communications SDK reports call ended.
    /// </summary>
    public async Task OnCallTerminatedAsync()
    {
        await _transcriber.StopAsync();
        await _backend.SendLifecycleEventAsync(new BotLifecycleEvent(
            _meetingId, _botInstanceId, "meeting_ended", DateTimeOffset.UtcNow));

        _logger.LogInformation(
            "Call terminated for meeting {MeetingId}, transcription stopped", _meetingId);
    }

    /// <summary>
    /// Send participants_updated event to Python backend.
    /// </summary>
    public async Task SendParticipantUpdateAsync()
    {
        var participants = _msiToParticipant.Values
            .Select(p => new Dictionary<string, object>
            {
                ["id"] = p.UserId,
                ["displayName"] = p.DisplayName,
            })
            .ToList();

        await _backend.SendLifecycleEventAsync(new BotLifecycleEvent(
            _meetingId, _botInstanceId, "participants_updated", DateTimeOffset.UtcNow,
            new Dictionary<string, object> { ["participants"] = participants }));
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _msiToParticipant.Clear();
        // SpeechTranscriber lifecycle is managed by BotService
    }

    private record ParticipantInfo(string UserId, string DisplayName);
}

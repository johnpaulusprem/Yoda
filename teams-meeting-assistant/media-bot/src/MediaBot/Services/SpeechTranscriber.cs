using Microsoft.CognitiveServices.Speech;
using Microsoft.CognitiveServices.Speech.Audio;
using Microsoft.Extensions.Options;
using MediaBot.Configuration;
using MediaBot.Models;

namespace MediaBot.Services;

/// <summary>
/// Wraps Azure Speech SDK for continuous recognition. Receives raw PCM audio
/// from the call handler, buffers recognized segments, and periodically flushes
/// them to the Python backend.
///
/// Speaker identification: The CallHandler provides active speaker info from
/// the Teams Real-time Media Platform (IAudioSocket.ActiveSpeakers), which maps
/// to actual Teams participant identities (Graph User ID + display name).
/// This is set via SetActiveSpeaker() before/during audio processing.
/// </summary>
public class SpeechTranscriber : IDisposable
{
    private readonly SpeechOptions _speechOpts;
    private readonly PythonBackendClient _backend;
    private readonly ILogger<SpeechTranscriber> _logger;
    private readonly string _botInstanceId;
    private const int MaxBufferSize = 5000;

    private volatile PushAudioInputStream? _audioStream;
    private SpeechRecognizer? _recognizer;
    private volatile string _meetingId = "";
    private int _sequenceNumber;
    private int _consecutiveFailures;
    private readonly List<TranscriptSegment> _buffer = new();
    private readonly Timer _flushTimer;
    private bool _disposed;

    // Active speaker tracking — set by CallHandler from media platform events.
    // The media platform's AudioMediaReceivedEventArgs.ActiveSpeakers provides
    // participant MSI (media stream ID) which maps to IParticipant identities.
    private volatile string _activeSpeakerId = "";
    private volatile string _activeSpeakerName = "Unknown";

    public SpeechTranscriber(
        IOptions<SpeechOptions> speechOpts,
        PythonBackendClient backend,
        ILogger<SpeechTranscriber> logger)
    {
        _speechOpts = speechOpts.Value;
        _backend = backend;
        _logger = logger;
        _botInstanceId = $"media-bot-{Environment.MachineName}";
        _flushTimer = new Timer(FlushBuffer, null, Timeout.Infinite, Timeout.Infinite);
    }

    public async Task StartAsync(string meetingId)
    {
        _meetingId = meetingId;
        _sequenceNumber = 0;
        Interlocked.Exchange(ref _consecutiveFailures, 0);

        // PCM 16kHz 16-bit mono — matches Teams audio format from IAudioSocket
        var format = AudioStreamFormat.GetWaveFormatPCM(16000, 16, 1);
        _audioStream = AudioInputStream.CreatePushStream(format);
        var audioConfig = AudioConfig.FromStreamInput(_audioStream);

        var speechConfig = SpeechConfig.FromSubscription(
            _speechOpts.SubscriptionKey, _speechOpts.Region);
        speechConfig.SpeechRecognitionLanguage = "en-US";
        speechConfig.EnableDictation();

        _recognizer = new SpeechRecognizer(speechConfig, audioConfig);
        _recognizer.Recognized += OnRecognized;
        _recognizer.Canceled += OnCanceled;

        await _recognizer.StartContinuousRecognitionAsync();
        _flushTimer.Change(TimeSpan.FromSeconds(5), TimeSpan.FromSeconds(5));

        _logger.LogInformation(
            "Speech transcription started for meeting {MeetingId}", meetingId);
    }

    /// <summary>
    /// Update the active speaker identity. Called by CallHandler when the media
    /// platform reports a speaker change via IAudioSocket.ActiveSpeakers.
    /// The speakerId is the Graph User ID; speakerName is the display name from
    /// the IParticipant.Resource.Info.Identity.User properties.
    /// Thread-safe: uses volatile fields for lock-free reads in OnRecognized.
    /// </summary>
    public void SetActiveSpeaker(string speakerId, string speakerName)
    {
        _activeSpeakerId = speakerId;
        _activeSpeakerName = speakerName;
    }

    /// <summary>
    /// Push raw PCM audio bytes into the Speech SDK recognizer.
    /// Called from the call handler's audio callback on a threadpool thread.
    /// </summary>
    public void PushAudio(byte[] audioData)
    {
        _audioStream?.Write(audioData);
    }

    public async Task StopAsync()
    {
        _flushTimer.Change(Timeout.Infinite, Timeout.Infinite);

        if (_recognizer != null)
        {
            try
            {
                await _recognizer.StopContinuousRecognitionAsync();
            }
            catch (Exception ex)
            {
                _logger.LogError(ex,
                    "Error stopping continuous recognition for {MeetingId}", _meetingId);
            }
            _recognizer.Dispose();
            _recognizer = null;
        }

        _audioStream?.Close();
        _audioStream = null;

        await FlushBufferAsync();

        _logger.LogInformation(
            "Speech transcription stopped for meeting {MeetingId}", _meetingId);
    }

    private void OnRecognized(object? sender, SpeechRecognitionEventArgs e)
    {
        if (e.Result.Reason != ResultReason.RecognizedSpeech) return;
        if (string.IsNullOrWhiteSpace(e.Result.Text)) return;

        // Capture active speaker at recognition time — this is the participant
        // the media platform identified as speaking during this audio segment.
        var speakerId = _activeSpeakerId;
        var speakerName = _activeSpeakerName;

        var segment = new TranscriptSegment(
            Sequence: Interlocked.Increment(ref _sequenceNumber),
            SpeakerId: speakerId,
            SpeakerName: speakerName,
            Text: e.Result.Text,
            StartTimeSec: e.Result.OffsetInTicks / 10_000_000.0,
            EndTimeSec: (e.Result.OffsetInTicks + e.Result.Duration.Ticks) / 10_000_000.0,
            Confidence: 0.0,
            IsFinal: true
        );

        lock (_buffer) { _buffer.Add(segment); }
    }

    private void OnCanceled(object? sender, SpeechRecognitionCanceledEventArgs e)
    {
        _logger.LogWarning(
            "Speech recognition canceled for {MeetingId}: {Reason} {Details}",
            _meetingId, e.Reason, e.ErrorDetails);

        // Notify Python backend about speech errors so the meeting doesn't
        // appear healthy when transcription is actually broken.
        if (e.Reason == CancellationReason.Error)
        {
            _ = _backend.SendLifecycleEventAsync(new BotLifecycleEvent(
                _meetingId, _botInstanceId, "bot_error", DateTimeOffset.UtcNow,
                new Dictionary<string, object>
                {
                    ["error"] = $"Speech recognition error: {e.ErrorDetails}",
                    ["error_code"] = e.ErrorCode.ToString(),
                }));
        }
    }

    /// <summary>
    /// Timer callback — wraps FlushBufferAsync with exception handling to
    /// prevent async void from crashing the process.
    /// </summary>
    private async void FlushBuffer(object? state)
    {
        try
        {
            await FlushBufferAsync();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex,
                "Unhandled error in FlushBuffer timer callback for {MeetingId}", _meetingId);
        }
    }

    private async Task FlushBufferAsync()
    {
        List<TranscriptSegment> toSend;
        lock (_buffer)
        {
            if (_buffer.Count == 0) return;
            toSend = new List<TranscriptSegment>(_buffer);
            _buffer.Clear();
        }

        try
        {
            await _backend.SendTranscriptAsync(new TranscriptChunk(
                _meetingId, _botInstanceId, toSend));
            Interlocked.Exchange(ref _consecutiveFailures, 0);
            _logger.LogDebug(
                "Flushed {Count} transcript segments for {MeetingId}",
                toSend.Count, _meetingId);
        }
        catch (Exception ex)
        {
            var failures = Interlocked.Increment(ref _consecutiveFailures);
            _logger.LogError(ex,
                "Failed to flush transcript buffer for {MeetingId} (consecutive failures: {Failures})",
                _meetingId, failures);

            lock (_buffer)
            {
                if (_buffer.Count + toSend.Count <= MaxBufferSize)
                {
                    _buffer.InsertRange(0, toSend);
                }
                else
                {
                    _logger.LogWarning(
                        "Dropping {Count} transcript segments for {MeetingId} — buffer at max capacity ({Max})",
                        toSend.Count, _meetingId, MaxBufferSize);
                }
            }
        }
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _flushTimer.Dispose();
        _recognizer?.Dispose();
        _audioStream?.Dispose();
    }
}

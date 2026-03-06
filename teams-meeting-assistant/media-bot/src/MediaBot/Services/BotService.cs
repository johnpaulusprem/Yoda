using System.Collections.Concurrent;
using System.Net;
using Microsoft.Extensions.Options;
using Microsoft.Graph.Communications.Calls;
using Microsoft.Graph.Communications.Calls.Media;
using Microsoft.Graph.Communications.Client;
using Microsoft.Graph.Communications.Common.Telemetry;
using Microsoft.Graph.Communications.Resources;
using Microsoft.Graph;
using MediaBot.Configuration;
using MediaBot.Models;

namespace MediaBot.Services;

/// <summary>
/// Manages the lifecycle of meeting bot instances. On Windows, initializes the
/// Graph Communications SDK for real-time media access. On non-Windows (dev/test),
/// operates in stub mode with fake call IDs.
///
/// Graph Communications SDK flow:
/// 1. StartAsync: Create ICommunicationsClient with media platform settings
/// 2. JoinMeetingAsync: Parse join URL → create media session → call Graph API
/// 3. Audio frames arrive via IAudioSocket → CallHandler → SpeechTranscriber
/// 4. LeaveMeetingAsync: Hang up call, dispose resources
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

    // Graph Communications SDK client — only initialized on Windows
    private ICommunicationsClient? _commsClient;
    private bool _isWindows;

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
    public ICommunicationsClient? CommsClient => _commsClient;

    public Task StartAsync(CancellationToken ct)
    {
        _isWindows = OperatingSystem.IsWindows();

        if (_isWindows)
        {
            InitializeGraphCommunicationsClient();
        }
        else
        {
            _logger.LogWarning(
                "Graph Communications Media SDK requires Windows. " +
                "Running in STUB MODE — join requests accepted but no real media processing. " +
                "Deploy to Windows Server/AKS Windows node pool for production.");
        }

        _logger.LogInformation(
            "BotService started (capacity: {MaxConcurrentMeetings}, mode: {Mode})",
            MaxConcurrentMeetings,
            _isWindows ? "production" : "stub");

        return Task.CompletedTask;
    }

    /// <summary>
    /// Initialize the Graph Communications SDK with media platform settings.
    /// This sets up the SRTP media platform, notification URL, and auth provider.
    /// Only called on Windows where the native media libraries are available.
    /// </summary>
    private void InitializeGraphCommunicationsClient()
    {
        try
        {
            var authProvider = _sp.GetRequiredService<AuthenticationProvider>();

            var publicIp = !string.IsNullOrEmpty(_opts.MediaPlatformInstancePublicIp)
                ? IPAddress.Parse(_opts.MediaPlatformInstancePublicIp)
                : IPAddress.Loopback;

            var mediaPlatformSettings = new MediaPlatformSettings
            {
                MediaPlatformInstanceSettings = new MediaPlatformInstanceSettings
                {
                    CertificateThumbprint = _opts.CertificateThumbprint ?? "",
                    InstanceInternalPort = _opts.MediaPlatformInstanceInternalPort,
                    InstancePublicIPAddress = publicIp,
                    InstancePublicPort = _opts.MediaPlatformInstanceInternalPort,
                    ServiceFqdn = new Uri(_opts.BotBaseUrl).Host,
                },
                ApplicationId = authProvider.AppId,
            };

            _commsClient = new CommunicationsClientBuilder("MediaBot", authProvider.AppId)
                .SetAuthenticationProvider(new GraphAuthAdapter(authProvider))
                .SetMediaPlatformSettings(mediaPlatformSettings)
                .SetNotificationUrl(new Uri($"{_opts.BotBaseUrl}/api/callbacks"))
                .SetServiceBaseUrl(new Uri("https://graph.microsoft.com/v1.0"))
                .Build();

            _commsClient.Calls().OnIncoming += OnIncomingCall;
            _commsClient.Calls().OnUpdated += OnCallCollectionUpdated;

            _logger.LogInformation(
                "Graph Communications SDK initialized (FQDN: {Fqdn}, Port: {Port})",
                new Uri(_opts.BotBaseUrl).Host,
                _opts.MediaPlatformInstanceInternalPort);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex,
                "Failed to initialize Graph Communications SDK — " +
                "falling back to stub mode");
            _isWindows = false; // Fall back to stub
        }
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
                info.CallHandler?.Dispose();
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

        if (_commsClient != null)
        {
            try
            {
                await _commsClient.TerminateAsync();
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error terminating Graph Communications client");
            }
            _commsClient = null;
        }

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
                var handlerLogger = scope.ServiceProvider.GetRequiredService<ILogger<CallHandler>>();

                string callId;
                CallHandler? callHandler = null;

                if (_isWindows && _commsClient != null)
                {
                    // Production path: use Graph Communications SDK to join meeting
                    callId = await JoinViaGraphSdkAsync(
                        request, backend, transcriber, handlerLogger, out callHandler);
                }
                else
                {
                    // Stub mode: generate fake call ID, start transcriber directly
                    callId = $"stub-{Guid.NewGuid():N}"[..24];
                    callHandler = new CallHandler(transcriber, backend, request.MeetingId, handlerLogger);

                    // In stub mode, simulate bot_joined and start transcription
                    await backend.SendLifecycleEventAsync(new BotLifecycleEvent(
                        request.MeetingId,
                        $"media-bot-{Environment.MachineName}",
                        "bot_joined",
                        DateTimeOffset.UtcNow));
                    await transcriber.StartAsync(request.MeetingId);
                }

                var info = new CallHandlerInfo(callId, scope, transcriber, callHandler);
                if (!_activeHandlers.TryAdd(request.MeetingId, info))
                    throw new InvalidOperationException(
                        $"Concurrent join attempt for meeting {request.MeetingId}");

                _callIdToMeetingId[callId] = request.MeetingId;

                _logger.LogInformation(
                    "Bot joined meeting {MeetingId}, callId={CallId}, mode={Mode}, active={ActiveCount}/{MaxCapacity}",
                    request.MeetingId, callId,
                    _isWindows ? "production" : "stub",
                    _activeHandlers.Count, MaxConcurrentMeetings);

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

    /// <summary>
    /// Join a Teams meeting using the Graph Communications SDK.
    /// Parses the join URL, creates a media session with receive-only audio,
    /// and places the call via Graph API.
    /// </summary>
    private async Task<string> JoinViaGraphSdkAsync(
        JoinMeetingRequest request,
        PythonBackendClient backend,
        SpeechTranscriber transcriber,
        ILogger<CallHandler> handlerLogger,
        out CallHandler callHandler)
    {
        // Parse the Teams meeting join URL into chatInfo + meetingInfo
        var (chatInfo, meetingInfo, tenantId) = TeamsJoinUrlParser.Parse(request.JoinUrl);

        // Create media session: receive-only audio (16kHz PCM mono)
        var mediaSession = _commsClient!.CreateMediaSession(
            new AudioSocketSettings
            {
                StreamDirections = StreamDirection.Recvonly,
                SupportedAudioFormat = AudioFormat.Pcm16K,
            },
            default, // no video
            default  // no VBSS
        );

        // Subscribe to audio frames
        callHandler = new CallHandler(transcriber, backend, request.MeetingId, handlerLogger);
        var handler = callHandler; // capture for lambda

        var audioSocket = mediaSession.AudioSocket;
        audioSocket.AudioMediaReceived += (sender, args) =>
        {
            var buffer = args.Buffer;
            handler.OnAudioReceived(buffer.Data, (int)buffer.Length, buffer.ActiveSpeakers);
            buffer.Dispose();
        };

        // Place the call to join the meeting
        var call = await _commsClient.Calls().AddAsync(new Call
        {
            ChatInfo = chatInfo,
            MeetingInfo = meetingInfo,
            TenantId = tenantId,
            MediaConfig = new AppHostedMediaConfig
            {
                Blob = mediaSession.GetSerializableContent(),
            },
            RequestedModalities = new[] { Modality.Audio },
        }, mediaSession);

        // Subscribe to call state and participant changes
        call.OnUpdated += async (sender, args) =>
        {
            try
            {
                if (sender.Resource.State == CallState.Established)
                    await handler.OnCallEstablishedAsync();
                else if (sender.Resource.State == CallState.Terminated)
                    await handler.OnCallTerminatedAsync();
            }
            catch (Exception ex)
            {
                _logger.LogError(ex,
                    "Error handling call state change for meeting {MeetingId}", request.MeetingId);
            }
        };

        call.Participants.OnUpdated += async (sender, args) =>
        {
            try
            {
                foreach (var participant in sender)
                {
                    var user = participant.Resource?.Info?.Identity?.User;
                    if (user != null && participant.Resource.MediaStreams != null)
                    {
                        foreach (var stream in participant.Resource.MediaStreams)
                        {
                            if (stream.MediaType == Modality.Audio && stream.SourceId.HasValue)
                            {
                                handler.UpdateParticipant(
                                    stream.SourceId.Value,
                                    user.Id ?? "",
                                    user.DisplayName ?? "Unknown");
                            }
                        }
                    }
                }
                await handler.SendParticipantUpdateAsync();
            }
            catch (Exception ex)
            {
                _logger.LogError(ex,
                    "Error handling participant update for meeting {MeetingId}", request.MeetingId);
            }
        };

        return call.Resource.Id;
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
            // Hang up the Graph call FIRST — this triggers the OnCallTerminated
            // callback which sends meeting_ended and stops the transcriber.
            // By doing this before disposing, we avoid ObjectDisposedException
            // in the callback and prevent duplicate meeting_ended events.
            if (_isWindows && _commsClient != null)
            {
                try
                {
                    var call = _commsClient.Calls()[callId];
                    await call.DeleteAsync();
                    // Give the OnCallTerminated callback a moment to fire
                    await Task.Delay(500);
                }
                catch (Exception ex)
                {
                    _logger.LogWarning(ex,
                        "Failed to hang up Graph call {CallId} — may have already ended", callId);
                }
            }
            else
            {
                // Stub mode: no Graph SDK callback, so we handle cleanup directly
                if (info.Transcriber != null)
                {
                    await info.Transcriber.StopAsync();
                }

                var backend = info.Scope.ServiceProvider.GetRequiredService<PythonBackendClient>();
                await backend.SendLifecycleEventAsync(new BotLifecycleEvent(
                    meetingId,
                    $"media-bot-{Environment.MachineName}",
                    "meeting_ended",
                    DateTimeOffset.UtcNow));
            }

            // Now safe to dispose — callback has already fired
            info.CallHandler?.Dispose();
            info.Transcriber?.Dispose();
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

    private void OnIncomingCall(ICallCollection sender, CollectionEventArgs<ICall> args)
    {
        // We don't accept incoming calls — we only join meetings proactively
        _logger.LogInformation("Rejecting incoming call {CallId}", args.AddedResources?.FirstOrDefault()?.Resource?.Id);
    }

    private void OnCallCollectionUpdated(ICallCollection sender, CollectionEventArgs<ICall> args)
    {
        // Log for diagnostics
        _logger.LogDebug("Call collection updated: {Count} calls", sender.Count());
    }

    private record CallHandlerInfo(
        string CallId,
        IServiceScope Scope,
        SpeechTranscriber? Transcriber,
        CallHandler? CallHandler
    );
}

/// <summary>
/// Adapter that bridges our AuthenticationProvider to the Graph Communications SDK's
/// IRequestAuthenticationProvider interface.
/// </summary>
internal class GraphAuthAdapter : Microsoft.Graph.Communications.Client.Authentication.IRequestAuthenticationProvider
{
    private readonly AuthenticationProvider _auth;

    public GraphAuthAdapter(AuthenticationProvider auth)
    {
        _auth = auth;
    }

    public async Task AuthenticateOutboundRequestAsync(HttpRequestMessage request, string tenant)
    {
        await _auth.AuthenticateOutboundRequestAsync(request);
    }

    public async Task<Microsoft.Graph.Communications.Common.RequestValidationResult> ValidateInboundRequestAsync(
        HttpRequestMessage request)
    {
        // TODO: Validate JWT token from Graph callbacks in production
        // For now, accept all — HMAC validation on the controller provides some protection
        var token = request.Headers.Authorization?.Parameter;
        return new Microsoft.Graph.Communications.Common.RequestValidationResult(
            !string.IsNullOrEmpty(token));
    }
}

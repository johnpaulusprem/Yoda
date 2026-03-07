using System.Collections.Concurrent;
using System.Net;
using Microsoft.Extensions.Options;
using Microsoft.Graph.Communications.Calls;
using Microsoft.Graph.Communications.Calls.Media;
using Microsoft.Graph.Communications.Client;
using Microsoft.Graph.Communications.Client.Authentication;
using Microsoft.Graph.Communications.Common.Telemetry;
using Microsoft.Graph.Communications.Resources;
using Microsoft.Graph.Models;
using Microsoft.Skype.Bots.Media;
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
    private IGraphLogger? _graphLogger;
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
        // Validate required config before attempting initialization
        if (string.IsNullOrEmpty(_opts.CertificateThumbprint))
        {
            _logger.LogError(
                "CertificateThumbprint is not configured. " +
                "Set Bot__CertificateThumbprint in environment or appsettings. " +
                "Falling back to stub mode.");
            _isWindows = false;
            return;
        }

        if (string.IsNullOrEmpty(_opts.BotBaseUrl))
        {
            _logger.LogError(
                "BotBaseUrl is not configured. " +
                "Set Bot__BotBaseUrl in environment or appsettings. " +
                "Falling back to stub mode.");
            _isWindows = false;
            return;
        }

        if (string.IsNullOrEmpty(_opts.MediaPlatformInstancePublicIp))
        {
            _logger.LogError(
                "MediaPlatformInstancePublicIp is not configured. " +
                "Set Bot__MediaPlatformInstancePublicIp to the VM's public IP. " +
                "Falling back to stub mode.");
            _isWindows = false;
            return;
        }

        try
        {
            var authProvider = _sp.GetRequiredService<AuthenticationProvider>();

            var publicIp = IPAddress.Parse(_opts.MediaPlatformInstancePublicIp);
            var fqdn = new Uri(_opts.BotBaseUrl).Host;

            var mediaPlatformSettings = new MediaPlatformSettings
            {
                MediaPlatformInstanceSettings = new MediaPlatformInstanceSettings
                {
                    CertificateThumbprint = _opts.CertificateThumbprint,
                    InstanceInternalPort = _opts.MediaPlatformInstanceInternalPort,
                    InstancePublicIPAddress = publicIp,
                    InstancePublicPort = _opts.MediaPlatformInstanceInternalPort,
                    ServiceFqdn = fqdn,
                },
                ApplicationId = authProvider.AppId,
            };

            // Create GraphLogger — required by the SDK for internal diagnostics
            _graphLogger = new GraphLogger("MediaBot");

            _commsClient = new CommunicationsClientBuilder("MediaBot", authProvider.AppId, _graphLogger)
                .SetAuthenticationProvider(new GraphAuthAdapter(authProvider))
                .SetMediaPlatformSettings(mediaPlatformSettings)
                .SetNotificationUrl(new Uri($"{_opts.BotBaseUrl}/api/callbacks"))
                .SetServiceBaseUrl(new Uri("https://graph.microsoft.com/v1.0"))
                .Build();

            _commsClient.Calls().OnIncoming += OnIncomingCall;
            _commsClient.Calls().OnUpdated += OnCallCollectionUpdated;

            _logger.LogInformation(
                "Graph Communications SDK initialized (FQDN: {Fqdn}, Port: {Port}, CertThumbprint: {Thumbprint})",
                fqdn,
                _opts.MediaPlatformInstanceInternalPort,
                _opts.CertificateThumbprint[..8] + "...");
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

        (_graphLogger as IDisposable)?.Dispose();
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
                    var result = await JoinViaGraphSdkAsync(
                        request, backend, transcriber, handlerLogger);
                    callId = result.callId;
                    callHandler = result.callHandler;
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
    private async Task<(string callId, CallHandler callHandler)> JoinViaGraphSdkAsync(
        JoinMeetingRequest request,
        PythonBackendClient backend,
        SpeechTranscriber transcriber,
        ILogger<CallHandler> handlerLogger)
    {
        // Parse the Teams meeting join URL into chatInfo + meetingInfo
        var (chatInfo, meetingInfo, tenantId) = TeamsJoinUrlParser.Parse(request.JoinUrl);

        _logger.LogInformation(
            "Parsed join URL for meeting {MeetingId}: threadId={ThreadId}, tenantId={TenantId}",
            request.MeetingId,
            chatInfo.ThreadId?[..Math.Min(30, chatInfo.ThreadId?.Length ?? 0)],
            tenantId);

        // Create media session: receive-only audio (16kHz PCM mono)
        var mediaSession = _commsClient!.CreateMediaSession(
            new AudioSocketSettings
            {
                StreamDirections = StreamDirection.Recvonly,
                SupportedAudioFormat = AudioFormat.Pcm16K,
            },
            (VideoSocketSettings?)null, // no video
            (VideoSocketSettings?)null  // no VBSS
        );

        // Set up the call handler and audio pipeline BEFORE placing the call
        var callHandler = new CallHandler(transcriber, backend, request.MeetingId, handlerLogger);

        var audioSocket = mediaSession.AudioSocket;
        audioSocket.AudioMediaReceived += (sender, args) =>
        {
            var buffer = args.Buffer;
            callHandler.OnAudioReceived(buffer.Data, (int)buffer.Length, buffer.ActiveSpeakers);
            buffer.Dispose();
        };

        // Build the Graph Call object for joining via app-hosted media
        var callRequest = new Call
        {
            ChatInfo = chatInfo,
            MeetingInfo = meetingInfo,
            TenantId = tenantId,
            MediaConfig = new AppHostedMediaConfig
            {
                Blob = mediaSession.GetMediaConfiguration()?.ToString(),
            },
            RequestedModalities = new List<Modality?> { Modality.Audio },
        };

        _logger.LogInformation(
            "Placing Graph call for meeting {MeetingId} with app-hosted media...",
            request.MeetingId);

        // Place the call to join the meeting
        ICall call;
        try
        {
            call = await _commsClient.Calls().AddAsync(callRequest, mediaSession);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex,
                "Failed to place Graph call for meeting {MeetingId}. " +
                "Check: (1) App registration has Calls.JoinGroupCall.All + Calls.AccessMedia.All permissions, " +
                "(2) Certificate thumbprint {Thumbprint} is in LocalMachine\\My, " +
                "(3) Public IP {PublicIp} is correct, " +
                "(4) Port {Port} is open for TCP+UDP, " +
                "(5) Bot base URL {BaseUrl} is reachable from internet",
                request.MeetingId,
                _opts.CertificateThumbprint?[..Math.Min(8, _opts.CertificateThumbprint?.Length ?? 0)],
                _opts.MediaPlatformInstancePublicIp,
                _opts.MediaPlatformInstanceInternalPort,
                _opts.BotBaseUrl);
            throw;
        }

        // Subscribe to call state changes IMMEDIATELY after AddAsync returns
        call.OnUpdated += async (sender, args) =>
        {
            try
            {
                var state = sender.Resource.State;
                _logger.LogInformation(
                    "Call state changed for meeting {MeetingId}: {State}",
                    request.MeetingId, state);

                if (state == CallState.Established)
                    await callHandler.OnCallEstablishedAsync();
                else if (state == CallState.Terminated)
                    await callHandler.OnCallTerminatedAsync();
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
                    if (user != null && participant.Resource?.MediaStreams != null)
                    {
                        foreach (var stream in participant.Resource.MediaStreams)
                        {
                            if (stream.MediaType == Modality.Audio && !string.IsNullOrEmpty(stream.SourceId)
                                && uint.TryParse(stream.SourceId, out var msi))
                            {
                                callHandler.UpdateParticipant(
                                    msi,
                                    user.Id ?? "",
                                    user.DisplayName ?? "Unknown");
                            }
                        }
                    }
                }
                await callHandler.SendParticipantUpdateAsync();
            }
            catch (Exception ex)
            {
                _logger.LogError(ex,
                    "Error handling participant update for meeting {MeetingId}", request.MeetingId);
            }
        };

        var callId = call.Resource.Id ?? throw new InvalidOperationException("Call resource ID is null");
        _logger.LogInformation(
            "Graph call placed successfully for meeting {MeetingId}, callId={CallId}, state={State}",
            request.MeetingId, callId, call.Resource.State);

        return (callId, callHandler);
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
/// IRequestAuthenticationProvider interface. Implements proper JWT validation for
/// inbound callbacks and tenant-aware token acquisition for outbound requests.
/// </summary>
internal class GraphAuthAdapter : IRequestAuthenticationProvider
{
    private readonly AuthenticationProvider _auth;

    public GraphAuthAdapter(AuthenticationProvider auth)
    {
        _auth = auth;
    }

    public async Task AuthenticateOutboundRequestAsync(HttpRequestMessage request, string tenant)
    {
        // Pass the tenant to get a tenant-specific token
        await _auth.AuthenticateOutboundRequestAsync(request, tenant);
    }

    public async Task<RequestValidationResult> ValidateInboundRequestAsync(
        HttpRequestMessage request)
    {
        var token = request.Headers.Authorization?.Parameter;
        var (isValid, tenantId) = await _auth.ValidateInboundTokenAsync(token);

        var result = new RequestValidationResult { IsValid = isValid };

        // Set tenant on the request properties so the SDK can use it
        if (isValid && !string.IsNullOrEmpty(tenantId))
        {
#pragma warning disable CS0618 // Properties is obsolete but Graph SDK still uses it
            request.Properties["TenantId"] = tenantId;
#pragma warning restore CS0618
        }

        return result;
    }
}

using Microsoft.Extensions.Options;
using Microsoft.Identity.Client;
using MediaBot.Configuration;

namespace MediaBot.Services;

/// <summary>
/// Provides MSAL-based authentication for the Graph Communications SDK.
/// Acquires app-only tokens (daemon flow) for Calls.JoinGroupCalls.All
/// and Calls.AccessMedia.All permissions.
///
/// Implements IRequestAuthenticationProvider from Graph Communications SDK
/// when running on Windows. On non-Windows, provides token acquisition
/// for other Graph API calls.
/// </summary>
public class AuthenticationProvider
{
    private readonly IConfidentialClientApplication _app;
    private readonly string _appId;
    private readonly ILogger<AuthenticationProvider> _logger;

    private static readonly string[] GraphScopes = { "https://graph.microsoft.com/.default" };

    public AuthenticationProvider(
        IOptions<BotOptions> options,
        ILogger<AuthenticationProvider> logger)
    {
        var opts = options.Value;
        _appId = opts.AppId;
        _logger = logger;

        if (string.IsNullOrEmpty(opts.AppId) || string.IsNullOrEmpty(opts.AppSecret))
        {
            _logger.LogWarning(
                "AuthenticationProvider initialized without AppId/AppSecret - Graph API calls will fail");
        }

        _app = ConfidentialClientApplicationBuilder
            .Create(opts.AppId)
            .WithClientSecret(opts.AppSecret)
            .WithAuthority($"https://login.microsoftonline.com/{opts.TenantId}")
            .Build();
    }

    public string AppId => _appId;

    /// <summary>
    /// Acquire an app-only access token for Microsoft Graph.
    /// Uses MSAL token cache - only calls Azure AD when token is expired.
    /// </summary>
    public async Task<string> AcquireTokenAsync()
    {
        try
        {
            var result = await _app.AcquireTokenForClient(GraphScopes).ExecuteAsync();
            return result.AccessToken;
        }
        catch (MsalException ex)
        {
            _logger.LogError(ex,
                "Failed to acquire Graph token for app {AppId}", _appId);
            throw;
        }
    }

    /// <summary>
    /// Add Bearer token to outgoing HTTP request.
    /// Used by Graph Communications SDK for outbound Graph API calls.
    /// </summary>
    public async Task AuthenticateOutboundRequestAsync(HttpRequestMessage request)
    {
        var token = await AcquireTokenAsync();
        request.Headers.Authorization =
            new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", token);
    }
}

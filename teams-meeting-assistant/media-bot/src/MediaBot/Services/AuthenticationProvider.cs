using System.Net.Http.Headers;
using Microsoft.Extensions.Options;
using Microsoft.Identity.Client;
using Microsoft.IdentityModel.Protocols;
using Microsoft.IdentityModel.Protocols.OpenIdConnect;
using Microsoft.IdentityModel.Tokens;
using MediaBot.Configuration;

namespace MediaBot.Services;

/// <summary>
/// Provides MSAL-based authentication for the Graph Communications SDK.
/// Handles both outbound token acquisition (for Graph API calls) and
/// inbound JWT validation (for Graph Communications callbacks).
///
/// Implements the same patterns as Microsoft's official sample:
/// - Outbound: tenant-aware ConfidentialClientApplication token acquisition
/// - Inbound: JWT validation against Skype's OpenID configuration
/// </summary>
public class AuthenticationProvider
{
    private readonly string _appId;
    private readonly string _appSecret;
    private readonly string _defaultTenantId;
    private readonly IConfidentialClientApplication _app;
    private readonly ILogger<AuthenticationProvider> _logger;

    // OpenID configuration for validating Graph Communications callbacks
    private const string OpenIdConfigUrl = "https://api.aps.skype.com/v1/.well-known/OpenIdConfiguration";
    private static readonly string[] ValidIssuers = {
        "https://graph.microsoft.com",
        "https://api.botframework.com",
    };
    private static readonly string[] GraphScopes = { "https://graph.microsoft.com/.default" };

    // Cache the OpenID config manager (thread-safe, auto-refreshes)
    private readonly ConfigurationManager<OpenIdConnectConfiguration> _openIdConfigManager;

    public AuthenticationProvider(
        IOptions<BotOptions> options,
        ILogger<AuthenticationProvider> logger)
    {
        var opts = options.Value;
        _appId = opts.AppId;
        _appSecret = opts.AppSecret;
        _defaultTenantId = opts.TenantId;
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

        _openIdConfigManager = new ConfigurationManager<OpenIdConnectConfiguration>(
            OpenIdConfigUrl,
            new OpenIdConnectConfigurationRetriever(),
            new HttpDocumentRetriever());
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
    /// Uses the specified tenant, falling back to the default tenant from config.
    /// Called by Graph Communications SDK for outbound Graph API calls.
    /// </summary>
    public async Task AuthenticateOutboundRequestAsync(HttpRequestMessage request, string? tenant = null)
    {
        var effectiveTenant = !string.IsNullOrEmpty(tenant) ? tenant : _defaultTenantId;

        try
        {
            // If the tenant matches our default, use the cached MSAL app
            if (effectiveTenant == _defaultTenantId)
            {
                var token = await AcquireTokenAsync();
                request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
                return;
            }

            // For a different tenant, build a tenant-specific app
            var app = ConfidentialClientApplicationBuilder
                .Create(_appId)
                .WithClientSecret(_appSecret)
                .WithAuthority($"https://login.microsoftonline.com/{effectiveTenant}")
                .Build();

            var result = await app.AcquireTokenForClient(GraphScopes).ExecuteAsync();
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", result.AccessToken);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex,
                "Failed to acquire token for tenant {Tenant}", effectiveTenant);
            throw;
        }
    }

    /// <summary>
    /// Validate an inbound JWT token from Graph Communications callbacks.
    /// Validates against Skype's OpenID configuration endpoint.
    /// Returns (isValid, tenantId) — tenantId is extracted from token claims.
    /// </summary>
    public async Task<(bool IsValid, string? TenantId)> ValidateInboundTokenAsync(string? token)
    {
        if (string.IsNullOrEmpty(token))
        {
            _logger.LogWarning("Inbound request has no authorization token");
            return (false, null);
        }

        try
        {
            var openIdConfig = await _openIdConfigManager.GetConfigurationAsync(CancellationToken.None);

            var validationParameters = new TokenValidationParameters
            {
                ValidateIssuer = true,
                ValidIssuers = ValidIssuers,
                ValidateAudience = true,
                ValidAudience = _appId,
                ValidateIssuerSigningKey = true,
                IssuerSigningKeys = openIdConfig.SigningKeys,
                ValidateLifetime = true,
                ClockSkew = TimeSpan.FromMinutes(5),
            };

            var handler = new Microsoft.IdentityModel.JsonWebTokens.JsonWebTokenHandler();
            var validationResult = await handler.ValidateTokenAsync(token, validationParameters);

            if (!validationResult.IsValid)
            {
                _logger.LogWarning("Token validation failed: {Error}", validationResult.Exception?.Message);
                return (false, null);
            }

            var principal = new System.Security.Claims.ClaimsPrincipal(validationResult.ClaimsIdentity);

            // Extract tenant ID from claims
            var tenantId = principal.FindFirst("http://schemas.microsoft.com/identity/claims/tenantid")?.Value
                ?? principal.FindFirst("tid")?.Value;

            _logger.LogDebug("Validated inbound token for tenant {TenantId}", tenantId);
            return (true, tenantId);
        }
        catch (SecurityTokenException ex)
        {
            _logger.LogWarning(ex, "Inbound token validation failed");
            return (false, null);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Unexpected error validating inbound token");
            return (false, null);
        }
    }
}

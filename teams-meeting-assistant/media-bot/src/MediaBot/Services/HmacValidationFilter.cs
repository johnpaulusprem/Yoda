using System.Security.Cryptography;
using System.Text;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Filters;
using Microsoft.Extensions.Options;
using MediaBot.Configuration;

namespace MediaBot.Services;

/// <summary>
/// Action filter that validates HMAC-SHA256 signatures on incoming requests.
/// Applied to controllers/actions that receive commands from the Python backend.
/// </summary>
public class HmacValidationFilter : IAsyncActionFilter
{
    private readonly string _hmacKey;
    private readonly ILogger<HmacValidationFilter> _logger;
    private const int MaxTimestampDriftSeconds = 300;

    public HmacValidationFilter(
        IOptions<PythonBackendOptions> options,
        ILogger<HmacValidationFilter> logger)
    {
        _hmacKey = options.Value.HmacKey;
        _logger = logger;
    }

    public async Task OnActionExecutionAsync(
        ActionExecutingContext context, ActionExecutionDelegate next)
    {
        // Skip validation if no key configured (dev mode)
        if (string.IsNullOrEmpty(_hmacKey))
        {
            await next();
            return;
        }

        var request = context.HttpContext.Request;

        if (!request.Headers.TryGetValue("X-Request-Timestamp", out var tsHeader) ||
            !request.Headers.TryGetValue("X-Request-Signature", out var sigHeader))
        {
            _logger.LogWarning(
                "HMAC validation failed: missing headers for {Method} {Path}",
                request.Method, request.Path);
            context.Result = new UnauthorizedObjectResult(
                new { error = "Missing HMAC headers" });
            return;
        }

        if (!long.TryParse(tsHeader, out var timestamp) ||
            Math.Abs(DateTimeOffset.UtcNow.ToUnixTimeSeconds() - timestamp) > MaxTimestampDriftSeconds)
        {
            _logger.LogWarning(
                "HMAC validation failed: timestamp expired for {Method} {Path}",
                request.Method, request.Path);
            context.Result = new UnauthorizedObjectResult(
                new { error = "Request timestamp expired" });
            return;
        }

        request.EnableBuffering();
        byte[] bodyBytes;
        using (var ms = new MemoryStream())
        {
            await request.Body.CopyToAsync(ms);
            bodyBytes = ms.ToArray();
        }
        request.Body.Position = 0;

        var bodyHash = Convert.ToHexString(SHA256.HashData(bodyBytes)).ToLowerInvariant();
        var payload = $"{timestamp}{request.Method}{request.Path}{bodyHash}";
        var expected = Convert.ToHexString(
            HMACSHA256.HashData(
                Encoding.UTF8.GetBytes(_hmacKey),
                Encoding.UTF8.GetBytes(payload))
        ).ToLowerInvariant();

        if (!CryptographicOperations.FixedTimeEquals(
            Encoding.UTF8.GetBytes(sigHeader.ToString()),
            Encoding.UTF8.GetBytes(expected)))
        {
            _logger.LogWarning(
                "HMAC validation failed: invalid signature for {Method} {Path}",
                request.Method, request.Path);
            context.Result = new UnauthorizedObjectResult(
                new { error = "Invalid signature" });
            return;
        }

        await next();
    }
}

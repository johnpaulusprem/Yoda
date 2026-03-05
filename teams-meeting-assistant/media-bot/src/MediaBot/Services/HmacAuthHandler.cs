using System.Security.Cryptography;
using System.Text;
using Microsoft.Extensions.Options;
using MediaBot.Configuration;

namespace MediaBot.Services;

/// <summary>
/// Delegating handler that signs outgoing HTTP requests with HMAC-SHA256.
/// Compatible with the Python backend's validate_hmac() function.
/// </summary>
public class HmacAuthHandler : DelegatingHandler
{
    private readonly string _hmacKey;
    private readonly IHttpContextAccessor _httpContextAccessor;

    public HmacAuthHandler(
        IOptions<PythonBackendOptions> options,
        IHttpContextAccessor httpContextAccessor)
    {
        _hmacKey = options.Value.HmacKey;
        _httpContextAccessor = httpContextAccessor;
    }

    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request, CancellationToken ct)
    {
        var timestamp = DateTimeOffset.UtcNow.ToUnixTimeSeconds().ToString();
        var method = request.Method.Method;
        var path = request.RequestUri?.PathAndQuery ?? "";

        byte[] bodyBytes;
        if (request.Content != null)
        {
            bodyBytes = await request.Content.ReadAsByteArrayAsync(ct);
        }
        else
        {
            bodyBytes = Array.Empty<byte>();
        }

        var bodyHash = Convert.ToHexString(SHA256.HashData(bodyBytes)).ToLowerInvariant();
        var payload = $"{timestamp}{method}{path}{bodyHash}";
        var keyBytes = Encoding.UTF8.GetBytes(_hmacKey);
        var sig = Convert.ToHexString(
            HMACSHA256.HashData(keyBytes, Encoding.UTF8.GetBytes(payload))
        ).ToLowerInvariant();

        request.Headers.Add("X-Request-Timestamp", timestamp);
        request.Headers.Add("X-Request-Signature", sig);

        // Propagate correlation ID from incoming request, or generate new one
        var correlationId = _httpContextAccessor.HttpContext?
            .Request.Headers["X-Correlation-Id"].FirstOrDefault()
            ?? Guid.NewGuid().ToString();
        request.Headers.Add("X-Correlation-Id", correlationId);

        // Re-create content since we consumed the stream, preserving all headers.
        // IMPORTANT: ByteArrayContent defaults to application/octet-stream, so we must
        // clear it before restoring original headers (TryAddWithoutValidation won't
        // override an existing Content-Type).
        if (bodyBytes.Length > 0)
        {
            var originalHeaders = request.Content?.Headers.ToList()
                ?? new List<KeyValuePair<string, IEnumerable<string>>>();
            request.Content = new ByteArrayContent(bodyBytes);
            request.Content.Headers.ContentType = null; // Clear default octet-stream
            foreach (var header in originalHeaders)
            {
                request.Content.Headers.TryAddWithoutValidation(header.Key, header.Value);
            }
        }

        return await base.SendAsync(request, ct);
    }
}

using Microsoft.Extensions.Options;
using MediaBot.Configuration;
using MediaBot.Services;

var builder = WebApplication.CreateBuilder(args);

// Configuration
builder.Services.Configure<BotOptions>(
    builder.Configuration.GetSection(BotOptions.Section));
builder.Services.Configure<SpeechOptions>(
    builder.Configuration.GetSection(SpeechOptions.Section));
builder.Services.Configure<PythonBackendOptions>(
    builder.Configuration.GetSection(PythonBackendOptions.Section));

// Core services
builder.Services.AddControllers();
builder.Services.AddHealthChecks();
builder.Services.AddHttpContextAccessor();

// Request logging
builder.Services.AddHttpLogging(opts =>
{
    opts.LoggingFields = Microsoft.AspNetCore.HttpLogging.HttpLoggingFields.RequestMethod
        | Microsoft.AspNetCore.HttpLogging.HttpLoggingFields.RequestPath
        | Microsoft.AspNetCore.HttpLogging.HttpLoggingFields.ResponseStatusCode
        | Microsoft.AspNetCore.HttpLogging.HttpLoggingFields.Duration;
});

// Authentication provider (MSAL — singleton for token caching)
builder.Services.AddSingleton<AuthenticationProvider>();

// HMAC validation filter (scoped — used by MeetingsController)
builder.Services.AddScoped<HmacValidationFilter>();

// HMAC-signed HTTP client for Python backend
builder.Services.AddTransient<HmacAuthHandler>();
builder.Services.AddHttpClient<PythonBackendClient>((sp, client) =>
{
    var opts = sp.GetRequiredService<IOptions<PythonBackendOptions>>();
    client.BaseAddress = new Uri(opts.Value.BaseUrl);
    client.Timeout = TimeSpan.FromSeconds(30);
})
.AddHttpMessageHandler<HmacAuthHandler>();

// Speech transcriber (one per meeting — transient)
builder.Services.AddTransient<SpeechTranscriber>();

// Bot service (singleton — manages all active meetings)
builder.Services.AddSingleton<BotService>();
builder.Services.AddHostedService(sp => sp.GetRequiredService<BotService>());

var app = builder.Build();

// Correlation ID middleware — propagate or generate for distributed tracing
app.Use(async (context, next) =>
{
    if (!context.Request.Headers.TryGetValue("X-Correlation-Id", out var correlationId)
        || string.IsNullOrEmpty(correlationId))
    {
        correlationId = Guid.NewGuid().ToString();
    }
    context.Response.Headers["X-Correlation-Id"] = correlationId;

    using (app.Logger.BeginScope(new Dictionary<string, object>
    {
        ["CorrelationId"] = correlationId.ToString()!
    }))
    {
        await next();
    }
});

app.UseHttpLogging();
app.MapControllers();
app.MapHealthChecks("/health/live");

app.Run();

using System.Text.Json.Serialization;

namespace MediaBot.Models;

public record BotLifecycleEvent(
    [property: JsonPropertyName("meeting_id")] string MeetingId,
    [property: JsonPropertyName("bot_instance_id")] string BotInstanceId,
    [property: JsonPropertyName("event_type")] string EventType,
    [property: JsonPropertyName("timestamp")] DateTimeOffset Timestamp,
    [property: JsonPropertyName("data")] Dictionary<string, object>? Data = null
);

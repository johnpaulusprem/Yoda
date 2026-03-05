using System.ComponentModel.DataAnnotations;
using System.Text.Json.Serialization;

namespace MediaBot.Models;

public record JoinMeetingRequest(
    [property: JsonPropertyName("meetingId")]
    [Required(AllowEmptyStrings = false)]
    string MeetingId,

    [property: JsonPropertyName("joinUrl")]
    [Required(AllowEmptyStrings = false)]
    [Url]
    string JoinUrl,

    [property: JsonPropertyName("scheduledStart")] string? ScheduledStart = null,
    [property: JsonPropertyName("scheduledEnd")] string? ScheduledEnd = null
);

public record JoinMeetingResponse(
    [property: JsonPropertyName("callId")] string CallId,
    [property: JsonPropertyName("status")] string Status
);

public record CapacityResponse(
    [property: JsonPropertyName("currentMeetings")] int CurrentMeetings,
    [property: JsonPropertyName("maxMeetings")] int MaxMeetings,
    [property: JsonPropertyName("canAccept")] bool CanAccept
);

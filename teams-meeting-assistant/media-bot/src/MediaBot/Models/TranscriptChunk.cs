using System.Text.Json.Serialization;

namespace MediaBot.Models;

public record TranscriptChunk(
    [property: JsonPropertyName("meeting_id")] string MeetingId,
    [property: JsonPropertyName("bot_instance_id")] string BotInstanceId,
    [property: JsonPropertyName("segments")] List<TranscriptSegment> Segments
);

public record TranscriptSegment(
    [property: JsonPropertyName("sequence")] int Sequence,
    [property: JsonPropertyName("speaker_id")] string SpeakerId,
    [property: JsonPropertyName("speaker_name")] string SpeakerName,
    [property: JsonPropertyName("text")] string Text,
    [property: JsonPropertyName("start_time_sec")] double StartTimeSec,
    [property: JsonPropertyName("end_time_sec")] double EndTimeSec,
    [property: JsonPropertyName("confidence")] double Confidence,
    [property: JsonPropertyName("is_final")] bool IsFinal
);

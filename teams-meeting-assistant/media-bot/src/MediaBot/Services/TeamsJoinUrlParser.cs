using System.Text.Json;
using System.Web;
using Microsoft.Graph;

namespace MediaBot.Services;

/// <summary>
/// Parses Teams meeting join URLs into ChatInfo and OrganizerMeetingInfo
/// required by the Graph Communications SDK to join a meeting.
///
/// Teams join URL format:
/// https://teams.microsoft.com/l/meetup-join/{threadId}/0?context={"Tid":"{tenantId}","Oid":"{organizerId}"}
///
/// Note: JoinInfo.ParseJoinURL() is NOT a public API in the Graph Communications SDK.
/// This helper manually parses the URL components.
/// </summary>
public static class TeamsJoinUrlParser
{
    /// <summary>
    /// Parse a Teams meeting join URL into the components needed for Graph SDK call join.
    /// </summary>
    public static (ChatInfo ChatInfo, OrganizerMeetingInfo MeetingInfo, string TenantId) Parse(string joinUrl)
    {
        if (string.IsNullOrWhiteSpace(joinUrl))
            throw new ArgumentException("Join URL cannot be empty", nameof(joinUrl));

        var uri = new Uri(joinUrl);

        // Extract thread ID from path: /l/meetup-join/{encodedThreadId}/...
        var pathSegments = uri.AbsolutePath.Split('/', StringSplitOptions.RemoveEmptyEntries);
        var meetupJoinIndex = Array.IndexOf(pathSegments, "meetup-join");
        if (meetupJoinIndex < 0 || meetupJoinIndex + 1 >= pathSegments.Length)
            throw new ArgumentException($"Invalid Teams join URL — cannot find meetup-join segment: {joinUrl}");

        var threadId = HttpUtility.UrlDecode(pathSegments[meetupJoinIndex + 1]);
        var messageId = meetupJoinIndex + 2 < pathSegments.Length
            ? pathSegments[meetupJoinIndex + 2]
            : "0";

        // Extract tenant ID and organizer ID from context query parameter
        var queryParams = HttpUtility.ParseQueryString(uri.Query);
        var contextJson = queryParams["context"];
        if (string.IsNullOrEmpty(contextJson))
            throw new ArgumentException($"Invalid Teams join URL — missing context parameter: {joinUrl}");

        string tenantId;
        string organizerId;
        try
        {
            using var doc = JsonDocument.Parse(contextJson);
            tenantId = doc.RootElement.GetProperty("Tid").GetString()
                ?? throw new ArgumentException("Missing Tid in context");
            organizerId = doc.RootElement.GetProperty("Oid").GetString()
                ?? throw new ArgumentException("Missing Oid in context");
        }
        catch (JsonException ex)
        {
            throw new ArgumentException($"Invalid context JSON in Teams join URL: {ex.Message}", ex);
        }

        var chatInfo = new ChatInfo
        {
            ThreadId = threadId,
            MessageId = messageId,
        };

        var meetingInfo = new OrganizerMeetingInfo
        {
            Organizer = new IdentitySet
            {
                User = new Identity
                {
                    Id = organizerId,
                    AdditionalData = new Dictionary<string, object>
                    {
                        ["tenantId"] = tenantId,
                    },
                },
            },
        };

        return (chatInfo, meetingInfo, tenantId);
    }
}

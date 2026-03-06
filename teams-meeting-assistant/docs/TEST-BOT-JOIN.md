# Test: Bot joins a call and transcribes

This guide walks through testing that a bot can join a Teams meeting and that transcription is received and stored.

---

## Two ways the bot can join

| Path | Who joins | Where transcript comes from |
|------|-----------|-----------------------------|
| **ACS** | Python backend uses **Azure Communication Services** Call Automation | ACS streams transcript to our WebSocket ` /ws/transcription/{meeting_id}` → saved to DB |
| **Media Bot** | **C# Media Bot** (separate service) joins via Graph Communications | Media Bot sends transcript to `POST /api/bot-events/transcript` → saved to DB |

The **API** (`POST /api/meetings/{meeting_id}/join`) uses the **ACS** path. The **scheduler** (calendar watcher) uses the **Media Bot** path when it triggers a join before a meeting starts.

---

## Prerequisites

### For ACS path (recommended for a first test)

1. **Azure Communication Services** resource and **Call Automation** enabled.
2. **`.env`** in `teams-meeting-assistant/`:
   - `ACS_CONNECTION_STRING` – from Azure portal (ACS resource → Keys).
   - `BASE_URL` – **must be a public URL** (e.g. `https://your-ngrok-url.ngrok.io`). ACS and Teams call back to this URL; `http://localhost:8000` will not work.
3. **Public URL in local dev**: use [ngrok](https://ngrok.com/) or similar:
   ```bash
   ngrok http 8000
   ```
   Set `BASE_URL` to the `https://...` URL ngrok shows.

### For Media Bot path

1. **C# Media Bot** running (see `media-bot/`). It requires Windows and Azure Bot + Speech configuration.
2. **`.env`**:
   - `MEDIA_BOT_BASE_URL=http://<host>:8080`
   - `INTER_SERVICE_HMAC_KEY` – same value as in the Media Bot’s `PythonBackend.HmacKey`.
3. Trigger join via the **scheduler** (create an opted-in user and a meeting that the watcher picks up), or add a small script that calls `BotCommander.join_meeting(meeting_id, join_url)` for a test meeting.

---

## Step-by-step test (ACS path)

### 1. Get a Teams meeting join URL

- In Teams (or Outlook), create a meeting and copy the **Join** link (e.g. `https://teams.microsoft.com/l/meetup-join/...`), or use an existing meeting you can join.

### 2. Create a meeting in the API

```bash
curl -X POST http://localhost:8000/api/meetings \
  -H "Content-Type: application/json" \
  -d '{
    "join_url": "https://teams.microsoft.com/l/meetup-join/YOUR_JOIN_LINK_HERE",
    "subject": "Bot test meeting"
  }'
```

Response includes `"id": "<meeting_id>"`. Use that `meeting_id` below.

### 3. Trigger the bot to join

```bash
curl -X POST http://localhost:8000/api/meetings/{meeting_id}/join
```

If ACS and `BASE_URL` are correctly set, the backend will join the meeting and ACS will stream transcription to our WebSocket. You should see the meeting status move to `in_progress` (e.g. via `GET /api/meetings/{meeting_id}`).

### 4. Join the meeting yourself (optional)

Open the same Teams join URL in a browser or the Teams app and speak; the bot will be in the call and transcription should flow to the backend.

### 5. Check transcript

```bash
curl http://localhost:8000/api/meetings/{meeting_id}/transcript
```

Segments appear as the call is transcribed (only **Final** results are stored). If the meeting has ended, call again to see the full transcript.

### 6. Leave the meeting (optional)

```bash
curl -X POST http://localhost:8000/api/meetings/{meeting_id}/leave
```

---

## Troubleshooting

- **Join returns 502 or “Failed to join meeting via ACS”**  
  Check `ACS_CONNECTION_STRING`, and that your ACS resource has Call Automation and (if required) Teams interop configured.

- **No transcript segments**  
  - Ensure `BASE_URL` is **public** (e.g. ngrok). ACS must be able to open a WebSocket to `wss://<BASE_URL>/ws/transcription/{meeting_id}`.
  - Check app logs for WebSocket connection and transcription messages.
  - Confirm the meeting has started and someone (or the bot) is speaking; only final segments are stored.

- **Using the Media Bot instead of ACS**  
  The calendar watcher uses the Media Bot. For a direct test, run the Media Bot, ensure it can reach the Python app at `PythonBackend.BaseUrl`, and trigger a join (e.g. by creating a meeting and having the scheduler run, or by calling the Media Bot’s `POST /api/meetings/join` with the same `meetingId` and `joinUrl` used in the Python meeting record).

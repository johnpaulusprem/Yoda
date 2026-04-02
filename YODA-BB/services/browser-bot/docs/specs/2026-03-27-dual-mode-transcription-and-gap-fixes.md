# Dual-Mode Caption + Audio Transcription & Gap Fixes

**Date:** 2026-03-27
**Status:** Approved
**Scope:** Browser bot — `YODA-BB/teams-meeting-assistant/browser-bot/`

---

## 1. Overview

Add caption-based transcription as the primary transcription source, with the existing audio pipeline running as hot standby. Both pipelines run simultaneously — caption segments are preferred for speaker identity, audio segments fill gaps (overlapping speech, caption unavailability). Additionally, fix 6 high-priority gaps identified in the code review.

## 2. Caption Capture Pipeline

### 2.1 New File: `src/platforms/msteams/caption-capture.ts`

**Purpose:** Enable Teams live captions, observe the caption DOM, extract speaker + text, emit structured segments.

**Interface:**
```typescript
export interface CaptionSegment {
  speaker: string;       // Microsoft account display name from caption
  text: string;          // Finalized caption text
  timestamp: number;     // Unix timestamp (ms)
}

export interface CaptionStream {
  readonly isActive: boolean;   // Whether captions are enabled and producing data
  onSegment(cb: (seg: CaptionSegment) => void): void;
  stop(): Promise<void>;
}

export async function startCaptionCapture(page: Page): Promise<CaptionStream>;
```

**Enable captions flow:**
1. Wait 3 seconds after join for Teams UI to stabilize
2. Try keyboard shortcut `Ctrl+Shift+U` to toggle captions on
3. Verify caption container appears within 10 seconds using selectors:
   - `[data-tid="closed-caption-text"]`
   - `[data-tid="caption-container"]`
   - `#annotationContainer`
   - `.ts-captions-container`
4. If no container found, try clicking the CC button:
   - `[data-tid="toggle-captions-button"]`
   - `button[aria-label*="caption" i]`
   - `button[aria-label*="subtitle" i]`
5. If still not found after 3 retries (5s apart), set `isActive = false` and return. Audio pipeline handles transcription alone.

**Caption observation:**
1. First, call `page.exposeFunction("__yodaOnCaption", ...)` to register the Node.js callback BEFORE injecting in-page code (same pattern as audio capture's `__yodaOnAudioData`)
2. Then inject via `page.evaluate`:
   - `MutationObserver` on the caption container with `{ childList: true, subtree: true, characterData: true }`
   - Track current speaker and current text per caption element
   - **Finalization:** A caption is considered "final" when its text has not changed for 500ms (debounce). Teams updates partial text in-place, then moves to the next caption when the speaker changes or a pause occurs.
   - Each finalized segment calls `window.__yodaOnCaption(speaker, text, timestamp)`

**Caption health monitoring:**
- If no caption events received for 30 seconds during an active meeting, log a warning
- If no events for 60 seconds, set `isActive = false` and log an alert
- `isActive` flag is readable by `TranscriptionService` to know whether to promote audio segments

**Cleanup:**
- Disconnect MutationObserver
- Clear debounce timers
- Nullify exposed function references

### 2.2 Changes to `src/services/transcription.ts`

Add a new method:
```typescript
pushCaptionSegment(speaker: string, text: string): void
```

This method:
1. Creates a `TranscriptSegment` with `source: "caption"` and the provided speaker name
2. Uses a separate sequence counter starting at 0 (caption sequences)
3. Sends via `backend.sendTranscriptChunk()`

Existing `emitSegment` (from audio pipeline):
1. Add `source: "audio"` to all audio-originated segments
2. Use sequence numbers starting at 100,000 to avoid collision with caption sequences

New property:
```typescript
captionActive: boolean = false;
```
Set by `bot-manager.ts` based on `CaptionStream.isActive`. When `captionActive` is true, audio segments are still sent (hot standby) but the Python backend knows caption data is the primary source.

### 2.3 Changes to `src/services/python-backend.ts`

Add `source` field to `TranscriptSegment` interface:
```typescript
export interface TranscriptSegment {
  // ... existing fields ...
  source: "caption" | "audio";
}
```

Add `source` to the `sendTranscriptChunk` payload mapping:
```typescript
source: s.source,
```

No other changes to PythonBackendClient.

### 2.4 Changes to `src/services/bot-manager.ts`

In `joinMeeting()`, after Step 5 (speaker detection), add Step 5b:

```
// Step 5b: Start caption capture
const captionStream = await startCaptionCapture(page);
if (captionStream.isActive) {
  transcription.captionActive = true;
  captionStream.onSegment((seg) => {
    transcription.pushCaptionSegment(seg.speaker, seg.text);
  });
}
```

Add `captionStream` to `ActiveMeeting` interface.
Add `captionStream.stop()` to cleanup chain (before `audioStream.stop()`).

### 2.5 Python Backend Changes

**Schema (`bot_events.py` / `TranscriptChunkIn`):**
Add optional `source` field to segment schema:
```python
source: str | None = None  # "caption" or "audio"
```

**Model (`TranscriptSegment`):**
Add nullable column:
```python
source: Mapped[str | None] = mapped_column(String(10), nullable=True)
```

**Migration:**
Alembic migration to add `source` column to `transcript_segments` table. Nullable, no default — existing rows get `NULL`.

No deduplication logic changes. The existing `(meeting_id, sequence_number)` unique constraint handles it because caption and audio pipelines use separate sequence number ranges.

---

## 3. Gap Fix: Structured Logging

### 3.1 Problem
Browser bot uses `console.log` / `console.error` everywhere. Python backend uses structured JSON logging. Logs can't be ingested by Azure Monitor / ELK.

### 3.2 Solution

Create `src/utils/logger.ts`:
```typescript
import { createLogger, format, transports } from "winston";

export const logger = createLogger({
  level: process.env.LOG_LEVEL || "info",
  format: format.combine(
    format.timestamp(),
    format.json()
  ),
  defaultMeta: { service: "browser-bot" },
  transports: [new transports.Console()],
});
```

Replace all `console.log` / `console.error` / `console.warn` calls across all files with `logger.info` / `logger.error` / `logger.warn`. Include structured metadata:
```typescript
logger.info("Bot joined meeting", { meetingId, callId, captionActive: true });
```

**Dependencies:** Add `winston` to `package.json`.

**Files changed:** All 7 source files (`index.ts`, `bot-manager.ts`, `join.ts`, `audio-capture.ts`, `speaker-detection.ts`, `transcription.ts`, `python-backend.ts`).

---

## 4. Gap Fix: HMAC Replay Protection

### 4.1 Problem
`python-backend.ts` signs requests with timestamp but the 5-minute window allows unlimited replays of the same request.

### 4.2 Solution

Add a nonce (UUID v4) to each request. Include it in the HMAC payload:

```typescript
const nonce = crypto.randomUUID();
const payload = `${timestamp}${nonce}POST${path}${bodyHash}`;
```

Send as header: `X-Request-Nonce: <nonce>`

**Python backend side** (`hmac_auth.py`):
1. Include nonce in HMAC payload verification
2. Store seen nonces in a set with TTL (in-memory with `cachetools.TTLCache(maxsize=10000, ttl=300)`)
3. Reject any request with a previously-seen nonce
4. Reduce timestamp window from 300s to 60s for inter-service calls

---

## 5. Gap Fix: Deep Health Check

### 5.1 Problem
`/health/live` returns static `{"status":"ok"}` regardless of actual system state.

### 5.2 Solution

Add `/health/ready` endpoint (auth-protected):
```json
{
  "status": "ok" | "degraded" | "unhealthy",
  "browser": {
    "connected": true,
    "contexts": 2,
    "memoryMB": 512
  },
  "meetings": {
    "active": 2,
    "capacity": 3,
    "details": [
      {
        "meetingId": "abc-123",
        "captionActive": true,
        "audioActive": true,
        "durationMin": 15,
        "lastTranscriptAgoSec": 3
      }
    ]
  },
  "uptime": 3600
}
```

**Status logic:**
- `ok`: Browser connected, all meetings have active transcription
- `degraded`: Browser connected but any meeting has no transcript data for >60s
- `unhealthy`: Browser disconnected or no meetings responding

Keep `/health/live` as-is (lightweight liveness probe for container orchestration).

---

## 6. Gap Fix: Continuous Audio Silence Detection

### 6.1 Problem
Audio diagnostic runs once at 5 seconds. No ongoing monitoring to detect when audio pipeline goes silent.

### 6.2 Solution

In `audio-capture.ts`, add a periodic silence check (every 10 seconds) inside the page context:
- Track last non-silent audio timestamp
- If RMS < 0.0001 for >30 consecutive seconds, emit a warning event to Node.js via `page.exposeFunction("__yodaOnAudioSilence", ...)`
- `TranscriptionService` receives the silence alert and logs it with structured metadata
- If silence persists for >120 seconds, log an error (likely broken pipeline)

This does NOT auto-recover — it alerts. Recovery would require rejoining, which is a separate future improvement.

---

## 7. Gap Fix: Browser Restart Policy

### 7.1 Problem
Chrome leaks memory over time. Industry restarts every 60 minutes or 100 renders. Current bot runs indefinitely.

### 7.2 Solution

In `BotManager`, track browser creation time:
```typescript
private browserCreatedAt: number = 0;
private meetingsSinceBrowserLaunch: number = 0;
```

In `ensureBrowser()`, check:
```typescript
const MAX_BROWSER_AGE_MS = 4 * 60 * 60 * 1000; // 4 hours
const MAX_MEETINGS_PER_BROWSER = 50;

const shouldRestart = this.browser &&
  this.browser.isConnected() &&
  this.meetings.size === 0 && // Only restart when no active meetings
  (Date.now() - this.browserCreatedAt > MAX_BROWSER_AGE_MS ||
   this.meetingsSinceBrowserLaunch >= MAX_MEETINGS_PER_BROWSER);

if (shouldRestart) {
  logger.info("Restarting browser for memory hygiene", {
    ageMinutes: (Date.now() - this.browserCreatedAt) / 60000,
    meetingsServed: this.meetingsSinceBrowserLaunch,
  });
  await this.browser.close().catch(() => {});
  this.browser = null;
}
```

Browser is only restarted when idle (no active meetings). Active meetings are never interrupted.

---

## 8. Gap Fix: Prometheus Metrics

### 8.1 Problem
Zero observability metrics exposed.

### 8.2 Solution

Add `prom-client` dependency. Create `src/utils/metrics.ts`:

```typescript
import { Counter, Gauge, Histogram, Registry } from "prom-client";

export const registry = new Registry();

export const meetingsActive = new Gauge({
  name: "browser_bot_meetings_active",
  help: "Number of active meetings",
  registers: [registry],
});

export const transcriptSegmentsTotal = new Counter({
  name: "browser_bot_transcript_segments_total",
  help: "Total transcript segments sent",
  labelNames: ["source"], // "caption" or "audio"
  registers: [registry],
});

export const audioSilenceTotal = new Counter({
  name: "browser_bot_audio_silence_alerts_total",
  help: "Audio silence alerts triggered",
  registers: [registry],
});

export const joinDuration = new Histogram({
  name: "browser_bot_join_duration_seconds",
  help: "Time to join a meeting",
  buckets: [5, 10, 30, 60, 120, 180],
  registers: [registry],
});

export const browserMemoryMB = new Gauge({
  name: "browser_bot_browser_memory_mb",
  help: "Browser process memory in MB",
  registers: [registry],
});

export const errorsTotal = new Counter({
  name: "browser_bot_errors_total",
  help: "Total errors",
  labelNames: ["type"], // "join_failed", "audio_capture", "caption_capture", "backend_send"
  registers: [registry],
});
```

Expose via `/metrics` endpoint in `index.ts` (no auth — standard for Prometheus scraping behind firewall):
```typescript
app.get("/metrics", async (_req, res) => {
  res.set("Content-Type", registry.contentType);
  res.send(await registry.metrics());
});
```

Instrument all key codepaths: meeting join/leave, segment emission, errors, silence alerts.

---

## 9. Files Changed Summary

| File | Change Type | What Changes |
|------|-------------|--------------|
| `src/platforms/msteams/caption-capture.ts` | **NEW** | Caption DOM scraping pipeline |
| `src/utils/logger.ts` | **NEW** | Winston structured logger |
| `src/utils/metrics.ts` | **NEW** | Prometheus metrics |
| `src/services/transcription.ts` | MODIFY | Add `pushCaptionSegment`, `source` field, `captionActive` flag |
| `src/services/python-backend.ts` | MODIFY | Add `source` to segment interface and payload |
| `src/services/bot-manager.ts` | MODIFY | Wire caption capture, browser restart policy, metrics |
| `src/platforms/msteams/audio-capture.ts` | MODIFY | Add continuous silence detection |
| `src/platforms/msteams/join.ts` | MODIFY | Replace console.log with structured logger |
| `src/platforms/msteams/speaker-detection.ts` | MODIFY | Replace console.log with structured logger |
| `src/index.ts` | MODIFY | Add `/health/ready`, `/metrics`, structured logger |
| `package.json` | MODIFY | Add `winston`, `prom-client` |

**Python backend (separate service):**

| File | Change Type |
|------|-------------|
| `schemas/bot_events.py` | Add optional `source` field |
| `models/transcript.py` (foundation) | Add nullable `source` column |
| `utils/hmac_auth.py` | Add nonce validation |
| `alembic/versions/` | New migration for `source` column |

---

## 10. What Is NOT In Scope

- Container-per-meeting architecture (separate initiative)
- Meeting rejoin on failure
- Multi-language caption support
- Deepgram/Whisper fallback provider
- Recording capability
- Unit tests (will be in implementation plan as tasks, but design is for the feature)

---

## 11. Dependencies

| Dependency | Version | Purpose |
|------------|---------|---------|
| `winston` | `^3.x` | Structured JSON logging |
| `prom-client` | `^15.x` | Prometheus metrics |
| `cachetools` (Python) | existing | TTL cache for nonce tracking |

No new Azure services. No infrastructure changes. No Dockerfile changes.

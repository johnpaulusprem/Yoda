# Dual-Mode Caption + Audio Transcription & Gap Fixes

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add caption-based transcription as primary source alongside existing audio pipeline, plus fix 6 production gaps (structured logging, HMAC replay protection, deep health check, audio silence detection, browser restart policy, Prometheus metrics).

**Architecture:** Both caption and audio pipelines run simultaneously. Caption segments use sequence numbers 0+, audio uses 100000+. Each segment carries a `source` field ("caption" or "audio"). Python backend stores source but dedup logic is unchanged. Six cross-cutting gap fixes improve observability, security, and reliability.

**Tech Stack:** TypeScript (Playwright, Express), Python (FastAPI, SQLAlchemy), Winston, prom-client, cachetools.

**Spec:** `docs/specs/2026-03-27-dual-mode-transcription-and-gap-fixes.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/utils/logger.ts` | CREATE | Winston JSON structured logger |
| `src/utils/metrics.ts` | CREATE | Prometheus metrics definitions |
| `src/platforms/msteams/caption-capture.ts` | CREATE | Caption DOM scraping pipeline |
| `src/services/python-backend.ts` | MODIFY | Add `source` field to segment interface/payload |
| `src/services/transcription.ts` | MODIFY | Add `pushCaptionSegment`, dual sequence counters, `captionActive` flag |
| `src/services/bot-manager.ts` | MODIFY | Wire caption capture, browser restart, metrics, logger |
| `src/platforms/msteams/audio-capture.ts` | MODIFY | Add continuous silence detection, logger |
| `src/platforms/msteams/join.ts` | MODIFY | Replace console.log with logger |
| `src/platforms/msteams/speaker-detection.ts` | MODIFY | Replace console.log with logger |
| `src/index.ts` | MODIFY | Add `/health/ready`, `/metrics`, logger, metrics |
| `package.json` | MODIFY | Add winston, prom-client |
| **Python backend** | | |
| `meeting-service/src/meeting_service/schemas/bot_events.py` | MODIFY | Add optional `source` to `TranscriptSegmentIn` |
| `foundation/src/yoda_foundation/models/transcript.py` | MODIFY | Add nullable `source` column |
| `meeting-service/src/meeting_service/utils/hmac_auth.py` | MODIFY | Add nonce validation |
| `meeting-service/src/meeting_service/routes/bot_events.py` | MODIFY | Pass `source` when creating TranscriptSegment |
| `alembic/versions/` | CREATE | Migration for `source` column |

---

### Task 1: Add dependencies

**Files:**
- Modify: `YODA-BB/teams-meeting-assistant/browser-bot/package.json`

- [ ] **Step 1: Install winston and prom-client**

```bash
cd /Users/srinivaasant/YODA/YODA-BB/teams-meeting-assistant/browser-bot
npm install winston prom-client
```

- [ ] **Step 2: Verify package.json updated**

```bash
cat package.json | grep -E "winston|prom-client"
```

Expected: Both packages appear in `dependencies`.

- [ ] **Step 3: Verify TypeScript compiles**

```bash
npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 4: Commit**

```bash
git add package.json package-lock.json
git commit -m "chore: add winston and prom-client dependencies"
```

---

### Task 2: Create structured logger

**Files:**
- Create: `src/utils/logger.ts`

- [ ] **Step 1: Create the logger module**

```typescript
// src/utils/logger.ts
import { createLogger, format, transports } from "winston";

const LOG_LEVEL = process.env.LOG_LEVEL || "info";

export const logger = createLogger({
  level: LOG_LEVEL,
  format: format.combine(
    format.timestamp({ format: "ISO" }),
    format.errors({ stack: true }),
    format.json()
  ),
  defaultMeta: { service: "browser-bot" },
  transports: [new transports.Console()],
});
```

- [ ] **Step 2: Verify it compiles**

```bash
cd /Users/srinivaasant/YODA/YODA-BB/teams-meeting-assistant/browser-bot
npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add src/utils/logger.ts
git commit -m "feat: add Winston structured JSON logger"
```

---

### Task 3: Create Prometheus metrics

**Files:**
- Create: `src/utils/metrics.ts`

- [ ] **Step 1: Create the metrics module**

```typescript
// src/utils/metrics.ts
import { Counter, Gauge, Histogram, Registry } from "prom-client";

export const registry = new Registry();

export const meetingsActive = new Gauge({
  name: "browser_bot_meetings_active",
  help: "Number of active meetings",
  registers: [registry],
});

export const transcriptSegmentsTotal = new Counter({
  name: "browser_bot_transcript_segments_total",
  help: "Total transcript segments sent to backend",
  labelNames: ["source"] as const,
  registers: [registry],
});

export const audioSilenceAlertsTotal = new Counter({
  name: "browser_bot_audio_silence_alerts_total",
  help: "Audio silence alerts triggered",
  registers: [registry],
});

export const joinDurationSeconds = new Histogram({
  name: "browser_bot_join_duration_seconds",
  help: "Time to join a meeting in seconds",
  buckets: [5, 10, 30, 60, 120, 180],
  registers: [registry],
});

export const browserMemoryMB = new Gauge({
  name: "browser_bot_browser_memory_mb",
  help: "Browser process memory usage in MB",
  registers: [registry],
});

export const errorsTotal = new Counter({
  name: "browser_bot_errors_total",
  help: "Total errors by type",
  labelNames: ["type"] as const,
  registers: [registry],
});
```

- [ ] **Step 2: Verify it compiles**

```bash
npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add src/utils/metrics.ts
git commit -m "feat: add Prometheus metrics definitions"
```

---

### Task 4: Add `source` field to Python backend schema and model

**Files:**
- Modify: `YODA-BB/services/meeting-service/src/meeting_service/schemas/bot_events.py:11-19`
- Modify: `YODA-BB/foundation/src/yoda_foundation/models/transcript.py:18-53`
- Modify: `YODA-BB/services/meeting-service/src/meeting_service/routes/bot_events.py:74-86`

- [ ] **Step 1: Add `source` to TranscriptSegmentIn schema**

In `YODA-BB/services/meeting-service/src/meeting_service/schemas/bot_events.py`, add to the `TranscriptSegmentIn` class after line 19 (`is_final: bool = True`):

```python
    source: str | None = Field(default=None, max_length=10)  # "caption" or "audio"
```

- [ ] **Step 2: Add `source` column to TranscriptSegment model**

In `YODA-BB/foundation/src/yoda_foundation/models/transcript.py`, add after line 49 (`String, nullable=True, default="en-US"`/closing paren):

```python
    source: Mapped[str | None] = mapped_column(String(10), nullable=True)
```

- [ ] **Step 3: Pass `source` when creating TranscriptSegment in bot_events route**

In `YODA-BB/services/meeting-service/src/meeting_service/routes/bot_events.py`, in the `ingest_transcript` function around line 75, modify the `TranscriptSegment(...)` constructor to include `source`:

Change:
```python
                    db.add(
                        TranscriptSegment(
                            meeting_id=meeting_uuid,
                            speaker_name=seg.speaker_name,
                            speaker_id=seg.speaker_id or None,
                            text=seg.text,
                            start_time=seg.start_time_sec,
                            end_time=seg.end_time_sec,
                            confidence=seg.confidence,
                            sequence_number=seg.sequence,
                        )
                    )
```

To:
```python
                    db.add(
                        TranscriptSegment(
                            meeting_id=meeting_uuid,
                            speaker_name=seg.speaker_name,
                            speaker_id=seg.speaker_id or None,
                            text=seg.text,
                            start_time=seg.start_time_sec,
                            end_time=seg.end_time_sec,
                            confidence=seg.confidence,
                            sequence_number=seg.sequence,
                            source=seg.source,
                        )
                    )
```

- [ ] **Step 4: Create Alembic migration**

```bash
cd /Users/srinivaasant/YODA/YODA-BB
alembic revision --autogenerate -m "add source column to transcript_segments"
```

Review the generated migration to ensure it only adds the `source` column.

- [ ] **Step 5: Commit**

```bash
git add foundation/src/yoda_foundation/models/transcript.py \
       services/meeting-service/src/meeting_service/schemas/bot_events.py \
       services/meeting-service/src/meeting_service/routes/bot_events.py \
       alembic/versions/
git commit -m "feat: add source field to transcript segments (caption/audio)"
```

---

### Task 5: Add HMAC nonce replay protection

**Files:**
- Modify: `YODA-BB/services/meeting-service/src/meeting_service/utils/hmac_auth.py`

- [ ] **Step 1: Add nonce validation to hmac_auth.py**

Replace the entire file content of `YODA-BB/services/meeting-service/src/meeting_service/utils/hmac_auth.py` with:

```python
"""HMAC-SHA256 request validation for inter-service communication."""

from __future__ import annotations

import hashlib
import hmac
import logging
import time

from cachetools import TTLCache
from fastapi import HTTPException, Request

from meeting_service.config import Settings

logger = logging.getLogger(__name__)

# Maximum allowed clock drift between services (seconds)
_MAX_TIMESTAMP_DRIFT = 60

# Nonce cache: stores seen nonces for TTL seconds to prevent replay attacks.
# maxsize=10000 handles ~167 requests/sec within the 60s window.
_seen_nonces: TTLCache[str, bool] = TTLCache(maxsize=10_000, ttl=_MAX_TIMESTAMP_DRIFT)


async def validate_hmac(request: Request, settings: Settings) -> None:
    """Validate HMAC signature on incoming requests from the Browser Bot.

    Raises HTTPException(401) on validation failure.
    Skips validation entirely if INTER_SERVICE_HMAC_KEY is not configured (dev mode).
    """
    if not settings.INTER_SERVICE_HMAC_KEY:
        if getattr(settings, "DEBUG", False) is False:
            logger.warning(
                "HMAC validation skipped — INTER_SERVICE_HMAC_KEY not set. "
                "This is acceptable only in development."
            )
        return

    timestamp = request.headers.get("X-Request-Timestamp", "")
    signature = request.headers.get("X-Request-Signature", "")
    nonce = request.headers.get("X-Request-Nonce", "")
    if not timestamp or not signature:
        logger.warning(
            "HMAC validation failed: missing headers for %s %s",
            request.method,
            request.url.path,
        )
        raise HTTPException(status_code=401, detail="Missing HMAC headers")

    try:
        ts = int(timestamp)
    except ValueError as exc:
        logger.warning("HMAC validation failed: non-integer timestamp")
        raise HTTPException(status_code=401, detail="Invalid timestamp") from exc

    drift = abs(time.time() - ts)
    if drift > _MAX_TIMESTAMP_DRIFT:
        logger.warning(
            "HMAC validation failed: timestamp drift %.0fs exceeds %ds for %s %s",
            drift,
            _MAX_TIMESTAMP_DRIFT,
            request.method,
            request.url.path,
        )
        raise HTTPException(status_code=401, detail="Request expired")

    # Nonce replay protection — reject if we've seen this nonce before
    if nonce:
        if nonce in _seen_nonces:
            logger.warning(
                "HMAC validation failed: replayed nonce for %s %s",
                request.method,
                request.url.path,
            )
            raise HTTPException(status_code=401, detail="Replayed request")
        _seen_nonces[nonce] = True

    body = await request.body()
    body_hash = hashlib.sha256(body).hexdigest()
    method = request.method
    path = request.url.path
    # Include nonce in payload if present (backwards compatible)
    payload = f"{timestamp}{nonce}{method}{path}{body_hash}"

    expected = hmac.new(
        settings.INTER_SERVICE_HMAC_KEY.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()

    # Use constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(signature, expected):
        logger.warning(
            "HMAC validation failed: invalid signature for %s %s",
            request.method,
            request.url.path,
        )
        raise HTTPException(status_code=401, detail="Invalid signature")
```

- [ ] **Step 2: Update TypeScript HMAC signing to include nonce**

In `YODA-BB/teams-meeting-assistant/browser-bot/src/services/python-backend.ts`, modify the `post` method (around lines 63-74). Change the HMAC signing block from:

```typescript
    if (this.hmacSecret) {
      const timestamp = Math.floor(Date.now() / 1000).toString();
      const bodyHash = crypto.createHash("sha256").update(bodyStr).digest("hex");
      const payload = `${timestamp}POST${path}${bodyHash}`;
      const signature = crypto
        .createHmac("sha256", this.hmacSecret)
        .update(payload)
        .digest("hex");

      headers["X-Request-Timestamp"] = timestamp;
      headers["X-Request-Signature"] = signature;
    }
```

To:

```typescript
    if (this.hmacSecret) {
      const timestamp = Math.floor(Date.now() / 1000).toString();
      const nonce = crypto.randomUUID();
      const bodyHash = crypto.createHash("sha256").update(bodyStr).digest("hex");
      const payload = `${timestamp}${nonce}POST${path}${bodyHash}`;
      const signature = crypto
        .createHmac("sha256", this.hmacSecret)
        .update(payload)
        .digest("hex");

      headers["X-Request-Timestamp"] = timestamp;
      headers["X-Request-Nonce"] = nonce;
      headers["X-Request-Signature"] = signature;
    }
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd /Users/srinivaasant/YODA/YODA-BB/teams-meeting-assistant/browser-bot
npx tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
cd /Users/srinivaasant/YODA/YODA-BB
git add services/meeting-service/src/meeting_service/utils/hmac_auth.py \
       teams-meeting-assistant/browser-bot/src/services/python-backend.ts
git commit -m "fix: add nonce-based HMAC replay protection"
```

---

### Task 6: Add `source` field to TypeScript TranscriptSegment and update transcription service

**Files:**
- Modify: `src/services/python-backend.ts:117-127`
- Modify: `src/services/transcription.ts`

- [ ] **Step 1: Add `source` to TypeScript TranscriptSegment interface**

In `src/services/python-backend.ts`, change the `TranscriptSegment` interface (lines 117-127) from:

```typescript
export interface TranscriptSegment {
  sequence: number;
  speakerId: string;
  speakerName: string;
  text: string;
  startTimeSec: number;
  endTimeSec: number;
  confidence: number;
  isFinal: boolean;
}
```

To:

```typescript
export interface TranscriptSegment {
  sequence: number;
  speakerId: string;
  speakerName: string;
  text: string;
  startTimeSec: number;
  endTimeSec: number;
  confidence: number;
  isFinal: boolean;
  source: "caption" | "audio";
}
```

- [ ] **Step 2: Add `source` to sendTranscriptChunk payload**

In `src/services/python-backend.ts`, in the `sendTranscriptChunk` method (around line 24-34), add `source` to the segment mapping:

Change:
```typescript
        is_final: s.isFinal,
      })),
```

To:
```typescript
        is_final: s.isFinal,
        source: s.source,
      })),
```

- [ ] **Step 3: Update TranscriptionService with dual sequence counters and captionActive flag**

In `src/services/transcription.ts`, make these changes:

**Add caption sequence counter and captionActive flag** after line 15 (`private sequenceNumber = 0;`):

```typescript
  private captionSequenceNumber = 0;
  captionActive = false;
```

**Change the existing `sequenceNumber` starting value** (line 15) from:
```typescript
  private sequenceNumber = 0;
```
To:
```typescript
  private sequenceNumber = 100_000;
```

**Add `source: "audio"` to the existing `emitSegment` method** (around line 188). Change:
```typescript
    const segment: TranscriptSegment = {
      sequence: this.sequenceNumber++,
      speakerId: resolvedSpeakerId,
      speakerName: resolvedSpeakerName,
      text: text.trim(),
      startTimeSec: Math.max(0, Date.now() / 1000 - durationSec),
      endTimeSec: Date.now() / 1000,
      confidence: 0.9,
      isFinal,
    };
```

To:
```typescript
    const segment: TranscriptSegment = {
      sequence: this.sequenceNumber++,
      speakerId: resolvedSpeakerId,
      speakerName: resolvedSpeakerName,
      text: text.trim(),
      startTimeSec: Math.max(0, Date.now() / 1000 - durationSec),
      endTimeSec: Date.now() / 1000,
      confidence: 0.9,
      isFinal,
      source: "audio",
    };
```

**Add the new `pushCaptionSegment` method** after the `setActiveSpeaker` method (after line 175):

```typescript
  pushCaptionSegment(speaker: string, text: string): void {
    if (!this.running) return;

    const segment: TranscriptSegment = {
      sequence: this.captionSequenceNumber++,
      speakerId: speaker.toLowerCase().replace(/\s+/g, "-"),
      speakerName: speaker,
      text: text.trim(),
      startTimeSec: Date.now() / 1000,
      endTimeSec: Date.now() / 1000,
      confidence: 1.0,
      isFinal: true,
      source: "caption",
    };

    this.backend
      .sendTranscriptChunk(this.meetingId, [segment])
      .catch((err) => {
        console.error(`[${this.meetingId}] Failed to send caption transcript:`, err.message);
      });
  }
```

- [ ] **Step 4: Verify it compiles**

```bash
cd /Users/srinivaasant/YODA/YODA-BB/teams-meeting-assistant/browser-bot
npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 5: Commit**

```bash
git add src/services/python-backend.ts src/services/transcription.ts
git commit -m "feat: add source field and dual caption/audio sequence counters"
```

---

### Task 7: Create caption-capture.ts

**Files:**
- Create: `src/platforms/msteams/caption-capture.ts`

- [ ] **Step 1: Create the caption capture module**

```typescript
// src/platforms/msteams/caption-capture.ts
import { Page } from "playwright";
import { logger } from "../../utils/logger.js";

export interface CaptionSegment {
  speaker: string;
  text: string;
  timestamp: number;
}

export interface CaptionStream {
  readonly isActive: boolean;
  onSegment(cb: (seg: CaptionSegment) => void): void;
  stop(): Promise<void>;
}

/**
 * Enables Teams live captions and scrapes speaker + text from the caption DOM.
 *
 * Teams renders captions in a container with speaker name and text elements.
 * Text updates in-place (partial → final). We debounce 500ms to detect finalization.
 * Segments are delivered to Node.js via page.exposeFunction (same pattern as audio capture).
 *
 * If captions are unavailable (admin disabled, no CC button), isActive will be false
 * and the audio pipeline should be used as the sole transcription source.
 */
export async function startCaptionCapture(page: Page): Promise<CaptionStream> {
  let callbacks: ((seg: CaptionSegment) => void)[] = [];
  let active = false;
  let stopped = false;
  let healthTimer: ReturnType<typeof setInterval> | null = null;
  let lastSegmentAt = 0;

  // Step 1: Expose callback BEFORE injecting in-page code
  await page.exposeFunction(
    "__yodaOnCaption",
    (speaker: string, text: string, timestamp: number) => {
      if (stopped) return;
      lastSegmentAt = Date.now();
      const seg: CaptionSegment = { speaker, text, timestamp };
      for (const cb of callbacks) {
        cb(seg);
      }
    }
  );

  // Expose health status callback
  await page.exposeFunction("__yodaOnCaptionHealth", (status: string) => {
    if (status === "active") {
      active = true;
    } else if (status === "unavailable") {
      active = false;
      logger.warn("Captions unavailable — audio pipeline is primary");
    }
  });

  // Step 2: Enable captions and set up observation
  await page.evaluate(() => {
    const CAPTION_CONTAINER_SELECTORS = [
      '[data-tid="closed-caption-text"]',
      '[data-tid="caption-container"]',
      "#annotationContainer",
      ".ts-captions-container",
      '[role="log"][aria-label*="caption" i]',
    ];

    const CC_BUTTON_SELECTORS = [
      '[data-tid="toggle-captions-button"]',
      'button[aria-label*="caption" i]',
      'button[aria-label*="subtitle" i]',
      'button[aria-label*="closed caption" i]',
    ];

    // Track finalization state per caption element
    const pendingCaptions = new Map<
      string,
      { speaker: string; text: string; timerId: ReturnType<typeof setTimeout> }
    >();
    const FINALIZATION_DEBOUNCE_MS = 500;
    let captionIdCounter = 0;

    function findCaptionContainer(): Element | null {
      for (const sel of CAPTION_CONTAINER_SELECTORS) {
        const el = document.querySelector(sel);
        if (el) return el;
      }
      return null;
    }

    function extractSpeakerAndText(
      node: Element
    ): { speaker: string; text: string } | null {
      // Strategy 1: Separate speaker name and text elements
      const speakerEl =
        node.querySelector(".caption-speaker-name") ||
        node.querySelector('[data-tid="caption-speaker"]') ||
        node.querySelector('[class*="speakerName"]');
      const textEl =
        node.querySelector(".caption-text") ||
        node.querySelector('[data-tid="caption-text"]') ||
        node.querySelector('[class*="captionText"]');

      if (speakerEl && textEl) {
        return {
          speaker: speakerEl.textContent?.trim() || "Unknown",
          text: textEl.textContent?.trim() || "",
        };
      }

      // Strategy 2: Single element with "Speaker: text" format
      const fullText = node.textContent?.trim() || "";
      const colonIdx = fullText.indexOf(":");
      if (colonIdx > 0 && colonIdx < 60) {
        return {
          speaker: fullText.substring(0, colonIdx).trim(),
          text: fullText.substring(colonIdx + 1).trim(),
        };
      }

      // Strategy 3: Just text, no speaker
      if (fullText.length > 0) {
        return { speaker: "Unknown", text: fullText };
      }

      return null;
    }

    function handleCaptionUpdate(nodeKey: string, speaker: string, text: string) {
      if (!text) return;

      const existing = pendingCaptions.get(nodeKey);
      if (existing) {
        clearTimeout(existing.timerId);
      }

      const timerId = setTimeout(() => {
        // Text hasn't changed for 500ms — consider it finalized
        pendingCaptions.delete(nodeKey);
        (window as any).__yodaOnCaption(speaker, text, Date.now());
      }, FINALIZATION_DEBOUNCE_MS);

      pendingCaptions.set(nodeKey, { speaker, text, timerId });
    }

    function observeCaptions(container: Element) {
      (window as any).__yodaOnCaptionHealth("active");
      console.log("[YodaBot] Caption observation started");

      const observer = new MutationObserver(() => {
        // Scan all child nodes for caption content
        const captionNodes = container.children;
        for (let i = 0; i < captionNodes.length; i++) {
          const node = captionNodes[i];
          const nodeKey =
            node.getAttribute("data-caption-id") ||
            node.getAttribute("data-tid") ||
            `caption-${i}`;

          const extracted = extractSpeakerAndText(node);
          if (extracted && extracted.text) {
            handleCaptionUpdate(nodeKey, extracted.speaker, extracted.text);
          }
        }
      });

      observer.observe(container, {
        childList: true,
        subtree: true,
        characterData: true,
      });

      (window as any).__captionObserver = observer;
      (window as any).__captionPending = pendingCaptions;
    }

    // --- Enable captions ---
    async function enableCaptions(): Promise<boolean> {
      // Try keyboard shortcut first
      document.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "U",
          code: "KeyU",
          ctrlKey: true,
          shiftKey: true,
          bubbles: true,
        })
      );

      // Wait for caption container to appear
      for (let attempt = 0; attempt < 3; attempt++) {
        await new Promise((r) => setTimeout(r, attempt === 0 ? 3000 : 5000));
        const container = findCaptionContainer();
        if (container) {
          observeCaptions(container);
          return true;
        }

        // Try clicking CC button if keyboard shortcut didn't work
        if (attempt === 0) {
          for (const sel of CC_BUTTON_SELECTORS) {
            const btn = document.querySelector(sel);
            if (btn instanceof HTMLElement) {
              btn.click();
              console.log(`[YodaBot] Clicked CC button: ${sel}`);
              break;
            }
          }
        }
      }

      // Captions unavailable
      (window as any).__yodaOnCaptionHealth("unavailable");
      return false;
    }

    enableCaptions();
  });

  // Wait a moment for the in-page enableCaptions() to run
  await page.waitForTimeout(5000);

  // Step 3: Health monitoring — detect when captions go silent
  healthTimer = setInterval(() => {
    if (!active || stopped) return;
    const silenceSec = (Date.now() - lastSegmentAt) / 1000;
    if (lastSegmentAt > 0 && silenceSec > 60) {
      logger.warn("Caption pipeline silent for >60s — may have failed", {
        silenceSeconds: Math.round(silenceSec),
      });
      active = false;
    } else if (lastSegmentAt > 0 && silenceSec > 30) {
      logger.warn("Caption pipeline silent for >30s", {
        silenceSeconds: Math.round(silenceSec),
      });
    }
  }, 10_000);

  return {
    get isActive() {
      return active;
    },
    onSegment(cb: (seg: CaptionSegment) => void) {
      callbacks.push(cb);
    },
    async stop() {
      stopped = true;
      callbacks.length = 0;
      if (healthTimer) {
        clearInterval(healthTimer);
        healthTimer = null;
      }
      await page
        .evaluate(() => {
          const observer = (window as any).__captionObserver;
          if (observer) {
            observer.disconnect();
            (window as any).__captionObserver = null;
          }
          // Clear pending debounce timers
          const pending = (window as any).__captionPending as
            | Map<string, { timerId: ReturnType<typeof setTimeout> }>
            | undefined;
          if (pending) {
            for (const entry of pending.values()) {
              clearTimeout(entry.timerId);
            }
            pending.clear();
            (window as any).__captionPending = null;
          }
        })
        .catch(() => {});
    },
  };
}
```

- [ ] **Step 2: Verify it compiles**

```bash
cd /Users/srinivaasant/YODA/YODA-BB/teams-meeting-assistant/browser-bot
npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add src/platforms/msteams/caption-capture.ts
git commit -m "feat: add caption-based transcription pipeline"
```

---

### Task 8: Wire caption capture into bot-manager and add browser restart policy

**Files:**
- Modify: `src/services/bot-manager.ts`

- [ ] **Step 1: Add imports**

At the top of `bot-manager.ts`, add after existing imports (line 8):

```typescript
import { startCaptionCapture, CaptionStream } from "../platforms/msteams/caption-capture.js";
import { logger } from "../utils/logger.js";
import { meetingsActive, joinDurationSeconds, errorsTotal } from "../utils/metrics.js";
```

- [ ] **Step 2: Add CaptionStream to ActiveMeeting interface**

In the `ActiveMeeting` interface (line 16-26), add after `stopParticipantMonitor`:

```typescript
  captionStream: CaptionStream | null;
```

- [ ] **Step 3: Add browser restart tracking fields**

In the `BotManager` class, after `private meetings = new Map<string, ActiveMeeting>();` (line 33), add:

```typescript
  private browserCreatedAt = 0;
  private meetingsSinceBrowserLaunch = 0;
```

- [ ] **Step 4: Add browser restart logic to ensureBrowser()**

At the top of `ensureBrowser()` (line 47), before the `if (!this.browser ...)` check, add:

```typescript
    const MAX_BROWSER_AGE_MS = 4 * 60 * 60 * 1000;
    const MAX_MEETINGS_PER_BROWSER = 50;

    if (
      this.browser?.isConnected() &&
      this.meetings.size === 0 &&
      (Date.now() - this.browserCreatedAt > MAX_BROWSER_AGE_MS ||
        this.meetingsSinceBrowserLaunch >= MAX_MEETINGS_PER_BROWSER)
    ) {
      logger.info("Restarting browser for memory hygiene", {
        ageMinutes: Math.round((Date.now() - this.browserCreatedAt) / 60000),
        meetingsServed: this.meetingsSinceBrowserLaunch,
      });
      await this.browser.close().catch(() => {});
      this.browser = null;
    }
```

Inside the existing `if (!this.browser ...)` block, after `this.browser = await chromium.launch(...)`, add:

```typescript
      this.browserCreatedAt = Date.now();
      this.meetingsSinceBrowserLaunch = 0;
```

- [ ] **Step 5: Wire caption capture in joinMeeting()**

In `joinMeeting()`, after the speaker detection block (after line 216 `});`), add:

```typescript
      // Step 5b: Start caption capture
      let captionStream: CaptionStream | null = null;
      try {
        logger.info("Starting caption capture", { meetingId });
        captionStream = await startCaptionCapture(page);
        if (captionStream.isActive) {
          transcription.captionActive = true;
          captionStream.onSegment((seg) => {
            transcription.pushCaptionSegment(seg.speaker, seg.text);
          });
          logger.info("Caption capture active", { meetingId });
        } else {
          logger.warn("Captions unavailable — using audio-only", { meetingId });
        }
      } catch (err: any) {
        logger.error("Caption capture failed (non-fatal)", {
          meetingId,
          error: err.message,
        });
        errorsTotal.inc({ type: "caption_capture" });
      }
```

- [ ] **Step 6: Add captionStream to cleanup and ActiveMeeting storage**

In the cleanup function (around line 237), add before `stopSpeakerDetection()`:

```typescript
          if (captionStream) await captionStream.stop();
```

In the `this.meetings.set(...)` call (around line 266), add:

```typescript
        captionStream,
```

Also add after the `this.meetings.set(...)` call:

```typescript
      meetingsActive.set(this.meetings.size);
      this.meetingsSinceBrowserLaunch++;
```

In the cleanup function, after `this.meetings.delete(meetingId);` add:

```typescript
          meetingsActive.set(this.meetings.size);
```

- [ ] **Step 7: Verify it compiles**

```bash
npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 8: Commit**

```bash
git add src/services/bot-manager.ts
git commit -m "feat: wire caption capture, browser restart policy, and metrics"
```

---

### Task 9: Add continuous audio silence detection

**Files:**
- Modify: `src/platforms/msteams/audio-capture.ts`

- [ ] **Step 1: Add silence detection callback exposure**

In `startAudioCapture()`, after the existing `page.exposeFunction("__yodaOnAudioData", ...)` call (around line 66), add:

```typescript
  await page.exposeFunction("__yodaOnAudioSilence", (silenceSeconds: number) => {
    if (stopped) return;
    // Will be wired to logger/metrics by bot-manager
    for (const cb of silenceCallbacks) {
      cb(silenceSeconds);
    }
  });
```

Add `silenceCallbacks` array at the top of the function alongside `callbacks`:

```typescript
  let silenceCallbacks: ((silenceSeconds: number) => void)[] = [];
```

- [ ] **Step 2: Inject silence monitoring into the page**

Inside the existing `page.evaluate(...)` block, after the 5-second diagnostic `setTimeout` (around line 287), add:

```typescript
    // Continuous silence monitoring (every 10 seconds)
    let lastNonSilentAt = Date.now();
    const SILENCE_CHECK_INTERVAL_MS = 10_000;
    const SILENCE_WARN_THRESHOLD_S = 30;

    const silenceCheckId = setInterval(() => {
      if (!sharedCtx || sharedCtx.state === "closed") return;
      try {
        const analyser = sharedCtx.createAnalyser();
        analyser.fftSize = 256;
        // Connect all live RTC audio sources
        const allAudios = document.querySelectorAll<HTMLAudioElement>("audio[data-rtc-track]");
        let connected = false;
        allAudios.forEach((audio) => {
          if (audio.srcObject) {
            const stream = audio.srcObject as MediaStream;
            const liveTracks = stream.getAudioTracks().filter((t) => t.readyState === "live");
            if (liveTracks.length > 0) {
              try {
                const src = sharedCtx!.createMediaStreamSource(new MediaStream(liveTracks));
                src.connect(analyser);
                connected = true;
              } catch {
                /* ignore duplicate */
              }
            }
          }
        });

        if (!connected) {
          analyser.disconnect();
          return;
        }

        const data = new Float32Array(analyser.fftSize);
        analyser.getFloatTimeDomainData(data);
        let rms = 0;
        for (let i = 0; i < data.length; i++) {
          rms += data[i] * data[i];
        }
        rms = Math.sqrt(rms / data.length);
        analyser.disconnect();

        if (rms > 0.0001) {
          lastNonSilentAt = Date.now();
        } else {
          const silenceSec = (Date.now() - lastNonSilentAt) / 1000;
          if (silenceSec >= SILENCE_WARN_THRESHOLD_S) {
            (window as any).__yodaOnAudioSilence(Math.round(silenceSec));
          }
        }
      } catch {
        /* analyser may fail if context closed */
      }
    }, SILENCE_CHECK_INTERVAL_MS);

    (window as any).__silenceCheckId = silenceCheckId;
```

- [ ] **Step 3: Add cleanup for silence monitoring**

In the `stop()` function's `page.evaluate` block (around line 314), add before the `// Clear remaining references` comment:

```typescript
          // Clear silence monitoring
          if ((window as any).__silenceCheckId) {
            clearInterval((window as any).__silenceCheckId);
            (window as any).__silenceCheckId = null;
          }
```

- [ ] **Step 4: Add `onSilence` to the returned AudioStream interface**

Change the returned object to include the silence callback:

Add to the `AudioStream` interface at the top of the file (around line 4):

```typescript
  onSilence(callback: (silenceSeconds: number) => void): void;
```

Add to the return object (after `onAudioData`):

```typescript
    onSilence(callback: (silenceSeconds: number) => void) {
      silenceCallbacks.push(callback);
    },
```

- [ ] **Step 5: Verify it compiles**

```bash
npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 6: Commit**

```bash
git add src/platforms/msteams/audio-capture.ts
git commit -m "feat: add continuous audio silence detection"
```

---

### Task 10: Add /health/ready, /metrics endpoints and replace console.log in index.ts

**Files:**
- Modify: `src/index.ts`

- [ ] **Step 1: Add imports**

At the top of `index.ts`, add after existing imports:

```typescript
import { logger } from "./utils/logger.js";
import { registry, meetingsActive, browserMemoryMB } from "./utils/metrics.js";
```

- [ ] **Step 2: Add /metrics endpoint**

After the `/health/live` endpoint (around line 139), add:

```typescript
// Prometheus metrics (no auth — standard for scraping behind firewall)
app.get("/metrics", async (_req, res) => {
  try {
    res.set("Content-Type", registry.contentType);
    res.send(await registry.metrics());
  } catch {
    res.status(500).json({ error: "Metrics unavailable" });
  }
});
```

- [ ] **Step 3: Add /health/ready endpoint**

After the `/metrics` endpoint, add:

```typescript
// Deep health check (auth-protected)
app.get("/health/ready", authenticateRequest, (_req, res) => {
  const active = botManager.activeMeetingCount;
  const capacity = botManager.canAccept;

  let status: "ok" | "degraded" | "unhealthy" = "ok";
  if (active === 0 && !capacity) {
    status = "unhealthy";
  }

  res.json({
    status,
    meetings: {
      active,
      canAccept: capacity,
    },
    uptime: Math.round(process.uptime()),
    memoryMB: Math.round(process.memoryUsage().rss / 1024 / 1024),
  });
});
```

- [ ] **Step 4: Replace all console.log/error/warn in index.ts**

Replace throughout `index.ts`:
- `console.error("FATAL:` → `logger.error(`
- `console.error(\`Failed to join` → `logger.error(`
- `console.error(\`Failed to leave` → `logger.error(`
- `console.error("Unhandled error:"` → `logger.error("Unhandled error",`
- `console.error("Unhandled rejection:"` → `logger.error("Unhandled rejection",`
- `console.log(\`${signal}` → `logger.info(\`${signal}`
- `console.log(\`Browser bot listening` → `logger.info(\`Browser bot listening`
- `console.log(\`Environment:` → `logger.info("Server started",`
- `console.log(\`Auth:` → (merge into the "Server started" log)

- [ ] **Step 5: Verify it compiles**

```bash
npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 6: Commit**

```bash
git add src/index.ts
git commit -m "feat: add /health/ready, /metrics endpoints and structured logging"
```

---

### Task 11: Replace console.log in join.ts, speaker-detection.ts, bot-manager.ts

**Files:**
- Modify: `src/platforms/msteams/join.ts`
- Modify: `src/platforms/msteams/speaker-detection.ts`
- Modify: `src/services/bot-manager.ts`

- [ ] **Step 1: Add logger import to join.ts**

At the top of `join.ts`, add:

```typescript
import { logger } from "../../utils/logger.js";
```

Replace all `console.log(` with `logger.info(` and `console.warn(` with `logger.warn(` and `console.error(` with `logger.error(` throughout the file. Keep the in-browser `console.log("[YodaBot]...")` calls as-is — those run inside the browser context and can't use Winston.

- [ ] **Step 2: Add logger import to speaker-detection.ts**

At the top of `speaker-detection.ts`, add:

```typescript
import { logger } from "../../utils/logger.js";
```

Replace `console.error("Failed to inject speaker detection:"` with `logger.error("Failed to inject speaker detection",`. Keep in-browser `console.log("[YodaBot]")` calls as-is.

- [ ] **Step 3: Replace remaining console.log in bot-manager.ts**

Logger import was already added in Task 8. Replace all remaining `console.log` and `console.error` calls with `logger.info` / `logger.error` / `logger.warn`. Keep in-browser `console.log("[YodaBot]")` calls as-is.

- [ ] **Step 4: Verify it compiles**

```bash
npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 5: Commit**

```bash
git add src/platforms/msteams/join.ts \
       src/platforms/msteams/speaker-detection.ts \
       src/services/bot-manager.ts
git commit -m "refactor: replace console.log with structured Winston logger"
```

---

### Task 12: Wire audio silence alerts to logger and metrics in bot-manager

**Files:**
- Modify: `src/services/bot-manager.ts`

- [ ] **Step 1: Wire onSilence callback**

In `joinMeeting()`, after the `audioStream.onAudioData(...)` call (around line 207), add:

```typescript
      audioStream.onSilence((silenceSeconds: number) => {
        logger.warn("Audio silence detected", { meetingId, silenceSeconds });
        audioSilenceAlertsTotal.inc();
        if (silenceSeconds >= 120) {
          logger.error("Audio pipeline likely broken — silence >120s", {
            meetingId,
            silenceSeconds,
          });
          errorsTotal.inc({ type: "audio_silence" });
        }
      });
```

Also add the import for `audioSilenceAlertsTotal` — update the existing metrics import line to:

```typescript
import { meetingsActive, joinDurationSeconds, errorsTotal, audioSilenceAlertsTotal } from "../utils/metrics.js";
```

- [ ] **Step 2: Add join duration timing**

In `joinMeeting()`, at the start of the method (line 152), add:

```typescript
    const joinStartedAt = Date.now();
```

After `joinTeamsMeeting(page, joinUrl, this.config.botName);` succeeds (around line 194), add:

```typescript
      joinDurationSeconds.observe((Date.now() - joinStartedAt) / 1000);
```

- [ ] **Step 3: Verify it compiles**

```bash
npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 4: Commit**

```bash
git add src/services/bot-manager.ts
git commit -m "feat: wire silence alerts, join duration metrics"
```

---

### Task 13: Full build and startup verification

**Files:** All modified files

- [ ] **Step 1: Full TypeScript build**

```bash
cd /Users/srinivaasant/YODA/YODA-BB/teams-meeting-assistant/browser-bot
npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 2: Build dist**

```bash
npm run build
```

Expected: `dist/` directory created with compiled JS.

- [ ] **Step 3: Verify startup**

```bash
NODE_ENV=development node dist/index.js &
sleep 2
curl -s http://localhost:3001/health/live
curl -s http://localhost:3001/metrics | head -5
kill %1
```

Expected:
- `/health/live` returns `{"status":"ok"}`
- `/metrics` returns Prometheus-format metrics text

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: dual-mode caption+audio transcription and 6 gap fixes — build verified"
```

---

## Summary

| Task | Description | Est. |
|------|------------|------|
| 1 | Add npm dependencies | 2 min |
| 2 | Create structured logger | 3 min |
| 3 | Create Prometheus metrics | 3 min |
| 4 | Python backend: source field + migration | 5 min |
| 5 | HMAC nonce replay protection (TS + Python) | 5 min |
| 6 | TypeScript source field + dual sequence counters | 5 min |
| 7 | Create caption-capture.ts | 10 min |
| 8 | Wire caption into bot-manager + browser restart | 10 min |
| 9 | Audio silence detection | 5 min |
| 10 | /health/ready + /metrics + logger in index.ts | 5 min |
| 11 | Replace console.log in remaining files | 5 min |
| 12 | Wire silence alerts + join timing metrics | 3 min |
| 13 | Full build + startup verification | 3 min |

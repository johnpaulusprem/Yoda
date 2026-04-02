# AudioWorklet Migration & Audio Capture Refactor

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace deprecated ScriptProcessorNode with AudioWorkletNode for reliable, thread-isolated audio capture that won't drop frames under heavy Teams UI load.

**Architecture:** The AudioWorklet processor runs on a dedicated audio rendering thread, completely decoupled from the main thread. Audio data flows: `RTCPeerConnection track -> AudioContext -> AudioWorkletNode -> MessagePort -> window.__audioChunks`. The processor code is injected as a Blob URL (no external file serving needed inside Playwright's page.evaluate). Resampling from native sample rate to 16kHz stays in the worklet thread for zero main-thread overhead.

**Tech Stack:** Web Audio API (AudioWorklet, AudioWorkletProcessor), Playwright page.evaluate/addInitScript, Blob URLs for inline module loading.

---

### Task 1: Create AudioWorklet processor as inline Blob module

**Files:**
- Modify: `src/platforms/msteams/audio-capture.ts`

**Step 1: Define the processor source code as a string constant**

Add this at the top of `audio-capture.ts`, below the imports. This is the AudioWorkletProcessor code that will run on the audio thread. It captures 128-sample frames, resamples to 16kHz, and posts Float32Array data to the main thread via MessagePort.

```typescript
const WORKLET_PROCESSOR_CODE = `
class AudioCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.active = true;
    this.port.onmessage = (e) => {
      if (e.data === 'stop') this.active = false;
    };
  }

  process(inputs, outputs, parameters) {
    if (!this.active) return false;
    const input = inputs[0];
    if (!input || !input[0] || input[0].length === 0) return true;

    const channelData = input[0]; // mono channel
    const inputRate = sampleRate; // global in AudioWorkletGlobalScope
    const targetRate = 16000;
    const ratio = inputRate / targetRate;
    const outputLength = Math.floor(channelData.length / ratio);

    if (outputLength === 0) return true;

    const output = new Float32Array(outputLength);
    for (let i = 0; i < outputLength; i++) {
      const srcIdx = i * ratio;
      const low = Math.floor(srcIdx);
      const high = Math.min(low + 1, channelData.length - 1);
      const frac = srcIdx - low;
      output[i] = channelData[low] * (1 - frac) + channelData[high] * frac;
    }

    this.port.postMessage(output, [output.buffer]);
    return true;
  }
}

registerProcessor('audio-capture-processor', AudioCaptureProcessor);
`;
```

**Step 2: Verify it compiles**

Run: `export PATH="$PATH:/c/Program Files/nodejs" && cd F:/Yoda/yoda-bb/teams-meeting-assistant/browser-bot && npx tsc --noEmit`
Expected: No errors (this is just a string constant)

**Step 3: Commit**

```bash
git add src/platforms/msteams/audio-capture.ts
git commit -m "refactor: add AudioWorklet processor source as inline constant"
```

---

### Task 2: Rewrite captureAudioElement to use AudioWorkletNode

**Files:**
- Modify: `src/platforms/msteams/audio-capture.ts`

**Step 1: Replace the page.evaluate block**

Replace the entire `page.evaluate(() => { ... })` block (lines 18-100) with the new AudioWorklet-based implementation. The key changes:

1. Create a Blob URL from the processor string and register it via `audioContext.audioWorklet.addModule(blobUrl)`
2. Replace `createScriptProcessor` with `new AudioWorkletNode`
3. Use `workletNode.port.onmessage` to receive PCM data on the main thread
4. Keep the same `window.__audioChunks` interface so the polling code in Node.js doesn't change

```typescript
export async function startAudioCapture(page: Page): Promise<AudioStream> {
  // Inject the AudioWorklet processor code and capture setup into the page
  await page.evaluate((processorCode: string) => {
    (window as any).__audioChunks = [] as Float32Array[];
    (window as any).__audioCaptureActive = true;
    (window as any).__audioCleanup = [] as (() => void)[];

    // Store processor code for async loading inside captureAudioElement
    (window as any).__processorCode = processorCode;

    async function captureAudioElement(audio: HTMLAudioElement) {
      if (!audio.srcObject) {
        console.log(`[YodaBot] Skipping ${audio.id} — no srcObject`);
        return;
      }

      const ctx = new AudioContext();
      if (ctx.state === "suspended") {
        await ctx.resume();
        console.log(`[YodaBot] AudioContext resumed for ${audio.id}`);
      }

      // Register AudioWorklet processor via Blob URL
      const blob = new Blob([(window as any).__processorCode], { type: "application/javascript" });
      const blobUrl = URL.createObjectURL(blob);
      try {
        await ctx.audioWorklet.addModule(blobUrl);
      } finally {
        URL.revokeObjectURL(blobUrl);
      }

      const source = ctx.createMediaStreamSource(audio.srcObject as MediaStream);
      const workletNode = new AudioWorkletNode(ctx, "audio-capture-processor");

      // Receive resampled PCM from audio thread
      workletNode.port.onmessage = (event: MessageEvent) => {
        if (!(window as any).__audioCaptureActive) return;
        (window as any).__audioChunks.push(event.data as Float32Array);
      };

      source.connect(workletNode);
      // AudioWorkletNode does NOT need to connect to destination for capture,
      // but we connect to keep the audio graph alive in some browsers
      workletNode.connect(ctx.destination);

      console.log(`[YodaBot] AudioWorklet capture started for ${audio.id} @ ${ctx.sampleRate}Hz`);

      (window as any).__audioCleanup.push(() => {
        workletNode.port.postMessage("stop");
        workletNode.disconnect();
        source.disconnect();
        ctx.close();
      });
    }

    // Make captureAudioElement available globally for MutationObserver
    (window as any).__captureAudioElement = captureAudioElement;

    // Capture existing RTC audio elements
    const rtcAudios = document.querySelectorAll<HTMLAudioElement>("audio[data-rtc-track]");
    console.log(`[YodaBot] Found ${rtcAudios.length} RTC audio elements to capture`);
    rtcAudios.forEach((audio) => {
      const stream = audio.srcObject as MediaStream | null;
      const tracks = stream?.getAudioTracks() || [];
      console.log(
        `[YodaBot] ${audio.id}: srcObject=${!!stream}, audioTracks=${tracks.length}, trackStates=${tracks.map((t) => t.readyState).join(",")}`
      );
      captureAudioElement(audio);
    });

    // Watch for new RTC audio elements
    const observer = new MutationObserver((mutations) => {
      for (const mut of mutations) {
        for (const node of mut.addedNodes) {
          if (node instanceof HTMLAudioElement && node.getAttribute("data-rtc-track") === "true") {
            captureAudioElement(node);
          }
        }
      }
    });
    observer.observe(document.body, { childList: true });
    (window as any).__audioObserver = observer;
  }, WORKLET_PROCESSOR_CODE);

  // ... polling code stays exactly the same (lines 102-152) ...
```

**Step 2: Verify it compiles**

Run: `export PATH="$PATH:/c/Program Files/nodejs" && cd F:/Yoda/yoda-bb/teams-meeting-assistant/browser-bot && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add src/platforms/msteams/audio-capture.ts
git commit -m "refactor: migrate ScriptProcessorNode to AudioWorkletNode"
```

---

### Task 3: Add ScriptProcessorNode fallback for older Chromium

**Files:**
- Modify: `src/platforms/msteams/audio-capture.ts`

**Step 1: Add fallback inside captureAudioElement**

Wrap the AudioWorklet path in a try-catch that falls back to ScriptProcessorNode if `audioWorklet` is not available. This ensures the bot still works on Chromium versions without AudioWorklet support (unlikely with Playwright's bundled Chromium, but defensive).

Inside the `captureAudioElement` function in the page.evaluate block, wrap the audioWorklet registration:

```typescript
    async function captureAudioElement(audio: HTMLAudioElement) {
      if (!audio.srcObject) {
        console.log(`[YodaBot] Skipping ${audio.id} — no srcObject`);
        return;
      }

      const ctx = new AudioContext();
      if (ctx.state === "suspended") {
        await ctx.resume();
        console.log(`[YodaBot] AudioContext resumed for ${audio.id}`);
      }

      const source = ctx.createMediaStreamSource(audio.srcObject as MediaStream);
      const TARGET_SAMPLE_RATE = 16000;

      // Try AudioWorklet first, fall back to ScriptProcessorNode
      let useWorklet = false;
      if (ctx.audioWorklet) {
        try {
          const blob = new Blob([(window as any).__processorCode], { type: "application/javascript" });
          const blobUrl = URL.createObjectURL(blob);
          try {
            await ctx.audioWorklet.addModule(blobUrl);
          } finally {
            URL.revokeObjectURL(blobUrl);
          }
          useWorklet = true;
        } catch (err) {
          console.warn(`[YodaBot] AudioWorklet failed for ${audio.id}, falling back to ScriptProcessor:`, err);
        }
      }

      if (useWorklet) {
        const workletNode = new AudioWorkletNode(ctx, "audio-capture-processor");
        workletNode.port.onmessage = (event: MessageEvent) => {
          if (!(window as any).__audioCaptureActive) return;
          (window as any).__audioChunks.push(event.data as Float32Array);
        };
        source.connect(workletNode);
        workletNode.connect(ctx.destination);
        console.log(`[YodaBot] AudioWorklet capture started for ${audio.id} @ ${ctx.sampleRate}Hz`);

        (window as any).__audioCleanup.push(() => {
          workletNode.port.postMessage("stop");
          workletNode.disconnect();
          source.disconnect();
          ctx.close();
        });
      } else {
        // Fallback: ScriptProcessorNode (deprecated but universally supported)
        const BUFFER_SIZE = 4096;
        const processor = ctx.createScriptProcessor(BUFFER_SIZE, 1, 1);
        processor.onaudioprocess = (event: AudioProcessingEvent) => {
          if (!(window as any).__audioCaptureActive) return;
          const inputData = event.inputBuffer.getChannelData(0);
          const ratio = ctx.sampleRate / TARGET_SAMPLE_RATE;
          const outputLength = Math.floor(inputData.length / ratio);
          const output = new Float32Array(outputLength);
          for (let i = 0; i < outputLength; i++) {
            const srcIdx = i * ratio;
            const low = Math.floor(srcIdx);
            const high = Math.min(low + 1, inputData.length - 1);
            const frac = srcIdx - low;
            output[i] = inputData[low] * (1 - frac) + inputData[high] * frac;
          }
          (window as any).__audioChunks.push(output);
        };
        source.connect(processor);
        processor.connect(ctx.destination);
        console.log(`[YodaBot] ScriptProcessor fallback capture for ${audio.id} @ ${ctx.sampleRate}Hz`);

        (window as any).__audioCleanup.push(() => {
          processor.disconnect();
          source.disconnect();
          ctx.close();
        });
      }
    }
```

**Step 2: Verify it compiles**

Run: `export PATH="$PATH:/c/Program Files/nodejs" && cd F:/Yoda/yoda-bb/teams-meeting-assistant/browser-bot && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add src/platforms/msteams/audio-capture.ts
git commit -m "refactor: add ScriptProcessorNode fallback for AudioWorklet"
```

---

### Task 4: Replace polling with page.exposeFunction for direct audio callback

**Files:**
- Modify: `src/platforms/msteams/audio-capture.ts`

**Step 1: Replace the polling interval with page.exposeFunction**

Currently audio data is polled every 200ms via `page.evaluate()`. Replace this with `page.exposeFunction()` which creates a direct callback from browser context to Node.js — eliminating polling latency and reducing serialization overhead.

Replace the polling section (after the page.evaluate block) with:

```typescript
  let callbacks: ((pcmData: Float32Array) => void)[] = [];
  let stopped = false;

  // Expose a Node.js function to the page context for direct audio delivery
  await page.exposeFunction("__yodaOnAudioData", (data: number[]) => {
    if (stopped) return;
    const pcm = new Float32Array(data);
    for (const cb of callbacks) {
      cb(pcm);
    }
  });

  // Wire the in-page audio chunks to the exposed function
  await page.evaluate(() => {
    // Override the chunk accumulation — instead of buffering, send directly
    const origPush = Array.prototype.push;
    const chunks = (window as any).__audioChunks;

    // Replace __audioChunks with a proxy that sends data immediately
    (window as any).__audioChunks = new Proxy([], {
      get(target, prop) {
        if (prop === "push") {
          return (chunk: Float32Array) => {
            (window as any).__yodaOnAudioData(Array.from(chunk));
            return 0;
          };
        }
        return (target as any)[prop];
      },
    });
  });

  return {
    onAudioData(callback: (pcmData: Float32Array) => void) {
      callbacks.push(callback);
    },
    stop() {
      stopped = true;
      callbacks = [];
      page
        .evaluate(() => {
          (window as any).__audioCaptureActive = false;
          const cleanups = (window as any).__audioCleanup || [];
          for (const fn of cleanups) fn();
          const observer = (window as any).__audioObserver;
          if (observer) observer.disconnect();
        })
        .catch(() => {});
    },
  };
```

**Step 2: Verify it compiles**

Run: `export PATH="$PATH:/c/Program Files/nodejs" && cd F:/Yoda/yoda-bb/teams-meeting-assistant/browser-bot && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add src/platforms/msteams/audio-capture.ts
git commit -m "refactor: replace 200ms polling with page.exposeFunction direct callback"
```

---

### Task 5: Consolidate duplicate emitSegment methods in transcription.ts

**Files:**
- Modify: `src/services/transcription.ts`

**Step 1: Merge emitSegment and emitSegmentWithSpeaker into one method**

Replace both methods with a single `emitSegment` that accepts an optional `overrideSpeakerId`:

```typescript
  private emitSegment(
    text: string,
    durationSec: number,
    isFinal: boolean,
    overrideSpeakerId?: string
  ): void {
    const resolvedSpeakerId = overrideSpeakerId || this.activeSpeakerId;
    const resolvedSpeakerName = this.activeSpeakerName !== "Unknown"
      ? this.activeSpeakerName
      : overrideSpeakerId || "Unknown";

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

    this.backend
      .sendTranscriptChunk(this.meetingId, [segment])
      .catch((err) => {
        console.error(
          `[${this.meetingId}] Failed to send transcript:`,
          err.message
        );
      });
  }
```

Then update callers:
- ConversationTranscriber `transcribed` handler: `this.emitSegment(text, duration, true, speakerId)`
- SpeechRecognizer `recognized` handler: `this.emitSegment(text, duration, true)` (no speakerId)
- Remove the old `emitSegmentWithSpeaker` method entirely

**Step 2: Verify it compiles**

Run: `export PATH="$PATH:/c/Program Files/nodejs" && cd F:/Yoda/yoda-bb/teams-meeting-assistant/browser-bot && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add src/services/transcription.ts
git commit -m "refactor: consolidate duplicate emitSegment methods"
```

---

### Task 6: Remove unused ws dependency

**Files:**
- Modify: `package.json`

**Step 1: Remove ws from dependencies and @types/ws from devDependencies**

```bash
cd F:/Yoda/yoda-bb/teams-meeting-assistant/browser-bot
npm uninstall ws @types/ws
```

**Step 2: Verify nothing imports ws**

Run: `grep -r "from ['\"]ws['\"]" src/` — should return no results.

**Step 3: Verify it compiles**

Run: `export PATH="$PATH:/c/Program Files/nodejs" && cd F:/Yoda/yoda-bb/teams-meeting-assistant/browser-bot && npx tsc --noEmit`
Expected: No errors

**Step 4: Commit**

```bash
git add package.json package-lock.json
git commit -m "chore: remove unused ws dependency"
```

---

### Task 7: Final build verification and integration test

**Files:**
- All modified files

**Step 1: Full TypeScript build**

```bash
export PATH="$PATH:/c/Program Files/nodejs"
cd F:/Yoda/yoda-bb/teams-meeting-assistant/browser-bot
npx tsc --noEmit
```
Expected: 0 errors

**Step 2: Verify the dist builds cleanly**

```bash
npm run build
```
Expected: dist/ directory created with compiled JS

**Step 3: Start the bot and verify it launches**

```bash
export PATH="$PATH:/c/Program Files/nodejs"
cd F:/Yoda/yoda-bb/teams-meeting-assistant/browser-bot
AZURE_SPEECH_KEY=test AZURE_SPEECH_REGION=test node dist/index.js &
sleep 2
curl http://localhost:3001/health/live
kill %1
```
Expected: `{"status":"ok"}`

**Step 4: Commit any remaining fixes**

```bash
git add -A
git commit -m "refactor: AudioWorklet migration complete — build verified"
```

---

## Summary of Changes

| Task | File | What Changes |
|------|------|-------------|
| 1 | audio-capture.ts | Add AudioWorkletProcessor source as string constant |
| 2 | audio-capture.ts | Replace ScriptProcessorNode with AudioWorkletNode |
| 3 | audio-capture.ts | Add ScriptProcessorNode fallback for compatibility |
| 4 | audio-capture.ts | Replace 200ms polling with page.exposeFunction |
| 5 | transcription.ts | Merge duplicate emitSegment methods |
| 6 | package.json | Remove unused ws dependency |
| 7 | All | Final build verification |

**Total estimated file changes:** 2 files modified, ~200 lines changed
**Risk level:** Medium — audio pipeline is core functionality; ScriptProcessorNode fallback ensures no regression

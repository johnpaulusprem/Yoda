import { Page } from "playwright";

export interface AudioStream {
  onAudioData(callback: (pcmData: Float32Array) => void): void;
  stop(): void;
}

/**
 * Captures audio from the hooked RTCPeerConnection tracks in the page.
 * Uses Web Audio API (AudioContext → ScriptProcessorNode) to get raw PCM
 * data, then resamples to 16kHz mono for transcription.
 */
export async function startAudioCapture(page: Page): Promise<AudioStream> {
  // Inject audio capture code into the page. This:
  // 1. Finds <audio> elements created by our RTCPeerConnection hook
  // 2. Routes them through AudioContext → ScriptProcessorNode
  // 3. Resamples to 16kHz and exposes data via window.__audioChunks
  await page.evaluate(() => {
    (window as any).__audioChunks = [] as Float32Array[];
    (window as any).__audioCaptureActive = true;

    const TARGET_SAMPLE_RATE = 16000;
    const BUFFER_SIZE = 4096;

    function captureAudioElement(audio: HTMLAudioElement) {
      if (!audio.srcObject) {
        console.log(`[YodaBot] Skipping ${audio.id} — no srcObject`);
        return;
      }

      const ctx = new AudioContext();
      // Resume AudioContext — headless Chromium may start it suspended
      if (ctx.state === "suspended") {
        ctx.resume().then(() => console.log(`[YodaBot] AudioContext resumed for ${audio.id}`));
      }
      const source = ctx.createMediaStreamSource(audio.srcObject as MediaStream);
      const processor = ctx.createScriptProcessor(BUFFER_SIZE, 1, 1);

      processor.onaudioprocess = (event: AudioProcessingEvent) => {
        if (!(window as any).__audioCaptureActive) return;

        const inputData = event.inputBuffer.getChannelData(0);
        const inputRate = ctx.sampleRate;

        // Resample to 16kHz
        const ratio = inputRate / TARGET_SAMPLE_RATE;
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

      console.log(`[YodaBot] Audio capture started for ${audio.id} @ ${ctx.sampleRate}Hz`);

      // Store cleanup handle
      (window as any).__audioCleanup = (window as any).__audioCleanup || [];
      (window as any).__audioCleanup.push(() => {
        processor.disconnect();
        source.disconnect();
        ctx.close();
      });
    }

    // Capture existing RTC audio elements
    const rtcAudios = document.querySelectorAll<HTMLAudioElement>('audio[data-rtc-track]');
    console.log(`[YodaBot] Found ${rtcAudios.length} RTC audio elements to capture`);
    rtcAudios.forEach((audio) => {
      const stream = audio.srcObject as MediaStream | null;
      const tracks = stream?.getAudioTracks() || [];
      console.log(`[YodaBot] ${audio.id}: srcObject=${!!stream}, audioTracks=${tracks.length}, trackStates=${tracks.map(t => t.readyState).join(',')}`);
      captureAudioElement(audio);
    });

    // Watch for new RTC audio elements (more tracks may arrive after initial connection)
    const observer = new MutationObserver((mutations) => {
      for (const mut of mutations) {
        for (const node of mut.addedNodes) {
          if (
            node instanceof HTMLAudioElement &&
            node.getAttribute("data-rtc-track") === "true"
          ) {
            captureAudioElement(node);
          }
        }
      }
    });
    observer.observe(document.body, { childList: true });
    (window as any).__audioObserver = observer;
  });

  // Polling interval to pull audio chunks from the page context
  let callbacks: ((pcmData: Float32Array) => void)[] = [];
  let stopped = false;

  const pollInterval = setInterval(async () => {
    if (stopped) return;
    try {
      const chunks: number[][] = await page.evaluate(() => {
        const chunks = (window as any).__audioChunks as Float32Array[];
        if (!chunks || chunks.length === 0) return [];
        // Drain the buffer
        const result = chunks.map((c) => Array.from(c));
        (window as any).__audioChunks = [];
        return result;
      });

      for (const chunk of chunks) {
        const pcm = new Float32Array(chunk);
        for (const cb of callbacks) {
          cb(pcm);
        }
      }
    } catch {
      // Page might have closed
      if (!stopped) {
        console.log("Audio capture polling error — page may have closed");
      }
    }
  }, 200); // Poll every 200ms (~5x/sec)

  return {
    onAudioData(callback: (pcmData: Float32Array) => void) {
      callbacks.push(callback);
    },
    stop() {
      stopped = true;
      clearInterval(pollInterval);
      callbacks = [];
      // Clean up in-page resources
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
}

import { Page } from "playwright";

export interface AudioStream {
  onAudioData(callback: (pcmData: Float32Array) => void): void;
  onSilence(callback: (silenceSeconds: number) => void): void;
  stop(): Promise<void>;
}

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

    const channelData = input[0];
    const inputRate = sampleRate;
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

/**
 * Captures audio from the hooked RTCPeerConnection tracks in the page.
 * Uses Web Audio API (AudioContext → AudioWorkletNode) to get raw PCM
 * data on a dedicated audio thread, then resamples to 16kHz mono for
 * transcription. Falls back to ScriptProcessorNode if AudioWorklet is
 * unavailable. Audio data is delivered directly to Node.js via
 * page.exposeFunction (no polling).
 *
 * NOTE: Call only once per page — exposeFunction("__yodaOnAudioData")
 * can only be registered once per page context.
 */
export async function startAudioCapture(page: Page): Promise<AudioStream> {
  let callbacks: ((pcmData: Float32Array) => void)[] = [];
  let silenceCallbacks: ((silenceSeconds: number) => void)[] = [];
  let stopped = false;

  // Step 1: Expose Node.js function BEFORE any audio capture setup.
  // This ensures the Proxy installed in Step 2 can call it immediately,
  // eliminating the race condition where chunks buffer in a plain array.
  await page.exposeFunction("__yodaOnAudioData", (data: number[]) => {
    if (stopped) return;
    const pcm = new Float32Array(data);
    for (const cb of callbacks) {
      cb(pcm);
    }
  });

  await page.exposeFunction("__yodaOnAudioSilence", (silenceSeconds: number) => {
    if (stopped) return;
    for (const cb of silenceCallbacks) {
      cb(silenceSeconds);
    }
  });

  // Step 2: Inject audio capture code into the page.
  // The Proxy on __audioChunks is installed immediately (same evaluate block)
  // so there's zero window for chunks to buffer in a plain array.
  await page.evaluate((processorCode: string) => {
    (window as any).__audioCaptureActive = true;
    (window as any).__audioCleanup = [];

    // Batch audio chunks in-browser and flush every 100ms.
    // Sending each micro-chunk (~42 samples at 2.7ms intervals) individually
    // through page.exposeFunction causes ~375 protocol roundtrips/sec,
    // adding 10-15s of latency. Batching reduces calls to ~10/sec.
    const pendingChunks: Float32Array[] = [];
    const FLUSH_INTERVAL_MS = 100;

    const flushAudioChunks = () => {
      if (pendingChunks.length === 0) return;
      // Merge all pending chunks into a single array for one protocol call
      let totalLen = 0;
      for (const c of pendingChunks) totalLen += c.length;
      const merged = new Float32Array(totalLen);
      let offset = 0;
      for (const c of pendingChunks) {
        merged.set(c, offset);
        offset += c.length;
      }
      pendingChunks.length = 0;
      (window as any).__yodaOnAudioData(Array.from(merged));
    }

    const flushTimerId = setInterval(flushAudioChunks, FLUSH_INTERVAL_MS);
    (window as any).__audioFlushTimerId = flushTimerId;

    // Proxy intercepts .push() to buffer chunks for batched delivery
    (window as any).__audioChunks = new Proxy([], {
      get(target: any, prop: string) {
        if (prop === "push") {
          return (chunk: Float32Array) => {
            // Set audio session start timestamp on first chunk (Vexa pattern)
            // This is used by speaker-detection.ts for relative timestamps
            if (!(window as any).__yodaAudioStartMs) {
              (window as any).__yodaAudioStartMs = Date.now();
              console.log(`[YodaBot] Audio session start set: ${(window as any).__yodaAudioStartMs}`);
            }
            pendingChunks.push(chunk);
            return 0;
          };
        }
        return target[prop];
      },
    });

    // Shared AudioContext — Chrome limits to ~6 active contexts.
    // Reuse one context for all audio elements to avoid hitting the limit
    // when participants join/leave frequently.
    let sharedCtx: AudioContext | null = null;
    let workletModuleLoaded = false;

    const getOrCreateContext = async (): Promise<AudioContext> => {
      if (!sharedCtx || sharedCtx.state === "closed") {
        sharedCtx = new AudioContext();
        (window as any).__sharedAudioCtx = sharedCtx; // Keep cleanup reference in sync
        workletModuleLoaded = false; // New context needs fresh module load
      }
      if (sharedCtx.state === "suspended") {
        await sharedCtx.resume();
      }
      return sharedCtx;
    }

    const captureAudioElement = async (audio: HTMLAudioElement) => {
      if (!audio.srcObject) {
        console.log(`[YodaBot] Skipping ${audio.id} — no srcObject`);
        return;
      }

      const ctx = await getOrCreateContext();
      const source = ctx.createMediaStreamSource(audio.srcObject as MediaStream);

      // Use a GainNode(0) to silence speaker output while keeping the
      // audio pipeline alive. source → [capture node] → gainNode(0) → destination.
      // The capture node (AudioWorklet or ScriptProcessor) taps the full-volume
      // audio before it hits the silent gain gate.
      const silenceGain = ctx.createGain();
      silenceGain.gain.value = 0; // Zero gain = no speaker output
      silenceGain.connect(ctx.destination);

      try {
        // Load AudioWorklet module once per AudioContext.
        // Use data URI instead of blob URL — blob URLs fail in headless Chromium
        // with "AbortError: Unable to load a worklet's module".
        if (!workletModuleLoaded) {
          const dataUri = `data:application/javascript;base64,${btoa(processorCode)}`;
          await ctx.audioWorklet.addModule(dataUri);
          workletModuleLoaded = true;
        }

        const workletNode = new AudioWorkletNode(ctx, 'audio-capture-processor');

        workletNode.port.onmessage = (event: MessageEvent) => {
          if (!(window as any).__audioCaptureActive) return;
          (window as any).__audioChunks.push(event.data as Float32Array);
        };

        source.connect(workletNode);
        workletNode.connect(silenceGain); // Route through silent gain instead of directly to destination

        console.log(`[YodaBot] Audio capture started for ${audio.id} @ ${ctx.sampleRate}Hz (AudioWorklet)`);

        (window as any).__audioCleanup.push(() => {
          workletNode.port.postMessage('stop');
          workletNode.disconnect();
          silenceGain.disconnect();
          source.disconnect();
          // Don't close shared ctx here — other elements may still use it
        });
      } catch (workletError) {
        // Fall back to ScriptProcessorNode
        console.log(`[YodaBot] AudioWorklet failed for ${audio.id}, falling back to ScriptProcessor:`, workletError);

        const TARGET_SAMPLE_RATE = 16000;
        const BUFFER_SIZE = 4096;
        const processor = ctx.createScriptProcessor(BUFFER_SIZE, 1, 1);

        processor.onaudioprocess = (event: AudioProcessingEvent) => {
          if (!(window as any).__audioCaptureActive) return;

          const inputData = event.inputBuffer.getChannelData(0);
          const inputRate = ctx.sampleRate;

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
        processor.connect(silenceGain); // Route through silent gain instead of directly to destination

        console.log(`[YodaBot] Audio capture started for ${audio.id} @ ${ctx.sampleRate}Hz (ScriptProcessor fallback)`);

        (window as any).__audioCleanup.push(() => {
          processor.disconnect();
          silenceGain.disconnect();
          source.disconnect();
        });
      }
    }

    (window as any).__captureAudioElement = captureAudioElement;

    // Store shared context reference for cleanup
    (window as any).__sharedAudioCtx = sharedCtx;
    // Update reference whenever context is created
    const origGetOrCreate = getOrCreateContext;
    // We need to keep __sharedAudioCtx in sync
    (window as any).__getOrCreateContext = async () => {
      const ctx = await origGetOrCreate();
      (window as any).__sharedAudioCtx = ctx;
      return ctx;
    };

    // Capture existing RTC audio elements
    const rtcAudios = document.querySelectorAll<HTMLAudioElement>('audio[data-rtc-track]');
    console.log(`[YodaBot] Found ${rtcAudios.length} RTC audio elements to capture`);
    rtcAudios.forEach((audio) => {
      const stream = audio.srcObject as MediaStream | null;
      const tracks = stream?.getAudioTracks() || [];
      console.log(`[YodaBot] ${audio.id}: srcObject=${!!stream}, audioTracks=${tracks.length}, trackStates=${tracks.map(t => `${t.readyState}(enabled=${t.enabled},muted=${t.muted})`).join(',')}`);
      // Skip audio elements with ended tracks — they produce only zeros
      const hasLiveTrack = tracks.some(t => t.readyState === 'live');
      if (!hasLiveTrack && tracks.length > 0) {
        console.log(`[YodaBot] Skipping ${audio.id} — all tracks ended`);
        return;
      }
      captureAudioElement(audio);
    });

    // Diagnostic: after 5 seconds, check audio levels via AnalyserNode
    setTimeout(async () => {
      if (!sharedCtx || sharedCtx.state === 'closed') return;
      try {
        const analyser = sharedCtx.createAnalyser();
        analyser.fftSize = 2048;
        // Connect all sources to the analyser
        const allAudios = document.querySelectorAll<HTMLAudioElement>('audio[data-rtc-track]');
        let connectedCount = 0;
        allAudios.forEach(audio => {
          if (audio.srcObject) {
            const stream = audio.srcObject as MediaStream;
            const liveTracks = stream.getAudioTracks().filter(t => t.readyState === 'live');
            if (liveTracks.length > 0) {
              try {
                const src = sharedCtx!.createMediaStreamSource(new MediaStream(liveTracks));
                src.connect(analyser);
                connectedCount++;
              } catch (e) { /* ignore duplicate connections */ }
            }
          }
        });

        const data = new Float32Array(analyser.fftSize);
        analyser.getFloatTimeDomainData(data);
        let maxVal = 0;
        let rms = 0;
        for (let i = 0; i < data.length; i++) {
          const abs = Math.abs(data[i]);
          if (abs > maxVal) maxVal = abs;
          rms += data[i] * data[i];
        }
        rms = Math.sqrt(rms / data.length);
        console.log(
          `[YodaBot] Audio diagnostic (5s): ctx.state=${sharedCtx!.state}, ` +
          `sampleRate=${sharedCtx!.sampleRate}, sources=${connectedCount}, ` +
          `peak=${maxVal.toFixed(6)}, rms=${rms.toFixed(6)} ` +
          `(${maxVal > 0.001 ? 'AUDIO FLOWING' : 'SILENT — check headed mode'})`
        );
        analyser.disconnect();
      } catch (e: any) {
        console.log(`[YodaBot] Audio diagnostic failed: ${e.message}`);
      }
    }, 5000);

    // Continuous silence monitoring (every 10 seconds)
    let lastNonSilentAt = Date.now();
    const SILENCE_CHECK_INTERVAL_MS = 10_000;
    const SILENCE_WARN_THRESHOLD_S = 30;

    const silenceCheckId = setInterval(() => {
      if (!sharedCtx || sharedCtx.state === "closed") return;
      try {
        const analyser = sharedCtx.createAnalyser();
        analyser.fftSize = 256;
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
              } catch { /* ignore duplicate */ }
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
      } catch { /* analyser may fail if context closed */ }
    }, SILENCE_CHECK_INTERVAL_MS);

    (window as any).__silenceCheckId = silenceCheckId;

    // Watch for new RTC audio elements
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
  }, WORKLET_PROCESSOR_CODE);

  return {
    onAudioData(callback: (pcmData: Float32Array) => void) {
      callbacks.push(callback);
    },
    onSilence(callback: (silenceSeconds: number) => void) {
      silenceCallbacks.push(callback);
    },
    async stop() {
      stopped = true;
      callbacks.length = 0; // Clear without reassigning — closure keeps same reference
      silenceCallbacks.length = 0;
      // Clean up in-page resources
      await page
        .evaluate(() => {
          (window as any).__audioCaptureActive = false;
          // Stop the batched flush timer
          if ((window as any).__audioFlushTimerId) {
            clearInterval((window as any).__audioFlushTimerId);
            (window as any).__audioFlushTimerId = null;
          }
          // Clear silence monitoring
          if ((window as any).__silenceCheckId) {
            clearInterval((window as any).__silenceCheckId);
            (window as any).__silenceCheckId = null;
          }
          // Run element-level cleanups (disconnect nodes/sources)
          const cleanups = (window as any).__audioCleanup || [];
          for (const fn of cleanups) fn();
          (window as any).__audioCleanup = null;
          // Disconnect the DOM observer
          const observer = (window as any).__audioObserver;
          if (observer) {
            observer.disconnect();
            (window as any).__audioObserver = null;
          }
          // Close the shared AudioContext
          const ctx = (window as any).__sharedAudioCtx;
          if (ctx && ctx.state !== "closed") {
            ctx.close();
          }
          (window as any).__sharedAudioCtx = null;
          // Clear remaining references
          (window as any).__audioChunks = null;
          (window as any).__captureAudioElement = null;
        })
        .catch(() => {});
    },
  };
}

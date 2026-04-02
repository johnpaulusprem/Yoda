import { PythonBackendClient, TranscriptSegment } from "./python-backend.js";
import { SpeakerEvent } from "../platforms/msteams/speaker-detection.js";

/**
 * Speaker event stored for overlap-based mapping.
 * Each event represents a SPEAKER_START or SPEAKER_END with a relative timestamp.
 */
interface StoredSpeakerEvent {
  eventType: "SPEAKER_START" | "SPEAKER_END";
  participantId: string;
  participantName: string;
  relativeTimestampMs: number;
  receivedAt: number; // Date.now() for diagnostics
}

/**
 * Buffers audio data, runs Azure Speech recognition, and sends transcript
 * segments to the Python backend.
 *
 * Speaker attribution uses the Vexa-style overlap algorithm:
 * - SPEAKER_START/SPEAKER_END events are buffered with relative timestamps
 * - When a transcript segment is finalized, the algorithm computes which
 *   speaker(s) had the longest overlap with the segment's time interval
 * - The speaker with the longest overlap is attributed to the segment
 *
 * Provider priority:
 * 1. Azure ConversationTranscriber (diarization)
 * 2. Azure SpeechRecognizer (fallback, no diarization)
 * 3. Buffer mode (no transcription, logs audio stats)
 */
export class TranscriptionService {
  private backend: PythonBackendClient;
  private meetingId: string;
  private sequenceNumber = 100_000;
  private captionSequenceNumber = 0;
  captionActive = false;
  private activeSpeakerId = "";
  private activeSpeakerName = "Unknown";
  private running = false;

  // ── Speaker event buffer for overlap-based mapping ──
  private speakerEvents: StoredSpeakerEvent[] = [];
  private static readonly MAX_SPEAKER_EVENTS = 2000; // ~8+ hours at normal speaking rates
  private static readonly SPEAKER_EVENT_TTL_MS = 24 * 60 * 60 * 1000; // 24h
  /** Epoch: set to Date.now() on first audio chunk (like Vexa's sessionAudioStartTimeMs) */
  private audioSessionStartMs: number | null = null;

  // Audio buffer for batch processing (capped to prevent unbounded growth)
  private audioBuffer: Float32Array[] = [];
  private audioBufferSamples = 0;
  private static readonly MAX_BUFFER_SAMPLES = 480_000; // ~30s at 16kHz
  private flushInterval: ReturnType<typeof setInterval> | null = null;

  // Azure Speech SDK (lazy-loaded)
  private recognizer: any = null;
  private transcriber: any = null;
  private pushStream: any = null;
  private useAzureSpeech = false;

  constructor(backend: PythonBackendClient, meetingId: string) {
    this.backend = backend;
    this.meetingId = meetingId;
  }

  async start(): Promise<void> {
    this.running = true;

    if (await this.tryAzureSpeech()) return;

    // Fallback: buffer audio and log stats
    console.log(
      `[${this.meetingId}] No transcription provider available — using buffer mode. ` +
      `Set AZURE_SPEECH_KEY + AZURE_SPEECH_REGION for real-time transcription.`
    );
    this.flushInterval = setInterval(() => this.flushBuffer(), 5000);
  }

  private async tryAzureSpeech(): Promise<boolean> {
    try {
      const sdk = await import("microsoft-cognitiveservices-speech-sdk");
      const speechKey = process.env.AZURE_SPEECH_KEY;
      const speechRegion = process.env.AZURE_SPEECH_REGION;
      const speechEndpoint = process.env.AZURE_SPEECH_ENDPOINT;

      if (!speechKey || (!speechRegion && !speechEndpoint)) return false;

      // Use custom endpoint if configured (required for resources with custom domains/firewall),
      // otherwise fall back to regional endpoint.
      let speechConfig;
      if (speechEndpoint) {
        const endpointUrl = speechEndpoint.replace(/\/$/, ""); // strip trailing slash
        speechConfig = sdk.SpeechConfig.fromEndpoint(new URL(endpointUrl), speechKey);
        console.log(`[${this.meetingId}] Using custom Speech endpoint: ${endpointUrl}`);
      } else {
        speechConfig = sdk.SpeechConfig.fromSubscription(speechKey, speechRegion!);
      }
      speechConfig.speechRecognitionLanguage = "en-US";

      const pushStream = sdk.AudioInputStream.createPushStream(
        sdk.AudioStreamFormat.getWaveFormatPCM(16000, 16, 1)
      );
      const audioConfig = sdk.AudioConfig.fromStreamInput(pushStream);
      this.pushStream = pushStream;

      // Try ConversationTranscriber first (diarization)
      try {
        if (sdk.ConversationTranscriber) {
          this.transcriber = new sdk.ConversationTranscriber(speechConfig, audioConfig);
          this.useAzureSpeech = true;

          this.transcriber.transcribed = (_sender: any, event: any) => {
            if (event.result.text) {
              const speakerId: string = event.result.speakerId || "";
              const speakerLabel = speakerId || this.activeSpeakerName;
              console.log(`[${this.meetingId}] Speaker: ${speakerLabel} → "${event.result.text}"`);
              this.emitSegment(event.result.text, event.result.duration / 10000000, true, speakerId);
            }
          };

          this.transcriber.transcribing = (_sender: any, event: any) => {
            if (event.result.text) {
              const speakerId: string = event.result.speakerId || "";
              // Show DOM-mapped speaker name if available (resolves "Guest-1"/"Unknown" to real names)
              const speakerLabel = this.activeSpeakerName !== "Unknown"
                ? this.activeSpeakerName
                : speakerId || "Unknown";
              console.log(`[${this.meetingId}] TRANSCRIPT (partial) Speaker: ${speakerLabel} → "${event.result.text}"`);
            }
          };

          this.transcriber.canceled = (_sender: any, event: any) => {
            const details = event.errorDetails || event.reason || "";
            const errorCode = event.errorCode ?? "";
            console.error(`[${this.meetingId}] Transcription canceled: ${details} (code=${errorCode})`);
            
            // If WebSocket dropped (1006) or connection failed, fall back to SpeechRecognizer
            if (String(details).includes("1006") || String(details).includes("Unable to contact")) {
              console.warn(`[${this.meetingId}] ConversationTranscriber WebSocket failed — attempting SpeechRecognizer fallback...`);
              this.transcriber = null;
              this.useAzureSpeech = false;
              // Re-create pushStream and try SpeechRecognizer
              this.fallbackToRecognizer(sdk).catch((err: any) => {
                console.error(`[${this.meetingId}] SpeechRecognizer fallback also failed: ${err.message}`);
              });
            }
          };

          this.transcriber.sessionStarted = () => {
            console.log(`[${this.meetingId}] Transcription session STARTED (WebSocket connected)`);
          };

          this.transcriber.sessionStopped = () => {
            console.log(`[${this.meetingId}] Transcription session stopped`);
          };

          await new Promise<void>((resolve, reject) => {
            this.transcriber.startTranscribingAsync(resolve, reject);
          });
          console.log(`[${this.meetingId}] Azure ConversationTranscriber initialized (diarization enabled)`);
          return true;
        }
      } catch (diaErr: any) {
        console.warn(`[${this.meetingId}] ConversationTranscriber failed: ${diaErr.message} — falling back to SpeechRecognizer`);
        this.transcriber = null;
        this.useAzureSpeech = false;
      }

      // Fallback: SpeechRecognizer (no diarization)
      // Need fresh pushStream since the previous one may have been consumed
      const pushStream2 = sdk.AudioInputStream.createPushStream(
        sdk.AudioStreamFormat.getWaveFormatPCM(16000, 16, 1)
      );
      const audioConfig2 = sdk.AudioConfig.fromStreamInput(pushStream2);
      this.pushStream = pushStream2;

      this.recognizer = new sdk.SpeechRecognizer(speechConfig, audioConfig2);
      this.useAzureSpeech = true;

      this.recognizer.recognized = (_sender: any, event: any) => {
        if (event.result.reason === sdk.ResultReason.RecognizedSpeech && event.result.text) {
          console.log(`[${this.meetingId}] TRANSCRIPT (final): ${event.result.text}`);
          this.emitSegment(event.result.text, event.result.duration / 10000000, true);
        }
      };

      this.recognizer.recognizing = (_sender: any, event: any) => {
        if (event.result.text) {
          console.log(`[${this.meetingId}] TRANSCRIPT (partial): ${event.result.text}`);
        }
      };

      this.recognizer.canceled = (_sender: any, event: any) => {
        const details = event.errorDetails || event.reason || "";
        console.error(`[${this.meetingId}] Speech recognition canceled: ${details}`);
      };

      await new Promise<void>((resolve, reject) => {
        this.recognizer.startContinuousRecognitionAsync(resolve, reject);
      });
      console.log(`[${this.meetingId}] Azure SpeechRecognizer initialized (no diarization)`);
      return true;
    } catch (err: any) {
      console.error(`[${this.meetingId}] Azure Speech SDK init failed: ${err.message}`);
      return false;
    }
  }

  /**
   * Fallback: create a new SpeechRecognizer when ConversationTranscriber's WebSocket drops.
   * Re-creates the pushStream so old dead references are replaced.
   */
  private async fallbackToRecognizer(sdk: any): Promise<void> {
    try {
      const speechKey = process.env.AZURE_SPEECH_KEY!;
      const speechRegion = process.env.AZURE_SPEECH_REGION;
      const speechEndpoint = process.env.AZURE_SPEECH_ENDPOINT;

      let speechConfig;
      if (speechEndpoint) {
        const endpointUrl = speechEndpoint.replace(/\/$/, "");
        speechConfig = sdk.SpeechConfig.fromEndpoint(new URL(endpointUrl), speechKey);
      } else {
        speechConfig = sdk.SpeechConfig.fromSubscription(speechKey, speechRegion!);
      }
      speechConfig.speechRecognitionLanguage = "en-US";

      // Fresh pushStream
      const pushStream = sdk.AudioInputStream.createPushStream(
        sdk.AudioStreamFormat.getWaveFormatPCM(16000, 16, 1)
      );
      const audioConfig = sdk.AudioConfig.fromStreamInput(pushStream);
      this.pushStream = pushStream;

      this.recognizer = new sdk.SpeechRecognizer(speechConfig, audioConfig);
      this.useAzureSpeech = true;

      this.recognizer.recognized = (_sender: any, event: any) => {
        if (event.result.reason === sdk.ResultReason.RecognizedSpeech && event.result.text) {
          console.log(`[${this.meetingId}] TRANSCRIPT (final): ${event.result.text}`);
          this.emitSegment(event.result.text, event.result.duration / 10000000, true);
        }
      };

      this.recognizer.recognizing = (_sender: any, event: any) => {
        if (event.result.text) {
          console.log(`[${this.meetingId}] TRANSCRIPT (partial): ${event.result.text}`);
        }
      };

      this.recognizer.canceled = (_sender: any, event: any) => {
        const details = event.errorDetails || event.reason || "";
        console.error(`[${this.meetingId}] SpeechRecognizer canceled: ${details}`);
      };

      await new Promise<void>((resolve, reject) => {
        this.recognizer.startContinuousRecognitionAsync(resolve, reject);
      });
      console.log(`[${this.meetingId}] Fallback SpeechRecognizer initialized successfully`);
    } catch (err: any) {
      console.error(`[${this.meetingId}] Fallback SpeechRecognizer failed: ${err.message}`);
      this.useAzureSpeech = false;
    }
  }

  private pushCount = 0;
  private totalSamples = 0;
  private lastPushLogAt = 0;

  pushAudio(pcmData: Float32Array): void {
    if (!this.running) return;

    // Set audio session start on first chunk (Vexa's sessionAudioStartTimeMs)
    this.setAudioSessionStart();

    this.pushCount++;
    this.totalSamples += pcmData.length;

    // Log audio stats every 10 seconds
    const now = Date.now();
    if (now - this.lastPushLogAt > 10_000) {
      let peak = 0;
      for (let i = 0; i < pcmData.length; i++) {
        const abs = Math.abs(pcmData[i]);
        if (abs > peak) peak = abs;
      }
      console.log(
        `[${this.meetingId}] pushAudio stats: chunks=${this.pushCount} totalSamples=${this.totalSamples} ` +
        `(${(this.totalSamples / 16000).toFixed(1)}s) peak=${peak.toFixed(6)} ` +
        `azureSpeech=${this.useAzureSpeech} pushStream=${!!this.pushStream}`
      );
      this.lastPushLogAt = now;
    }

    if (this.useAzureSpeech && (this.transcriber || this.recognizer) && this.pushStream) {
      // Convert Float32 [-1,1] to Int16 PCM for Azure Speech SDK
      const int16 = new Int16Array(pcmData.length);
      for (let i = 0; i < pcmData.length; i++) {
        const s = Math.max(-1, Math.min(1, pcmData[i]));
        int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      }
      this.pushStream.write(int16.buffer);
    } else {
      this.audioBuffer.push(pcmData);
      this.audioBufferSamples += pcmData.length;
      while (this.audioBufferSamples > TranscriptionService.MAX_BUFFER_SAMPLES && this.audioBuffer.length > 0) {
        const dropped = this.audioBuffer.shift()!;
        this.audioBufferSamples -= dropped.length;
      }
    }
  }

  setActiveSpeaker(speakerId: string, speakerName: string): void {
    this.activeSpeakerId = speakerId;
    this.activeSpeakerName = speakerName;
  }

  // ═══════════════════════════════════════════════════════════════
  // Speaker Event Buffer & Overlap-Based Mapping (Vexa-style)
  // ═══════════════════════════════════════════════════════════════

  /**
   * Record the audio session start time. Should be called on the first audio chunk.
   * This is the epoch for all relative timestamps in speaker events.
   */
  setAudioSessionStart(): void {
    if (this.audioSessionStartMs === null) {
      this.audioSessionStartMs = Date.now();
      console.log(`[${this.meetingId}] Audio session start set: ${this.audioSessionStartMs}`);
    }
  }

  /**
   * Ingest a SPEAKER_START / SPEAKER_END event from DOM-based speaker detection.
   * Events are stored chronologically for overlap mapping.
   */
  pushSpeakerEvent(event: SpeakerEvent): void {
    const stored: StoredSpeakerEvent = {
      eventType: event.eventType,
      participantId: event.participantId,
      participantName: event.participantName,
      relativeTimestampMs: event.relativeTimestampMs,
      receivedAt: Date.now(),
    };

    this.speakerEvents.push(stored);

    // Cap buffer size
    if (this.speakerEvents.length > TranscriptionService.MAX_SPEAKER_EVENTS) {
      this.speakerEvents.splice(0, this.speakerEvents.length - TranscriptionService.MAX_SPEAKER_EVENTS);
    }

    // Also update the "current active speaker" for backward compatibility
    if (event.eventType === "SPEAKER_START") {
      this.activeSpeakerId = event.participantId;
      this.activeSpeakerName = event.participantName;
      console.log(
        `[${this.meetingId}] Active speaker set: "${event.participantName}" ` +
        `(id=${event.participantId.substring(0, 20)}, at=${event.relativeTimestampMs.toFixed(0)}ms, ` +
        `buffered=${this.speakerEvents.length})`
      );
    }
  }

  /**
   * Map a transcript segment to the most likely speaker using the overlap algorithm.
   *
   * Algorithm (from Vexa deep-dive, with fix for speaker-transition bias):
   * 1. Build a timeline of speaking intervals from SPEAKER_START/END pairs
   * 2. For each interval that overlaps the segment, compute overlap duration
   * 3. Select speaker with longest overlap
   *
   * Key fix: when building intervals, pair each START with its corresponding END
   * rather than just using the latest START. A speaker may have multiple
   * START/END pairs (e.g., spoke, paused, spoke again).
   *
   * @param segmentStartMs - segment start time (relative to audio session start, in ms)
   * @param segmentEndMs - segment end time
   * @returns { speakerName, speakerId, status }
   */
  private mapSpeakerToSegment(
    segmentStartMs: number,
    segmentEndMs: number
  ): { speakerName: string; speakerId: string; status: string } {
    if (this.speakerEvents.length === 0) {
      return {
        speakerName: this.activeSpeakerName,
        speakerId: this.activeSpeakerId,
        status: "NO_SPEAKER_EVENTS",
      };
    }

    const POST_BUFFER_MS = 500; // 500ms buffer after segment end

    // Filter events within the relevant time window (always from 0, per Vexa doc)
    const relevantEvents = this.speakerEvents.filter(
      (e) => e.relativeTimestampMs <= segmentEndMs + POST_BUFFER_MS
    );

    if (relevantEvents.length === 0) {
      return {
        speakerName: this.activeSpeakerName,
        speakerId: this.activeSpeakerId,
        status: "NO_SPEAKER_EVENTS",
      };
    }

    // ── Build speaking intervals from START/END pairs ──
    // Each speaker can have multiple intervals (spoke, paused, spoke again).
    // An interval is [startTs, endTs] for one continuous speaking period.
    interface SpeakingInterval {
      participantId: string;
      participantName: string;
      startTs: number;
      endTs: number; // segmentEndMs if still speaking (no END event yet)
    }

    // Track open (currently speaking) intervals per participant
    const openIntervals = new Map<string, { participantId: string; participantName: string; startTs: number }>();
    const allIntervals: SpeakingInterval[] = [];

    for (const event of relevantEvents) {
      const key = event.participantId || event.participantName;

      if (event.eventType === "SPEAKER_START") {
        // Close any existing open interval for this speaker before opening a new one
        const existing = openIntervals.get(key);
        if (existing) {
          allIntervals.push({
            ...existing,
            endTs: event.relativeTimestampMs, // Implicitly ended when a new START arrives
          });
        }
        openIntervals.set(key, {
          participantId: event.participantId,
          participantName: event.participantName,
          startTs: event.relativeTimestampMs,
        });
      } else if (event.eventType === "SPEAKER_END") {
        const existing = openIntervals.get(key);
        if (existing) {
          allIntervals.push({
            ...existing,
            endTs: event.relativeTimestampMs,
          });
          openIntervals.delete(key);
        }
      }
    }

    // Close any still-open intervals (speaker hasn't stopped yet)
    for (const [, open] of openIntervals) {
      allIntervals.push({
        ...open,
        endTs: segmentEndMs, // Assume still speaking until segment end
      });
    }

    // ── Compute overlap for each interval with the segment ──
    // Accumulate total overlap per speaker (a speaker may have multiple intervals)
    const speakerOverlap = new Map<string, { participantId: string; participantName: string; totalOverlapMs: number }>();

    for (const interval of allIntervals) {
      const overlapStart = Math.max(interval.startTs, segmentStartMs);
      const overlapEnd = Math.min(interval.endTs, segmentEndMs);

      if (overlapStart < overlapEnd) {
        const overlapMs = overlapEnd - overlapStart;
        const key = interval.participantId || interval.participantName;
        const existing = speakerOverlap.get(key);

        if (existing) {
          existing.totalOverlapMs += overlapMs;
        } else {
          speakerOverlap.set(key, {
            participantId: interval.participantId,
            participantName: interval.participantName,
            totalOverlapMs: overlapMs,
          });
        }
      }
    }

    if (speakerOverlap.size === 0) {
      return {
        speakerName: this.activeSpeakerName,
        speakerId: this.activeSpeakerId,
        status: "UNKNOWN",
      };
    }

    // ── Select speaker with longest total overlap ──
    const scored = Array.from(speakerOverlap.values()).sort(
      (a, b) => b.totalOverlapMs - a.totalOverlapMs
    );
    const winner = scored[0];

    const status = scored.length > 1 ? "MULTIPLE_CONCURRENT_SPEAKERS" : "MAPPED";

    if (scored.length > 1) {
      console.log(
        `[${this.meetingId}] Speaker mapping: ${scored.length} concurrent speakers. ` +
        `Winner: "${winner.participantName}" (${winner.totalOverlapMs}ms overlap) vs ` +
        `"${scored[1].participantName}" (${scored[1].totalOverlapMs}ms overlap)`
      );
    }

    return {
      speakerName: winner.participantName,
      speakerId: winner.participantId,
      status,
    };
  }

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

  private emitSegment(
    text: string,
    durationSec: number,
    isFinal: boolean,
    overrideSpeakerId?: string
  ): void {
    // ── Overlap-based speaker mapping (Vexa-style) ──
    // Compute segment time window relative to audio session start
    const nowMs = Date.now();
    const segmentEndMs = this.audioSessionStartMs
      ? nowMs - this.audioSessionStartMs
      : 0;
    const segmentStartMs = Math.max(0, segmentEndMs - durationSec * 1000);

    let resolvedSpeakerId: string;
    let resolvedSpeakerName: string;

    // Priority: DOM-based overlap mapping > ConversationTranscriber speakerId > last-seen active speaker
    // The overlap mapping uses SPEAKER_START/SPEAKER_END events from DOM observation,
    // which provide actual participant names (e.g., "John Paulus P") rather than
    // ConversationTranscriber's generic IDs (e.g., "Guest-1").
    if (this.speakerEvents.length > 0 && this.audioSessionStartMs) {
      // Use overlap-based mapping (Vexa-style) — this resolves to real names
      const mapping = this.mapSpeakerToSegment(segmentStartMs, segmentEndMs);

      if (mapping.status !== "NO_SPEAKER_EVENTS" && mapping.status !== "UNKNOWN" && mapping.speakerName) {
        resolvedSpeakerId = mapping.speakerId;
        resolvedSpeakerName = mapping.speakerName;

        if (isFinal) {
          console.log(
            `[${this.meetingId}] Speaker mapped: "${resolvedSpeakerName}" ` +
            `(status=${mapping.status}, azureSpeakerId=${overrideSpeakerId || "none"}, ` +
            `segment=${segmentStartMs.toFixed(0)}-${segmentEndMs.toFixed(0)}ms, ` +
            `events=${this.speakerEvents.length})`
          );
        }
      } else if (overrideSpeakerId) {
        // Overlap mapping failed but ConversationTranscriber gave us an ID
        resolvedSpeakerId = overrideSpeakerId;
        resolvedSpeakerName = this.activeSpeakerName !== "Unknown"
          ? this.activeSpeakerName
          : overrideSpeakerId;

        if (isFinal) {
          console.log(
            `[${this.meetingId}] Speaker fallback to Azure: "${resolvedSpeakerName}" ` +
            `(azureSpeakerId=${overrideSpeakerId}, mapping=${mapping.status})`
          );
        }
      } else {
        resolvedSpeakerId = this.activeSpeakerId;
        resolvedSpeakerName = this.activeSpeakerName;
      }
    } else if (overrideSpeakerId) {
      // No speaker events yet but ConversationTranscriber gave us an ID
      resolvedSpeakerId = overrideSpeakerId;
      resolvedSpeakerName = this.activeSpeakerName !== "Unknown"
        ? this.activeSpeakerName
        : overrideSpeakerId;
    } else {
      // Fallback: use last-seen active speaker
      resolvedSpeakerId = this.activeSpeakerId;
      resolvedSpeakerName = this.activeSpeakerName;
    }

    const segment: TranscriptSegment = {
      sequence: this.sequenceNumber++,
      speakerId: resolvedSpeakerId,
      speakerName: resolvedSpeakerName,
      text: text.trim(),
      startTimeSec: Math.max(0, nowMs / 1000 - durationSec),
      endTimeSec: nowMs / 1000,
      confidence: 0.9,
      isFinal,
      source: "audio" as const,
    };

    this.backend
      .sendTranscriptChunk(this.meetingId, [segment])
      .catch((err) => {
        console.error(`[${this.meetingId}] Failed to send transcript:`, err.message);
      });
  }

  private flushBuffer(): void {
    if (this.audioBuffer.length === 0) return;

    const totalSamples = this.audioBuffer.reduce((sum, buf) => sum + buf.length, 0);
    const durationSec = totalSamples / 16000;

    let maxAmplitude = 0;
    let rmsSum = 0;
    let sampleCount = 0;
    for (const buf of this.audioBuffer) {
      for (let i = 0; i < buf.length; i++) {
        const abs = Math.abs(buf[i]);
        if (abs > maxAmplitude) maxAmplitude = abs;
        rmsSum += buf[i] * buf[i];
        sampleCount++;
      }
    }
    const rms = sampleCount > 0 ? Math.sqrt(rmsSum / sampleCount) : 0;

    console.log(
      `[${this.meetingId}] Audio buffer: ${durationSec.toFixed(1)}s ` +
      `(${this.audioBuffer.length} chunks, ${totalSamples} samples) ` +
      `peak=${maxAmplitude.toFixed(4)} rms=${rms.toFixed(4)}`
    );
    this.audioBuffer = [];
  }

  async stop(): Promise<void> {
    this.running = false;

    this.audioBuffer.length = 0;
    this.audioBufferSamples = 0;

    if (this.flushInterval) {
      clearInterval(this.flushInterval);
      this.flushInterval = null;
    }

    if (this.transcriber) {
      try {
        await new Promise<void>((resolve, reject) => {
          this.transcriber.stopTranscribingAsync(resolve, reject);
        });
      } catch (err: any) {
        console.error(`[${this.meetingId}] Error stopping transcriber:`, err.message);
      }
      this.transcriber = null;
    }

    if (this.recognizer) {
      try {
        await new Promise<void>((resolve, reject) => {
          this.recognizer.stopContinuousRecognitionAsync(resolve, reject);
        });
      } catch (err: any) {
        console.error(`[${this.meetingId}] Error stopping recognizer:`, err.message);
      }
      this.recognizer = null;
    }

    if (this.pushStream) {
      this.pushStream.close();
      this.pushStream = null;
    }

    this.useAzureSpeech = false;
    console.log(`[${this.meetingId}] Transcription stopped`);
  }
}

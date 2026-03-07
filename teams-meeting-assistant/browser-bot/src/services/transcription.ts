import { PythonBackendClient, TranscriptSegment } from "./python-backend.js";

/**
 * Buffers audio data, runs speech recognition, and sends transcript
 * segments to the Python backend.
 *
 * Uses Azure Speech SDK for real-time transcription. Falls back to
 * buffered batch mode if the SDK isn't available.
 */
export class TranscriptionService {
  private backend: PythonBackendClient;
  private meetingId: string;
  private sequenceNumber = 0;
  private activeSpeakerId = "";
  private activeSpeakerName = "Unknown";
  private running = false;

  // Audio buffer for batch processing
  private audioBuffer: Float32Array[] = [];
  private flushInterval: ReturnType<typeof setInterval> | null = null;

  // Azure Speech SDK recognizer (lazy-loaded)
  private recognizer: any = null;
  private useAzureSpeech = false;

  constructor(backend: PythonBackendClient, meetingId: string) {
    this.backend = backend;
    this.meetingId = meetingId;
  }

  async start(): Promise<void> {
    this.running = true;

    // Try to initialize Azure Speech SDK
    try {
      const sdk = await import("microsoft-cognitiveservices-speech-sdk");
      const speechKey = process.env.AZURE_SPEECH_KEY;
      const speechRegion = process.env.AZURE_SPEECH_REGION;

      if (speechKey && speechRegion) {
        const speechConfig = sdk.SpeechConfig.fromSubscription(
          speechKey,
          speechRegion
        );
        speechConfig.speechRecognitionLanguage = "en-US";

        // Use push stream so we can feed PCM data directly
        const pushStream = sdk.AudioInputStream.createPushStream(
          sdk.AudioStreamFormat.getWaveFormatPCM(16000, 16, 1)
        );
        const audioConfig = sdk.AudioConfig.fromStreamInput(pushStream);

        this.recognizer = new sdk.SpeechRecognizer(speechConfig, audioConfig);
        this.useAzureSpeech = true;

        // Store pushStream for feeding audio
        (this as any)._pushStream = pushStream;

        this.recognizer.recognized = (
          _sender: any,
          event: any
        ) => {
          if (
            event.result.reason === sdk.ResultReason.RecognizedSpeech &&
            event.result.text
          ) {
            this.emitSegment(event.result.text, event.result.duration / 10000000, true);
          }
        };

        this.recognizer.recognizing = (
          _sender: any,
          event: any
        ) => {
          // Partial results — don't send to backend (is_final = false)
        };

        await new Promise<void>((resolve, reject) => {
          this.recognizer.startContinuousRecognitionAsync(resolve, reject);
        });
        console.log(`[${this.meetingId}] Azure Speech SDK initialized`);
        return;
      }
    } catch {
      // Azure Speech SDK not available — fall through to buffer mode
    }

    // Fallback: buffer audio and send periodic silence-delimited chunks
    console.log(
      `[${this.meetingId}] Azure Speech SDK not available — using buffer mode. ` +
      `Set AZURE_SPEECH_KEY and AZURE_SPEECH_REGION for real-time transcription.`
    );
    this.flushInterval = setInterval(() => this.flushBuffer(), 5000);
  }

  pushAudio(pcmData: Float32Array): void {
    if (!this.running) return;

    if (this.useAzureSpeech && (this as any)._pushStream) {
      // Convert Float32 [-1,1] to Int16 PCM for Azure Speech SDK
      const int16 = new Int16Array(pcmData.length);
      for (let i = 0; i < pcmData.length; i++) {
        const s = Math.max(-1, Math.min(1, pcmData[i]));
        int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      }
      (this as any)._pushStream.write(int16.buffer);
    } else {
      this.audioBuffer.push(pcmData);
    }
  }

  setActiveSpeaker(speakerId: string, speakerName: string): void {
    this.activeSpeakerId = speakerId;
    this.activeSpeakerName = speakerName;
  }

  private emitSegment(
    text: string,
    durationSec: number,
    isFinal: boolean
  ): void {
    const segment: TranscriptSegment = {
      sequence: this.sequenceNumber++,
      speakerId: this.activeSpeakerId,
      speakerName: this.activeSpeakerName,
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

  private flushBuffer(): void {
    if (this.audioBuffer.length === 0) return;

    // In buffer mode without Azure Speech SDK, we can't transcribe locally.
    // Log the buffered audio size for debugging.
    const totalSamples = this.audioBuffer.reduce(
      (sum, buf) => sum + buf.length,
      0
    );
    const durationSec = totalSamples / 16000;
    console.log(
      `[${this.meetingId}] Audio buffer: ${durationSec.toFixed(1)}s ` +
      `(${this.audioBuffer.length} chunks, ${totalSamples} samples) — ` +
      `needs Azure Speech SDK for transcription`
    );
    this.audioBuffer = [];
  }

  async stop(): Promise<void> {
    this.running = false;

    if (this.flushInterval) {
      clearInterval(this.flushInterval);
      this.flushInterval = null;
    }

    if (this.recognizer) {
      try {
        await new Promise<void>((resolve, reject) => {
          this.recognizer.stopContinuousRecognitionAsync(resolve, reject);
        });
      } catch (err: any) {
        console.error(
          `[${this.meetingId}] Error stopping recognizer:`,
          err.message
        );
      }
      this.recognizer = null;
    }

    if ((this as any)._pushStream) {
      (this as any)._pushStream.close();
      (this as any)._pushStream = null;
    }

    console.log(`[${this.meetingId}] Transcription stopped`);
  }
}

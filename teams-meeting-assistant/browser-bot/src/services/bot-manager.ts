import { chromium, Browser, BrowserContext } from "playwright";
import { v4 as uuidv4 } from "uuid";
import os from "os";
import { joinTeamsMeeting } from "../platforms/msteams/join.js";
import { startAudioCapture } from "../platforms/msteams/audio-capture.js";
import { startSpeakerDetection } from "../platforms/msteams/speaker-detection.js";
import { PythonBackendClient } from "./python-backend.js";
import { TranscriptionService } from "./transcription.js";

export interface BotManagerConfig {
  pythonBackendUrl: string;
  hmacSecret: string;
  botName: string;
}

interface ActiveMeeting {
  meetingId: string;
  callId: string;
  context: BrowserContext;
  transcription: TranscriptionService;
  backend: PythonBackendClient;
  cleanup: () => Promise<void>;
}

export class BotManager {
  static readonly MAX_MEETINGS = 5;

  private config: BotManagerConfig;
  private browser: Browser | null = null;
  private meetings = new Map<string, ActiveMeeting>();

  constructor(config: BotManagerConfig) {
    this.config = config;
  }

  get activeMeetingCount(): number {
    return this.meetings.size;
  }

  get canAccept(): boolean {
    return this.meetings.size < BotManager.MAX_MEETINGS;
  }

  private async ensureBrowser(): Promise<Browser> {
    if (!this.browser || !this.browser.isConnected()) {
      this.browser = await chromium.launch({
        headless: true,
        args: [
          "--no-sandbox",
          "--disable-setuid-sandbox",
          "--use-fake-ui-for-media-stream",
          "--use-fake-device-for-media-stream",
          "--disable-web-security",
          "--allow-running-insecure-content",
          "--autoplay-policy=no-user-gesture-required",
        ],
      });
      console.log("Browser launched");
    }
    return this.browser;
  }

  async joinMeeting(meetingId: string, joinUrl: string): Promise<string> {
    if (this.meetings.has(meetingId)) {
      throw new Error(`Already in meeting ${meetingId}`);
    }

    const callId = `browser-${uuidv4().slice(0, 12)}`;
    const botInstanceId = `browser-bot-${os.hostname()}`;

    const backend = new PythonBackendClient(
      this.config.pythonBackendUrl,
      this.config.hmacSecret,
      botInstanceId
    );

    const browser = await this.ensureBrowser();
    const context = await browser.newContext({
      permissions: ["microphone", "camera"],
      userAgent:
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
      viewport: { width: 1280, height: 720 },
    });

    const page = await context.newPage();

    try {
      // Step 1: Join the Teams meeting via browser
      console.log(`[${meetingId}] Joining Teams meeting...`);
      await joinTeamsMeeting(page, joinUrl, this.config.botName);
      console.log(`[${meetingId}] Joined meeting`);

      // Step 2: Start audio capture (hooks RTCPeerConnection)
      console.log(`[${meetingId}] Starting audio capture...`);
      const audioStream = await startAudioCapture(page);
      console.log(`[${meetingId}] Audio capture started`);

      // Step 3: Start transcription service
      const transcription = new TranscriptionService(backend, meetingId);
      await transcription.start();

      // Step 4: Wire audio data to transcription
      audioStream.onAudioData((pcmData: Float32Array) => {
        transcription.pushAudio(pcmData);
      });

      // Step 5: Start speaker detection from DOM
      console.log(`[${meetingId}] Starting speaker detection...`);
      startSpeakerDetection(page, (speakerId, speakerName, isSpeaking) => {
        if (isSpeaking) {
          transcription.setActiveSpeaker(speakerId, speakerName);
        }
      });

      // Step 6: Notify Python backend (non-fatal — don't fail the join if backend is unreachable)
      try {
        await backend.sendLifecycleEvent(meetingId, "bot_joined");
        console.log(`[${meetingId}] Backend notified: bot_joined`);
      } catch (err: any) {
        console.warn(`[${meetingId}] Backend notification failed (non-fatal): ${err.message}`);
      }
      console.log(`[${meetingId}] Bot joined, callId=${callId}`);

      const cleanup = async () => {
        try {
          audioStream.stop();
          await transcription.stop();
          await backend.sendLifecycleEvent(meetingId, "meeting_ended");
        } catch (err: any) {
          console.error(`[${meetingId}] Cleanup error:`, err.message);
        } finally {
          await context.close().catch(() => {});
          this.meetings.delete(meetingId);
        }
      };

      // Monitor for meeting end (page closed, navigated away, etc.)
      page.on("close", () => {
        console.log(`[${meetingId}] Page closed — cleaning up`);
        cleanup();
      });

      this.meetings.set(meetingId, {
        meetingId,
        callId,
        context,
        transcription,
        backend,
        cleanup,
      });

      return callId;
    } catch (err) {
      await context.close().catch(() => {});
      throw err;
    }
  }

  async leaveMeeting(callId: string): Promise<void> {
    for (const [, meeting] of this.meetings) {
      if (meeting.callId === callId) {
        await meeting.cleanup();
        return;
      }
    }
    throw new Error(`No active meeting with callId ${callId}`);
  }

  async shutdown(): Promise<void> {
    for (const [, meeting] of this.meetings) {
      await meeting.cleanup();
    }
    if (this.browser) {
      await this.browser.close();
      this.browser = null;
    }
  }
}

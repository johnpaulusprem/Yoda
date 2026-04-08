import { chromium, Browser, BrowserContext, Page } from "playwright";
import { v4 as uuidv4 } from "uuid";
import os from "os";
import { joinTeamsMeeting, LobbyDeniedError } from "../platforms/msteams/join.js";
import { startAudioCapture } from "../platforms/msteams/audio-capture.js";
import { startSpeakerDetection } from "../platforms/msteams/speaker-detection.js";
import { startCaptionCapture, CaptionStream } from "../platforms/msteams/caption-capture.js";
import { PythonBackendClient } from "./python-backend.js";
import { TranscriptionService } from "./transcription.js";
import { logger } from "../utils/logger.js";
import { meetingsActive, joinDurationSeconds, errorsTotal, audioSilenceAlertsTotal } from "../utils/metrics.js";

export interface BotManagerConfig {
  pythonBackendUrl: string;
  hmacSecret: string;
  botName: string;
}

interface ActiveMeeting {
  meetingId: string;
  callId: string;
  context: BrowserContext;
  page: Page;
  transcription: TranscriptionService;
  backend: PythonBackendClient;
  cleanup: () => Promise<void>;
  stopSpeakerDetection: (() => void) | null;
  stopParticipantMonitor: (() => void) | null;
  captionStream: CaptionStream | null;
}

export class BotManager {
  static readonly MAX_MEETINGS = 5;

  private config: BotManagerConfig;
  private browser: Browser | null = null;
  private meetings = new Map<string, ActiveMeeting>();
  private browserCreatedAt = 0;
  private meetingsSinceBrowserLaunch = 0;

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

    if (!this.browser || !this.browser.isConnected()) {
      // Use Chrome's new headless mode (not Playwright's headless shell).
      // The old headless shell has no audio pipeline — WebRTC tracks stay muted.
      // New headless mode (--headless=new via channel: "chrome") supports audio.
      // In Docker with Xvfb: use headed mode for maximum compatibility.
      // Set HEADED=true to force headed mode (visible browser window).
      const useHeaded = !!process.env.DISPLAY || process.env.HEADED === "true";
      this.browser = await chromium.launch({
        headless: !useHeaded,
        // Use installed Chrome when available (supports audio rendering via new headless mode).
        // On ARM64 (e.g. Apple Silicon Docker), Chrome isn't available — use bundled Chromium.
        channel: process.env.PLAYWRIGHT_CHROMIUM_CHANNEL || (process.arch === "arm64" ? undefined : "chrome"),
        ignoreDefaultArgs: ["--mute-audio"],
        args: [
          "--no-sandbox",
          "--disable-setuid-sandbox",
          "--disable-dev-shm-usage",
          "--use-fake-ui-for-media-stream",
          "--use-fake-device-for-media-stream",
          "--autoplay-policy=no-user-gesture-required",
          "--enable-audio-service",
        ],
      });
      this.browserCreatedAt = Date.now();
      this.meetingsSinceBrowserLaunch = 0;
      logger.info(`Browser launched (${useHeaded ? "headed + Xvfb" : "chrome headless"})`);
      this.browser.on("disconnected", () => {
        logger.error("Browser disconnected unexpectedly — cleaning up all meetings");
        this.browser = null;
        // Snapshot meetings to avoid iterator invalidation during async cleanup
        const snapshot = [...this.meetings.values()];
        for (const meeting of snapshot) {
          meeting.cleanup().catch(() => {});
        }
      });
    }
    return this.browser;
  }

  /**
   * Monitors participant count in the meeting. When the bot is the only
   * participant remaining for ALONE_THRESHOLD_MS, triggers auto-leave.
   * ScreenApp pattern: prevents the bot from lingering in empty meetings.
   */
  private startParticipantMonitor(
    page: Page,
    meetingId: string,
    onAlone: () => void
  ): () => void {
    const POLL_INTERVAL_MS = 30_000;
    const ALONE_THRESHOLD_MS = 120_000; // 2 min alone → auto-leave
    let aloneStartedAt: number | null = null;
    let unknownCount = 0; // Track consecutive "unknown" readings

    const interval = setInterval(async () => {
      try {
        const participantCount = await page.evaluate(() => {
          // Check if meeting has ended (Teams shows a post-meeting screen)
          const endedIndicators = [
            '[data-tid="meeting-ended"]',
            '[data-tid="call-ended"]',
            '[data-tid="rejoin-button"]',
            '[data-tid="post-call-screen"]',
          ];
          for (const sel of endedIndicators) {
            if (document.querySelector(sel)) return 0;
          }

          // Also check for "You left the meeting" or similar text
          const bodyText = document.body?.innerText || "";
          if (
            bodyText.includes("left the meeting") ||
            bodyText.includes("meeting has ended") ||
            bodyText.includes("call has ended") ||
            bodyText.includes("Rejoin")
          ) {
            return 0;
          }

          // Strategy 1: People button badge (Teams shows participant count)
          const badge =
            document.querySelector('[data-tid="people-button"] [data-tid="notification-badge"]') ||
            document.querySelector('[data-tid="roster-button"] [data-tid="notification-badge"]');
          if (badge?.textContent) {
            const count = parseInt(badge.textContent.trim(), 10);
            if (!isNaN(count)) return count;
          }
          // Strategy 2: Roster list items
          const rosterItems = document.querySelectorAll(
            '[data-tid="roster-participant"], [data-tid="participant-item"]'
          );
          if (rosterItems.length > 0) return rosterItems.length;
          // Strategy 3: Video tiles (at least captures visible participants)
          const videoTiles = document.querySelectorAll('[data-tid="video-tile"]');
          if (videoTiles.length > 0) return videoTiles.length;
          return -1; // Unknown
        });

        if (participantCount === -1) {
          unknownCount++;
          // Log but do NOT treat as alone — only leave when we positively
          // confirm no other participants are present.
          if (unknownCount % 5 === 0) {
            logger.info(`[${meetingId}] Participant count unknown for ${unknownCount} consecutive polls — staying in meeting`);
          }
          return;
        }

        unknownCount = 0; // Reset on valid reading

        if (participantCount <= 1) {
          if (!aloneStartedAt) {
            aloneStartedAt = Date.now();
            logger.info(`[${meetingId}] Bot appears to be alone (${participantCount} participants)`);
          } else if (Date.now() - aloneStartedAt >= ALONE_THRESHOLD_MS) {
            logger.info(
              `[${meetingId}] Bot has been alone for ${ALONE_THRESHOLD_MS / 1000}s — auto-leaving`
            );
            clearInterval(interval);
            onAlone();
          }
        } else {
          if (aloneStartedAt) {
            logger.info(`[${meetingId}] Other participants detected (${participantCount}) — resetting alone timer`);
          }
          aloneStartedAt = null;
        }
      } catch {
        // Page may have closed
        clearInterval(interval);
      }
    }, POLL_INTERVAL_MS);

    return () => clearInterval(interval);
  }

  async joinMeeting(meetingId: string, joinUrl: string): Promise<string> {
    const joinStartedAt = Date.now();

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

    // Forward browser console logs to Node.js (ScreenApp pattern)
    // Filter out noisy Teams-internal errors that are harmless for anonymous bots
    const TEAMS_NOISE_PATTERNS = [
      "RenderingContextManager",
      "CoreSettings/EcsParameters",
      "ErrorStateProvider",
      "AtpSafelinks",
      "ConversationFolderManager",
      "i18n: failed to import",
      "resolverUncaughtErrorBoundary",
      "TrouterService",
      "Failed to load resource",
      "live-persona-card",
      "DUPLICATE_POLICY_FOUND",
      "useConsumptionHorizon",
      "consumptionHorizon",
    ];

    page.on("console", (msg) => {
      const type = msg.type();
      const text = msg.text();
      if (type === "error") {
        // Suppress known Teams-internal noise (401s, i18n, GraphQL, etc.)
        if (TEAMS_NOISE_PATTERNS.some((p) => text.includes(p))) return;
        logger.error(`[${meetingId}][browser] ${text}`);
      } else if (type === "warning") {
        logger.warn(`[${meetingId}][browser] ${text}`);
      } else if (text.includes("[YodaBot]")) {
        // Always surface our own logs
        logger.info(`[${meetingId}][browser] ${text}`);
      }
    });

    try {
      // Step 1: Join the Teams meeting via browser
      logger.info(`[${meetingId}] Joining Teams meeting...`);
      await joinTeamsMeeting(page, joinUrl, this.config.botName);
      joinDurationSeconds.observe((Date.now() - joinStartedAt) / 1000);
      logger.info(`[${meetingId}] Joined meeting`);

      // Step 2: Start audio capture (hooks RTCPeerConnection)
      logger.info(`[${meetingId}] Starting audio capture...`);
      const audioStream = await startAudioCapture(page);
      logger.info(`[${meetingId}] Audio capture started`);

      // Step 3: Start transcription service
      const transcription = new TranscriptionService(backend, meetingId);
      await transcription.start();

      // Step 4: Wire audio data to transcription
      audioStream.onAudioData((pcmData: Float32Array) => {
        transcription.pushAudio(pcmData);
      });

      audioStream.onSilence((silenceSeconds: number) => {
        // Silence is normal in meetings (muted participants, screen sharing,
        // reading, etc.). Only log at debug level — never treat as an error.
        if (silenceSeconds % 60 === 0) {
          logger.debug("Audio silent", { meetingId, silenceSeconds });
        }
      });

      // Step 5: Start speaker detection from DOM (Vexa-style)
      logger.info(`[${meetingId}] Starting speaker detection...`);
      const stopSpeakerDetection = startSpeakerDetection(
        page,
        // Legacy callback — sets the current active speaker in transcription service
        (speakerId, speakerName, isSpeaking) => {
          if (isSpeaking) {
            transcription.setActiveSpeaker(speakerId, speakerName);
          }
        },
        // New Vexa-style SPEAKER_START/SPEAKER_END event callback
        (event) => {
          // Feed events into transcription service for overlap-based mapping
          transcription.pushSpeakerEvent(event);

          // Also send to Python backend for server-side storage/mapping
          backend
            .sendSpeakerEvent(
              meetingId,
              event.eventType,
              event.participantId,
              event.participantName,
              event.relativeTimestampMs
            )
            .catch((err) => {
              // Non-fatal: speaker events are best-effort
              logger.debug(`[${meetingId}] Speaker event send failed: ${err.message}`);
            });
        }
      );

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

      // Step 6: Notify Python backend (non-fatal — don't fail the join if backend is unreachable)
      try {
        await backend.sendLifecycleEvent(meetingId, "bot_joined", { join_url: joinUrl });
        logger.info(`[${meetingId}] Backend notified: bot_joined`);
      } catch (err: any) {
        logger.warn(`[${meetingId}] Backend notification failed (non-fatal): ${err.message}`);
      }
      logger.info(`[${meetingId}] Bot joined, callId=${callId}`);

      let cleaned = false;
      let stopParticipantMonitor: (() => void) | null = null;
      const onPageClose = () => {
        logger.info(`[${meetingId}] Page closed — cleaning up`);
        cleanup();
      };
      const onPageCrash = () => {
        logger.error(`[${meetingId}] Page CRASHED — cleaning up`);
        cleanup();
      };
      const cleanup = async () => {
        if (cleaned) return;
        cleaned = true;
        // Remove page listeners to prevent re-entry during context.close()
        page.removeListener("close", onPageClose);
        page.removeListener("crash", onPageCrash);
        try {
          if (captionStream) await captionStream.stop();
          if (stopParticipantMonitor) stopParticipantMonitor();
          stopSpeakerDetection();
          await audioStream.stop();
          await transcription.stop();
          await backend.sendLifecycleEvent(meetingId, "meeting_ended");
        } catch (err: any) {
          logger.error(`[${meetingId}] Cleanup error`, { error: err.message });
        } finally {
          await context.close().catch(() => {});
          this.meetings.delete(meetingId);
          meetingsActive.set(this.meetings.size);
        }
      };

      // Step 7: Start participant monitoring (auto-leave when bot is alone)
      stopParticipantMonitor = this.startParticipantMonitor(page, meetingId, () => {
        cleanup();
      });

      // Monitor for meeting end (page closed, navigated away, crashed)
      page.on("close", onPageClose);
      page.on("crash", onPageCrash);

      this.meetings.set(meetingId, {
        meetingId,
        callId,
        context,
        page,
        transcription,
        backend,
        cleanup,
        stopSpeakerDetection,
        stopParticipantMonitor,
        captionStream,
      });

      meetingsActive.set(this.meetings.size);
      this.meetingsSinceBrowserLaunch++;

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
    const SHUTDOWN_TIMEOUT_MS = 15_000;
    logger.info(`Shutting down ${this.meetings.size} active meetings...`);

    const shutdownWork = async () => {
      // Step 1: Attempt graceful cleanup for each meeting, but don't let one failure block others
      const cleanupPromises = [...this.meetings.values()].map(async (meeting) => {
        try {
          await Promise.race([
            meeting.cleanup(),
            new Promise((_, reject) =>
              setTimeout(() => reject(new Error("Cleanup timeout")), 5000)
            ),
          ]);
        } catch (err: any) {
          logger.error(`[${meeting.meetingId}] Shutdown cleanup failed: ${err.message}`);
        }
      });
      await Promise.allSettled(cleanupPromises);

      // Step 2: Force-close any browser contexts that may still be open
      if (this.browser?.isConnected()) {
        const contexts = this.browser.contexts();
        await Promise.allSettled(
          contexts.map((ctx) => ctx.close().catch(() => {}))
        );
      }

      // Step 3: Close the browser itself
      if (this.browser) {
        try {
          await this.browser.close();
        } catch (err: any) {
          logger.error("Browser close failed", { error: err.message });
        }
        this.browser = null;
      }

      this.meetings.clear();
    };

    // Race shutdown work against a timeout to prevent hanging indefinitely
    await Promise.race([
      shutdownWork(),
      new Promise<void>((resolve) =>
        setTimeout(() => {
          logger.error(`Shutdown timed out after ${SHUTDOWN_TIMEOUT_MS}ms — forcing browser close`);
          if (this.browser) {
            this.browser.close().catch(() => {});
            this.browser = null;
          }
          this.meetings.clear();
          resolve();
        }, SHUTDOWN_TIMEOUT_MS)
      ),
    ]);
    logger.info("Shutdown complete");
  }
}

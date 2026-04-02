import { Page } from "playwright";
import path from "path";
import { logger } from "../../utils/logger.js";

export class LobbyDeniedError extends Error {
  constructor(message = "Bot was denied access to the meeting") {
    super(message);
    this.name = "LobbyDeniedError";
  }
}

const LOBBY_DENIAL_TEXTS = [
  "Sorry, but you were denied access to the meeting",
  "you were denied access",
  "request to join was denied",
  "meeting organizer didn't let you in",
];

const DEBUG_DIR = process.env.DEBUG_SCREENSHOT_DIR || "./debug-screenshots";
const ENABLE_DEBUG = process.env.ENABLE_DEBUG_SCREENSHOTS === "true";

async function debugScreenshot(page: Page, name: string): Promise<void> {
  if (!ENABLE_DEBUG) return;
  try {
    const { mkdirSync } = await import("fs");
    mkdirSync(DEBUG_DIR, { recursive: true });
    const filePath = path.join(DEBUG_DIR, `${name}.png`);
    await page.screenshot({ path: filePath, fullPage: true });
    logger.info(`[DEBUG] Screenshot saved: ${filePath}`);
  } catch (err: any) {
    logger.info(`[DEBUG] Screenshot failed: ${err.message}`);
  }
}

/**
 * Joins a Teams meeting via browser automation.
 *
 * Critical learnings from Vexa AI, ScreenApp, and industry research:
 * 1. Hook RTCPeerConnection BEFORE navigation
 * 2. "Computer audio" MUST be selected — otherwise no WebRTC audio at all
 * 3. Do NOT mute mic on pre-join screen — risks deselecting "Computer audio"
 * 4. Mute mic AFTER joining via keyboard shortcut (Ctrl+Shift+M)
 * 5. Unmute all <audio> elements after joining to ensure playback
 * 6. Use role-based selectors (getByRole) — more resilient to UI changes
 * 7. Use generous timeouts — Teams pre-join can take 60-120s to load
 */
export async function joinTeamsMeeting(
  page: Page,
  joinUrl: string,
  botName: string
): Promise<void> {
  // Polyfill: tsx/esbuild with keepNames injects __name() calls that reference a
  // module-scope helper. Inside page.evaluate/addInitScript the module scope doesn't
  // exist, causing "ReferenceError: __name is not defined". Injecting __name as a
  // global via a *string* (not a callback) prevents esbuild from transforming it.
  await page.addInitScript(`
    if (typeof globalThis.__name === "undefined") {
      globalThis.__defProp = Object.defineProperty;
      globalThis.__name = function(target, value) {
        return globalThis.__defProp(target, "name", { value: value, configurable: true });
      };
    }
  `);

  // Anti-webdriver detection (Recall AI pattern)
  // Prevents Teams from detecting Playwright automation via navigator.webdriver
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "webdriver", { get: () => false });
  });

  // Hook RTCPeerConnection BEFORE navigating — this is critical.
  // When Teams establishes WebRTC, our hook captures remote audio tracks
  // and mirrors them into hidden <audio> elements for later capture.
  await page.addInitScript(() => {
    const OrigRTC = window.RTCPeerConnection;

    // Store all peer connections for inspection
    (window as any).__rtcConnections = [];
    (window as any).__rtcAudioTrackCount = 0;

    const PatchedRTC = function (
      this: RTCPeerConnection,
      config?: RTCConfiguration
    ) {
      const pc = new OrigRTC(config);
      (window as any).__rtcConnections.push(pc);
      // Prune closed connections to prevent memory leaks
      (window as any).__rtcConnections = (window as any).__rtcConnections.filter(
        (c: RTCPeerConnection) => c.connectionState !== "closed"
      );

      pc.addEventListener("track", (event: RTCTrackEvent) => {
        if (event.track.kind === "audio") {
          (window as any).__rtcAudioTrackCount++;
          // Mirror remote audio track into a hidden <audio> element
          const audio = document.createElement("audio");
          audio.id = `rtc-audio-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
          audio.autoplay = true;
          audio.muted = false;
          // Volume must be > 0 for Chrome to keep the audio pipeline alive.
          // Setting volume=0 causes Chrome to optimize away audio data, resulting
          // in MediaStreamSource receiving silence. We use a near-zero volume here
          // (inaudible) and the Web Audio GainNode in audio-capture.ts handles
          // proper silence of speaker output.
          audio.volume = 0.01;
          audio.setAttribute("data-rtc-track", "true");
          audio.srcObject = new MediaStream([event.track]);
          audio.style.display = "none";
          document.body.appendChild(audio);
          // Force play to ensure audio flows
          audio.play().catch(() => {});
          console.log(`[YodaBot] Captured remote audio track #${(window as any).__rtcAudioTrackCount} → ${audio.id}`);
          // Clean up when track ends to prevent memory leaks
          event.track.onended = () => {
            console.log(`[YodaBot] Track ended, removing ${audio.id}`);
            audio.srcObject = null;
            audio.remove();
          };
        }
      });

      return pc;
    } as unknown as typeof RTCPeerConnection;

    PatchedRTC.prototype = OrigRTC.prototype;
    Object.defineProperty(PatchedRTC, "name", { value: "RTCPeerConnection" });
    (window as any).RTCPeerConnection = PatchedRTC;
  });

  // Pre-resolve the meeting URL server-side (Recall AI pattern)
  // Teams short URLs (e.g. /meet/123) redirect to the full join URL.
  // By resolving the redirect and adding suppressPrompt=true, we skip
  // the "open in Teams app" interstitial entirely — more reliable than clicking through it.
  let resolvedUrl = joinUrl;
  try {
    const response = await fetch(joinUrl, { redirect: "follow" });
    const finalUrl = new URL(response.url);
    finalUrl.searchParams.set("msLaunch", "false");
    finalUrl.searchParams.set("suppressPrompt", "true");
    finalUrl.searchParams.set("directDl", "true");
    finalUrl.searchParams.set("enableMobilePage", "true");
    resolvedUrl = finalUrl.toString();
    logger.info(`Pre-resolved URL: ${joinUrl} → ${resolvedUrl}`);
  } catch (err: any) {
    logger.warn(`URL pre-resolution failed (non-fatal): ${err.message} — using original URL`);
  }

  // Navigate to the (pre-resolved) meeting join URL
  logger.info(`Navigating to join URL...`);
  await page.goto(resolvedUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
  await debugScreenshot(page, "01-after-navigation");

  // Step 1: Click "Continue on this browser" / "Join from browser"
  // With suppressPrompt=true this step is often skipped, but we keep it
  // as a fallback in case pre-resolution didn't fully suppress the dialog.
  const continueSelectors = [
    'button[aria-label="Join meeting from this browser"]',
    'button[aria-label="Continue on this browser"]',
    'button[aria-label="Join on this browser"]',
    'button:has-text("Continue on this browser")',
    'button:has-text("Join from browser")',
    'a:has-text("Continue on this browser")',
    '[data-tid="joinOnWeb"]',
  ];

  let continueClicked = false;
  for (const selector of continueSelectors) {
    try {
      const btn = page.locator(selector).first();
      await btn.waitFor({ timeout: continueClicked ? 1000 : 5000 }); // Shorter timeout since suppressPrompt usually works
      await btn.click({ force: true });
      continueClicked = true;
      logger.info(`Clicked continue button: ${selector}`);
      break;
    } catch {
      continue;
    }
  }
  if (!continueClicked) {
    logger.info("No 'Continue on this browser' prompt — suppressPrompt worked or already on pre-join page");
  }
  await debugScreenshot(page, "02-after-continue");

  // Step 2: Wait for pre-join screen and set bot name
  // Use the specific Teams data-tid selector (most reliable per ScreenApp),
  // with generous timeout — Teams can take 60-120s to load the pre-join screen.
  try {
    const nameInput = page.locator('input[data-tid="prejoin-display-name-input"]');
    await nameInput.waitFor({ state: "visible", timeout: 120000 });
    logger.info("Pre-join screen loaded — name input visible");
    await debugScreenshot(page, "03-prejoin-screen");

    await nameInput.click();
    await nameInput.fill("");
    await nameInput.fill(botName);
    // Verify the name was actually set
    const nameValue = await nameInput.inputValue();
    logger.info(`Set bot name to "${botName}" (verified: "${nameValue}")`);
    if (!nameValue) {
      // Fallback: type character by character
      await nameInput.click();
      await page.keyboard.type(botName, { delay: 50 });
      logger.info(`Typed bot name character by character`);
    }
    await page.waitForTimeout(1000); // Let Teams process the name
  } catch {
    // Fallback to broader selectors if data-tid not found
    logger.info("data-tid name input not found — trying fallback selectors");
    try {
      const fallbackInput = page.locator(
        '#username, ' +
        'input[placeholder*="name" i], ' +
        'input[placeholder*="Type your name" i]'
      ).first();
      await fallbackInput.waitFor({ timeout: 10000 });
      await fallbackInput.click();
      await fallbackInput.fill(botName);
      logger.info(`Set bot name via fallback selector`);
    } catch {
      logger.info("Name input not found — may be logged in already");
    }
    await debugScreenshot(page, "03-prejoin-screen");
  }

  // Step 3: Ensure "Computer audio" is selected — THIS IS CRITICAL
  // Without "Computer audio", Teams won't establish a WebRTC audio connection,
  // meaning we get NO remote audio tracks at all.
  try {
    const computerAudio = page.locator(
      'text="Computer audio", ' +
      '[data-tid="prejoin-audio-computer"], ' +
      'input[value="computer-audio"], ' +
      'label:has-text("Computer audio")'
    );
    const audioOption = computerAudio.first();
    if (await audioOption.isVisible({ timeout: 3000 })) {
      await audioOption.click();
      logger.info("Ensured 'Computer audio' is selected");
    } else {
      logger.info("'Computer audio' option not visible — may already be selected or different UI");
    }
  } catch {
    logger.info("Could not find 'Computer audio' option — proceeding with current audio state");
  }

  // Step 4: Disable camera only — do NOT touch the microphone toggle on pre-join
  // Muting mic on pre-join risks deselecting "Computer audio" entirely,
  // which would kill the WebRTC audio connection.
  try {
    const cameraSelectors = [
      'input[data-tid="toggle-video"][checked]',
      'input[type="checkbox"][title*="Turn camera off" i]',
      'input[role="switch"][data-tid="toggle-video"]',
      '[data-tid="toggle-video"]',
      'button[aria-label*="Turn camera off" i]',
      'button[aria-label*="Camera off" i]',
      'button[aria-label*="camera" i][aria-pressed="true"]',
      'button[aria-label*="video" i][aria-pressed="true"]',
    ];

    for (const selector of cameraSelectors) {
      const toggle = page.locator(selector).first();
      if (await toggle.isVisible({ timeout: 2000 }).catch(() => false)) {
        await toggle.click();
        logger.info(`Disabled camera via: ${selector}`);
        await page.waitForTimeout(500);
        break;
      }
    }
  } catch {
    logger.info("Camera toggle not found or already off");
  }

  await debugScreenshot(page, "04-before-join-click");

  // Step 5: Click "Join now" with retry (ScreenApp pattern: 3 attempts, 15s wait)
  // Retrying handles transient UI glitches where the button appears but isn't interactive yet.
  const JOIN_MAX_ATTEMPTS = 3;
  const JOIN_RETRY_WAIT_MS = 15_000;
  let inMeeting = false;

  for (let attempt = 1; attempt <= JOIN_MAX_ATTEMPTS; attempt++) {
    const joinTexts = ["Join now", "Join", "Ask to join", "Join meeting"];
    let joinClicked = false;

    for (const text of joinTexts) {
      try {
        const btn = page.getByRole("button", { name: new RegExp(text, "i") });
        if (await btn.isVisible({ timeout: 3000 }).catch(() => false)) {
          await btn.click();
          joinClicked = true;
          logger.info(`Clicked "${text}" button (attempt ${attempt}/${JOIN_MAX_ATTEMPTS})`);
          break;
        }
      } catch {
        continue;
      }
    }

    if (!joinClicked) {
      // Last resort: CSS selector fallback
      try {
        const fallbackJoin = page.locator(
          'button[data-tid="prejoin-join-button"]'
        ).first();
        await fallbackJoin.click({ timeout: 5000 });
        joinClicked = true;
        logger.info(`Clicked join via fallback CSS selector (attempt ${attempt}/${JOIN_MAX_ATTEMPTS})`);
      } catch {
        logger.info(`Join button not found (attempt ${attempt}/${JOIN_MAX_ATTEMPTS})`);
      }
    }

    // Step 5b: Check for lobby denial (ScreenApp pattern)
    // Teams shows a denial message if the organizer rejects the bot.
    try {
      const bodyText = await page.evaluate(() => document.body.innerText);
      for (const denialText of LOBBY_DENIAL_TEXTS) {
        if (bodyText.includes(denialText)) {
          await debugScreenshot(page, "05-lobby-denied");
          throw new LobbyDeniedError();
        }
      }
    } catch (err) {
      if (err instanceof LobbyDeniedError) throw err;
      // Ignore evaluate failures — page may still be loading
    }

    // Step 6: Wait for meeting to actually connect
    // ScreenApp pattern: look for Leave button via getByRole (most reliable)
    if (joinClicked) {
      try {
        const leaveButton = page.getByRole("button", { name: /Leave/i });
        await leaveButton.waitFor({ timeout: 60_000 }); // 1 min per attempt
        inMeeting = true;
        logger.info("Meeting joined successfully — Leave button visible");
        await debugScreenshot(page, "05-in-meeting");
        break; // Success — exit retry loop
      } catch {
        // Check lobby denial again after waiting
        try {
          const bodyText = await page.evaluate(() => document.body.innerText);
          for (const denialText of LOBBY_DENIAL_TEXTS) {
            if (bodyText.includes(denialText)) {
              await debugScreenshot(page, "05-lobby-denied");
              throw new LobbyDeniedError();
            }
          }
        } catch (err) {
          if (err instanceof LobbyDeniedError) throw err;
        }

        if (attempt < JOIN_MAX_ATTEMPTS) {
          logger.info(
            `Join attempt ${attempt}/${JOIN_MAX_ATTEMPTS} failed — waiting ${JOIN_RETRY_WAIT_MS / 1000}s before retry`
          );
          await page.waitForTimeout(JOIN_RETRY_WAIT_MS);
        } else {
          // Final attempt — proceed anyway (bot may be in meeting despite selector failure)
          inMeeting = true;
          logger.warn("Warning: Could not confirm meeting join via Leave button — proceeding anyway");
          await debugScreenshot(page, "05-join-uncertain");
        }
      }
    } else if (attempt < JOIN_MAX_ATTEMPTS) {
      logger.info(`Retrying join in ${JOIN_RETRY_WAIT_MS / 1000}s...`);
      await page.waitForTimeout(JOIN_RETRY_WAIT_MS);
    } else {
      // If we couldn't even click join after all attempts, still set inMeeting
      // in case the bot actually entered (e.g. auto-admitted meeting)
      inMeeting = true;
      logger.warn("Warning: Could not click join button — proceeding anyway");
      await debugScreenshot(page, "05-join-uncertain");
    }
  }

  // Step 6b: Dismiss any post-join dialogs (device check, notifications)
  // Teams sometimes shows popups after joining that can block interaction.
  try {
    const closeBtn = page.locator('button[aria-label="Close"], button[title="Close"]').first();
    if (await closeBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await closeBtn.click();
      logger.info("Dismissed post-join dialog");
    }
  } catch {
    // No dialog to dismiss — expected
  }

  // Step 7: After joining, mute mic via keyboard shortcut (Ctrl+Shift+M)
  // This is safe because the WebRTC audio connection is already established.
  // We still RECEIVE remote audio even when our mic is muted.
  if (inMeeting) {
    // Wait briefly for meeting UI to stabilize
    await page.waitForTimeout(2000);
    try {
      await page.keyboard.press("Control+Shift+m");
      logger.info("Muted microphone via Ctrl+Shift+M (after join)");
    } catch {
      logger.info("Failed to mute mic via keyboard — may already be muted");
    }
  }

  // Step 8: Ensure all <audio> elements are playing (but volume 0 to prevent speaker output).
  // The audio must be unmuted (audio.muted = false) for MediaStreamSource to receive data,
  // but volume = 0 prevents actual sound output. This is the key difference from --mute-audio
  // which blocks the entire pipeline.
  await page.evaluate(() => {
    document.querySelectorAll("audio").forEach((audio) => {
      audio.muted = false;
      // Volume must be > 0 for Chrome to keep the audio pipeline alive.
      // Near-zero volume is inaudible but keeps MediaStreamSource fed with real data.
      audio.volume = 0.01;
      audio.play().catch(() => {});
    });
    console.log(
      `[YodaBot] Activated ${document.querySelectorAll("audio").length} audio elements (volume=0.01), ` +
      `RTC tracks captured: ${(window as any).__rtcAudioTrackCount || 0}`
    );
  });

  // Step 9: Verify we have RTC audio tracks
  const rtcTrackCount = await page.evaluate(
    () => (window as any).__rtcAudioTrackCount || 0
  );
  logger.info(`[DEBUG] RTC audio tracks captured so far: ${rtcTrackCount}`);
  logger.info(`[DEBUG] Final URL: ${page.url()}`);
  logger.info(`[DEBUG] Final title: ${await page.title()}`);
}

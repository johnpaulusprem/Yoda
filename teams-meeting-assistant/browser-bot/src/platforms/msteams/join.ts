import { Page } from "playwright";
import path from "path";

const DEBUG_DIR = process.env.DEBUG_SCREENSHOT_DIR || "./debug-screenshots";

async function debugScreenshot(page: Page, name: string): Promise<void> {
  try {
    const { mkdirSync } = await import("fs");
    mkdirSync(DEBUG_DIR, { recursive: true });
    const filePath = path.join(DEBUG_DIR, `${name}.png`);
    await page.screenshot({ path: filePath, fullPage: true });
    console.log(`[DEBUG] Screenshot saved: ${filePath}`);
  } catch (err: any) {
    console.log(`[DEBUG] Screenshot failed: ${err.message}`);
  }
}

/**
 * Joins a Teams meeting via browser automation.
 * Based on the Vexa AI pattern: hook RTCPeerConnection BEFORE navigation,
 * then click through the pre-join UI.
 */
export async function joinTeamsMeeting(
  page: Page,
  joinUrl: string,
  botName: string
): Promise<void> {
  // Hook RTCPeerConnection BEFORE navigating — this is critical.
  // When Teams establishes WebRTC, our hook captures remote audio tracks
  // and mirrors them into hidden <audio> elements for later capture.
  await page.addInitScript(() => {
    const OrigRTC = window.RTCPeerConnection;
    const origAddTrack = OrigRTC.prototype.addTrack;
    const origSetRemote = OrigRTC.prototype.setRemoteDescription;

    // Store all peer connections for inspection
    (window as any).__rtcConnections = [];

    const PatchedRTC = function (
      this: RTCPeerConnection,
      config?: RTCConfiguration
    ) {
      const pc = new OrigRTC(config);
      (window as any).__rtcConnections.push(pc);

      pc.addEventListener("track", (event: RTCTrackEvent) => {
        if (event.track.kind === "audio") {
          // Mirror remote audio track into a hidden <audio> element
          const audio = document.createElement("audio");
          audio.id = `rtc-audio-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
          audio.autoplay = true;
          audio.setAttribute("data-rtc-track", "true");
          audio.srcObject = new MediaStream([event.track]);
          audio.style.display = "none";
          document.body.appendChild(audio);
          console.log(`[YodaBot] Captured remote audio track → ${audio.id}`);
        }
      });

      return pc;
    } as unknown as typeof RTCPeerConnection;

    PatchedRTC.prototype = OrigRTC.prototype;
    Object.defineProperty(PatchedRTC, "name", { value: "RTCPeerConnection" });
    (window as any).RTCPeerConnection = PatchedRTC;
  });

  // Navigate to the meeting join URL
  console.log(`Navigating to join URL...`);
  await page.goto(joinUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.waitForTimeout(2000);
  await debugScreenshot(page, "01-after-navigation");

  // Teams shows different pre-join flows. The browser (non-app) flow typically:
  // 1. "Continue on this browser" button
  // 2. Pre-join screen: name input, audio/video toggles, "Join now" button

  // Step 1: Click "Continue on this browser" (may not always appear)
  try {
    const continueBtn = page.locator(
      'button:has-text("Continue on this browser"), ' +
      'a:has-text("Continue on this browser"), ' +
      '[data-tid="joinOnWeb"]'
    );
    await continueBtn.first().click({ timeout: 15000 });
    console.log("Clicked 'Continue on this browser'");
    await page.waitForTimeout(2000);
    await debugScreenshot(page, "02-after-continue-btn");
  } catch {
    console.log("No 'Continue on this browser' prompt — already on pre-join page");
    await debugScreenshot(page, "02-no-continue-btn");
  }

  // Wait for pre-join screen to load
  await page.waitForTimeout(3000);
  await debugScreenshot(page, "03-prejoin-screen");

  // Step 2: Disable camera if toggle is available
  try {
    const cameraToggle = page.locator(
      '[data-tid="toggle-video"], ' +
      'button[aria-label*="camera" i][aria-pressed="true"], ' +
      'button[aria-label*="video" i][aria-pressed="true"]'
    );
    const toggle = cameraToggle.first();
    if (await toggle.isVisible({ timeout: 3000 })) {
      await toggle.click();
      console.log("Disabled camera");
    }
  } catch {
    console.log("Camera toggle not found or already off");
  }

  // Step 3: Disable microphone if toggle is available
  try {
    const micToggle = page.locator(
      '[data-tid="toggle-mute"], ' +
      'button[aria-label*="microphone" i][aria-pressed="true"], ' +
      'button[aria-label*="mic" i][aria-pressed="true"]'
    );
    const toggle = micToggle.first();
    if (await toggle.isVisible({ timeout: 3000 })) {
      await toggle.click();
      console.log("Disabled microphone");
    }
  } catch {
    console.log("Mic toggle not found or already muted");
  }

  // Step 4: Set bot name in the name input field
  try {
    const nameInput = page.locator(
      '#username, ' +
      'input[data-tid="prejoin-display-name-input"], ' +
      'input[placeholder*="name" i]'
    );
    const input = nameInput.first();
    if (await input.isVisible({ timeout: 5000 })) {
      await input.fill("");
      await input.fill(botName);
      console.log(`Set bot name to "${botName}"`);
    }
  } catch {
    console.log("Name input not found — may be logged in already");
  }

  // Step 5: Select "Computer audio" option if available (some pre-join UIs show audio device picker)
  try {
    const computerAudio = page.locator(
      'button:has-text("Computer audio"), ' +
      '[data-tid="prejoin-audio-computer"]'
    );
    if (await computerAudio.first().isVisible({ timeout: 3000 })) {
      await computerAudio.first().click();
      console.log("Selected 'Computer audio'");
    }
  } catch {
    console.log("Computer audio option not shown");
  }

  // Step 6: Click "Join now"
  const joinButton = page.locator(
    'button:has-text("Join now"), ' +
    'button[data-tid="prejoin-join-button"], ' +
    'button:has-text("Join meeting")'
  );
  await debugScreenshot(page, "04-before-join-click");
  await joinButton.first().click({ timeout: 15000 });
  console.log("Clicked 'Join now'");

  // Step 7: Wait for meeting to actually connect
  // Look for indicators that we're in the meeting (roster panel, call controls, etc.)
  try {
    await page.waitForSelector(
      '[data-tid="call-composite"], ' +
      '[data-tid="hangup-button"], ' +
      'button[aria-label*="Leave" i], ' +
      '[data-tid="roster-button"]',
      { timeout: 30000 }
    );
    console.log("Meeting joined successfully — call controls visible");
    await debugScreenshot(page, "05-in-meeting");
  } catch {
    // Even if we don't find specific controls, the meeting may still be joined.
    // The audio capture will confirm via RTCPeerConnection tracks.
    console.log("Warning: Could not confirm meeting join via DOM — proceeding anyway");
    await debugScreenshot(page, "05-join-uncertain");
  }

  // Log the current page URL and title for debugging
  console.log(`[DEBUG] Final URL: ${page.url()}`);
  console.log(`[DEBUG] Final title: ${await page.title()}`);
}

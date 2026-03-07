import { Page } from "playwright";
import path from "path";

const DEBUG_DIR = process.env.DEBUG_SCREENSHOT_DIR || "./debug-screenshots";
const ENABLE_DEBUG = process.env.ENABLE_DEBUG_SCREENSHOTS === "true";

async function debugScreenshot(page: Page, name: string): Promise<void> {
  if (!ENABLE_DEBUG) return;
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
 *
 * Critical learnings from Vexa AI and industry research:
 * 1. Hook RTCPeerConnection BEFORE navigation
 * 2. "Computer audio" MUST be selected — otherwise no WebRTC audio at all
 * 3. Do NOT mute mic on pre-join screen — risks deselecting "Computer audio"
 * 4. Mute mic AFTER joining via keyboard shortcut (Ctrl+Shift+M)
 * 5. Unmute all <audio> elements after joining to ensure playback
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

    // Store all peer connections for inspection
    (window as any).__rtcConnections = [];
    (window as any).__rtcAudioTrackCount = 0;

    const PatchedRTC = function (
      this: RTCPeerConnection,
      config?: RTCConfiguration
    ) {
      const pc = new OrigRTC(config);
      (window as any).__rtcConnections.push(pc);

      pc.addEventListener("track", (event: RTCTrackEvent) => {
        if (event.track.kind === "audio") {
          (window as any).__rtcAudioTrackCount++;
          // Mirror remote audio track into a hidden <audio> element
          const audio = document.createElement("audio");
          audio.id = `rtc-audio-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
          audio.autoplay = true;
          audio.muted = false;
          audio.volume = 1.0;
          audio.setAttribute("data-rtc-track", "true");
          audio.srcObject = new MediaStream([event.track]);
          audio.style.display = "none";
          document.body.appendChild(audio);
          // Force play to ensure audio flows
          audio.play().catch(() => {});
          console.log(`[YodaBot] Captured remote audio track #${(window as any).__rtcAudioTrackCount} → ${audio.id}`);
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

  // Wait for pre-join screen to fully load
  await page.waitForTimeout(3000);
  await debugScreenshot(page, "03-prejoin-screen");

  // Step 2: Set bot name in the name input field (do this FIRST before touching any toggles)
  try {
    const nameInput = page.locator(
      '#username, ' +
      'input[data-tid="prejoin-display-name-input"], ' +
      'input[placeholder*="name" i], ' +
      'input[placeholder*="Type your name" i]'
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

  // Step 3: Ensure "Computer audio" is selected — THIS IS CRITICAL
  // Without "Computer audio", Teams won't establish a WebRTC audio connection,
  // meaning we get NO remote audio tracks at all.
  try {
    // Try clicking the "Computer audio" radio/option to ensure it's selected
    const computerAudio = page.locator(
      'text="Computer audio", ' +
      '[data-tid="prejoin-audio-computer"], ' +
      'input[value="computer-audio"], ' +
      'label:has-text("Computer audio")'
    );
    const audioOption = computerAudio.first();
    if (await audioOption.isVisible({ timeout: 3000 })) {
      await audioOption.click();
      console.log("Ensured 'Computer audio' is selected");
    } else {
      console.log("'Computer audio' option not visible — may already be selected or different UI");
    }
  } catch {
    console.log("Could not find 'Computer audio' option — proceeding with current audio state");
  }

  // Step 4: Disable camera only — do NOT touch the microphone toggle on pre-join
  // Muting mic on pre-join risks deselecting "Computer audio" entirely,
  // which would kill the WebRTC audio connection.
  try {
    const cameraToggle = page.locator(
      '[data-tid="toggle-video"], ' +
      'button[aria-label*="camera" i][aria-pressed="true"], ' +
      'button[aria-label*="video" i][aria-pressed="true"], ' +
      'input[data-tid="toggle-video"][checked]'
    );
    const toggle = cameraToggle.first();
    if (await toggle.isVisible({ timeout: 3000 })) {
      await toggle.click();
      console.log("Disabled camera");
    }
  } catch {
    console.log("Camera toggle not found or already off");
  }

  await debugScreenshot(page, "04-before-join-click");

  // Step 5: Click "Join now"
  const joinButton = page.locator(
    'button:has-text("Join now"), ' +
    'button[data-tid="prejoin-join-button"], ' +
    'button:has-text("Join meeting")'
  );
  await joinButton.first().click({ timeout: 15000 });
  console.log("Clicked 'Join now'");

  // Step 6: Wait for meeting to actually connect
  // Look for indicators that we're in the meeting (call controls, leave button, etc.)
  let inMeeting = false;
  try {
    await page.waitForSelector(
      '[data-tid="call-composite"], ' +
      '[data-tid="hangup-button"], ' +
      'button[aria-label*="Leave" i], ' +
      '[data-tid="roster-button"], ' +
      'button[aria-label*="Hang up" i]',
      { timeout: 60000 } // Allow up to 60s for lobby admission
    );
    inMeeting = true;
    console.log("Meeting joined successfully — call controls visible");
    await debugScreenshot(page, "05-in-meeting");
  } catch {
    console.log("Warning: Could not confirm meeting join via DOM — proceeding anyway");
    await debugScreenshot(page, "05-join-uncertain");
  }

  // Step 7: After joining, mute mic via keyboard shortcut (Ctrl+Shift+M)
  // This is safe because the WebRTC audio connection is already established.
  // We still RECEIVE remote audio even when our mic is muted.
  if (inMeeting) {
    try {
      await page.keyboard.press("Control+Shift+m");
      console.log("Muted microphone via Ctrl+Shift+M (after join)");
    } catch {
      console.log("Failed to mute mic via keyboard — may already be muted");
    }
  }

  // Step 8: Unmute all <audio> elements to ensure WebRTC audio playback flows
  // This is what Vexa does — forces all audio elements to play and be unmuted.
  await page.evaluate(() => {
    document.querySelectorAll("audio").forEach((audio) => {
      audio.muted = false;
      audio.volume = 1.0;
      audio.play().catch(() => {});
    });
    console.log(
      `[YodaBot] Unmuted ${document.querySelectorAll("audio").length} audio elements, ` +
      `RTC tracks captured: ${(window as any).__rtcAudioTrackCount || 0}`
    );
  });

  // Step 9: Verify we have RTC audio tracks
  const rtcTrackCount = await page.evaluate(
    () => (window as any).__rtcAudioTrackCount || 0
  );
  console.log(`[DEBUG] RTC audio tracks captured so far: ${rtcTrackCount}`);
  console.log(`[DEBUG] Final URL: ${page.url()}`);
  console.log(`[DEBUG] Final title: ${await page.title()}`);
}

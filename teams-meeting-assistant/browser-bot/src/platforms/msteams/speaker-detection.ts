import { Page } from "playwright";

type SpeakerCallback = (
  speakerId: string,
  speakerName: string,
  isSpeaking: boolean
) => void;

/**
 * Detects who is currently speaking in a Teams meeting by observing DOM changes.
 *
 * Teams renders voice-activity indicators on participant video tiles:
 * - `[data-tid="voice-level-stream-outline"]` elements show speaking state
 * - The CSS class `vdi-frame-occlusion` indicates active speaking
 * - Participant name is in adjacent DOM elements
 *
 * This approach avoids audio-based diarization entirely — we get speaker
 * identity from the UI itself, which is far more accurate.
 */
export function startSpeakerDetection(
  page: Page,
  callback: SpeakerCallback
): void {
  // Inject a MutationObserver + polling loop into the page
  page
    .evaluate(() => {
      (window as any).__speakerEvents = [] as Array<{
        id: string;
        name: string;
        speaking: boolean;
      }>;

      const activeSpeakers = new Map<string, boolean>();

      function checkSpeakers() {
        // Strategy 1: Voice-level stream outline elements (Teams specific)
        const voiceElements = document.querySelectorAll(
          '[data-tid="voice-level-stream-outline"]'
        );

        for (const el of voiceElements) {
          const isSpeaking = el.classList.contains("vdi-frame-occlusion");
          const container = el.closest(
            '[data-tid="video-tile"], [data-tid="participant-item"]'
          );
          if (!container) continue;

          const nameEl =
            container.querySelector('[data-tid="participant-name"]') ||
            container.querySelector('[data-cid="display-name"]') ||
            container.querySelector(".display-name");

          const name = nameEl?.textContent?.trim() || "Unknown";
          const id = name.toLowerCase().replace(/\s+/g, "-");

          const wasSpeaking = activeSpeakers.get(id) || false;
          if (isSpeaking !== wasSpeaking) {
            activeSpeakers.set(id, isSpeaking);
            (window as any).__speakerEvents.push({
              id,
              name,
              speaking: isSpeaking,
            });
          }
        }

        // Strategy 2: Active speaker border/highlight (fallback)
        // Some Teams versions use a colored border on the active speaker's tile
        const highlightedTiles = document.querySelectorAll(
          '[data-tid="video-tile"].active-speaker, ' +
          '[data-tid="video-tile"][data-is-dominant-speaker="true"]'
        );

        for (const tile of highlightedTiles) {
          const nameEl =
            tile.querySelector('[data-tid="participant-name"]') ||
            tile.querySelector('[data-cid="display-name"]') ||
            tile.querySelector(".display-name");

          const name = nameEl?.textContent?.trim() || "Unknown";
          const id = name.toLowerCase().replace(/\s+/g, "-");

          if (!activeSpeakers.get(id)) {
            activeSpeakers.set(id, true);
            (window as any).__speakerEvents.push({
              id,
              name,
              speaking: true,
            });

            // Auto-clear after 3s if no update (dominant speaker may stay highlighted)
            setTimeout(() => {
              if (activeSpeakers.get(id)) {
                activeSpeakers.set(id, false);
                (window as any).__speakerEvents.push({
                  id,
                  name,
                  speaking: false,
                });
              }
            }, 3000);
          }
        }
      }

      // Poll at ~4Hz for speaker changes
      setInterval(checkSpeakers, 250);

      // Also use MutationObserver to catch rapid DOM changes
      const observer = new MutationObserver(() => checkSpeakers());
      observer.observe(document.body, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ["class", "data-is-dominant-speaker"],
      });

      (window as any).__speakerObserver = observer;
    })
    .catch((err) => {
      console.error("Failed to inject speaker detection:", err);
    });

  // Poll for speaker events from the page context
  const interval = setInterval(async () => {
    try {
      const events: Array<{
        id: string;
        name: string;
        speaking: boolean;
      }> = await page.evaluate(() => {
        const evts = (window as any).__speakerEvents || [];
        (window as any).__speakerEvents = [];
        return evts;
      });

      for (const evt of events) {
        callback(evt.id, evt.name, evt.speaking);
      }
    } catch {
      // Page closed
      clearInterval(interval);
    }
  }, 300);

  // Clean up on page close
  page.on("close", () => clearInterval(interval));
}

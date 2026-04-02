import { Page } from "playwright";
import { logger } from "../../utils/logger.js";

export interface CaptionSegment {
  speaker: string;
  text: string;
  timestamp: number;
}

export interface CaptionStream {
  readonly isActive: boolean;
  onSegment(cb: (seg: CaptionSegment) => void): void;
  stop(): Promise<void>;
}

/**
 * Enables Teams live captions and scrapes speaker + text from the caption DOM.
 *
 * Teams renders captions in a container with speaker name and text elements.
 * Text updates in-place (partial -> final). We debounce 500ms to detect finalization.
 * Segments are delivered to Node.js via page.exposeFunction (same pattern as audio capture).
 *
 * If captions are unavailable (admin disabled, no CC button), isActive will be false
 * and the audio pipeline should be used as the sole transcription source.
 */
export async function startCaptionCapture(page: Page): Promise<CaptionStream> {
  let callbacks: ((seg: CaptionSegment) => void)[] = [];
  let active = false;
  let stopped = false;
  let healthTimer: ReturnType<typeof setInterval> | null = null;
  let lastSegmentAt = 0;

  // Step 1: Expose callback BEFORE injecting in-page code
  await page.exposeFunction(
    "__yodaOnCaption",
    (speaker: string, text: string, timestamp: number) => {
      if (stopped) return;
      lastSegmentAt = Date.now();
      const seg: CaptionSegment = { speaker, text, timestamp };
      for (const cb of callbacks) {
        cb(seg);
      }
    }
  );

  await page.exposeFunction("__yodaOnCaptionHealth", (status: string) => {
    if (status === "active") {
      active = true;
      logger.info("Caption capture activated");
    } else if (status === "unavailable") {
      active = false;
      logger.warn("Captions unavailable — audio pipeline is primary");
    }
  });

  // Step 2: Enable captions and set up observation
  await page.evaluate(() => {
    const CAPTION_CONTAINER_SELECTORS = [
      '[data-tid="closed-caption-text"]',
      '[data-tid="caption-container"]',
      "#annotationContainer",
      ".ts-captions-container",
      '[role="log"][aria-label*="caption" i]',
    ];

    const CC_BUTTON_SELECTORS = [
      '[data-tid="toggle-captions-button"]',
      'button[aria-label*="caption" i]',
      'button[aria-label*="subtitle" i]',
      'button[aria-label*="closed caption" i]',
    ];

    const pendingCaptions = new Map<
      string,
      { speaker: string; text: string; timerId: ReturnType<typeof setTimeout> }
    >();
    const FINALIZATION_DEBOUNCE_MS = 500;

    const findCaptionContainer = (): Element | null => {
      for (const sel of CAPTION_CONTAINER_SELECTORS) {
        const el = document.querySelector(sel);
        if (el) return el;
      }
      return null;
    }

    const extractSpeakerAndText = (
      node: Element
    ): { speaker: string; text: string } | null => {
      // Strategy 1: Separate speaker name and text elements
      const speakerEl =
        node.querySelector(".caption-speaker-name") ||
        node.querySelector('[data-tid="caption-speaker"]') ||
        node.querySelector('[class*="speakerName"]');
      const textEl =
        node.querySelector(".caption-text") ||
        node.querySelector('[data-tid="caption-text"]') ||
        node.querySelector('[class*="captionText"]');

      if (speakerEl && textEl) {
        return {
          speaker: speakerEl.textContent?.trim() || "Unknown",
          text: textEl.textContent?.trim() || "",
        };
      }

      // Strategy 2: Single element with "Speaker: text" format
      const fullText = node.textContent?.trim() || "";
      const colonIdx = fullText.indexOf(":");
      if (colonIdx > 0 && colonIdx < 60) {
        return {
          speaker: fullText.substring(0, colonIdx).trim(),
          text: fullText.substring(colonIdx + 1).trim(),
        };
      }

      // Strategy 3: Just text, no speaker
      if (fullText.length > 0) {
        return { speaker: "Unknown", text: fullText };
      }

      return null;
    }

    const handleCaptionUpdate = (nodeKey: string, speaker: string, text: string) => {
      if (!text) return;

      const existing = pendingCaptions.get(nodeKey);
      if (existing) {
        clearTimeout(existing.timerId);
      }

      const timerId = setTimeout(() => {
        pendingCaptions.delete(nodeKey);
        (window as any).__yodaOnCaption(speaker, text, Date.now());
      }, FINALIZATION_DEBOUNCE_MS);

      pendingCaptions.set(nodeKey, { speaker, text, timerId });
    }

    const observeCaptions = (container: Element) => {
      (window as any).__yodaOnCaptionHealth("active");
      console.log("[YodaBot] Caption observation started");

      const observer = new MutationObserver(() => {
        const captionNodes = container.children;
        for (let i = 0; i < captionNodes.length; i++) {
          const node = captionNodes[i];
          const nodeKey =
            node.getAttribute("data-caption-id") ||
            node.getAttribute("data-tid") ||
            `caption-${i}`;

          const extracted = extractSpeakerAndText(node);
          if (extracted && extracted.text) {
            handleCaptionUpdate(nodeKey, extracted.speaker, extracted.text);
          }
        }
      });

      observer.observe(container, {
        childList: true,
        subtree: true,
        characterData: true,
      });

      (window as any).__captionObserver = observer;
      (window as any).__captionPending = pendingCaptions;
    }

    const enableCaptions = async (): Promise<boolean> => {
      // Try keyboard shortcut first
      document.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "U",
          code: "KeyU",
          ctrlKey: true,
          shiftKey: true,
          bubbles: true,
        })
      );

      for (let attempt = 0; attempt < 3; attempt++) {
        await new Promise((r) => setTimeout(r, attempt === 0 ? 3000 : 5000));
        const container = findCaptionContainer();
        if (container) {
          observeCaptions(container);
          return true;
        }

        // Try clicking CC button if keyboard shortcut didn't work
        if (attempt === 0) {
          for (const sel of CC_BUTTON_SELECTORS) {
            const btn = document.querySelector(sel);
            if (btn instanceof HTMLElement) {
              btn.click();
              console.log(`[YodaBot] Clicked CC button: ${sel}`);
              break;
            }
          }
        }
      }

      (window as any).__yodaOnCaptionHealth("unavailable");
      return false;
    }

    enableCaptions();
  });

  // Wait for in-page enableCaptions() to complete its retry loop
  await page.waitForTimeout(5000);

  // Step 3: Health monitoring
  healthTimer = setInterval(() => {
    if (!active || stopped) return;
    const silenceSec = (Date.now() - lastSegmentAt) / 1000;
    // Silence is normal — don't mark captions inactive or spam warnings.
    // Only log at debug level every 5 minutes for diagnostics.
    if (lastSegmentAt > 0 && silenceSec > 300 && Math.round(silenceSec) % 300 < 11) {
      logger.debug("No captions for " + Math.round(silenceSec) + "s (normal if nobody speaking)");
    }
  }, 10_000);

  return {
    get isActive() {
      return active;
    },
    onSegment(cb: (seg: CaptionSegment) => void) {
      callbacks.push(cb);
    },
    async stop() {
      stopped = true;
      callbacks.length = 0;
      if (healthTimer) {
        clearInterval(healthTimer);
        healthTimer = null;
      }
      await page
        .evaluate(() => {
          const observer = (window as any).__captionObserver;
          if (observer) {
            observer.disconnect();
            (window as any).__captionObserver = null;
          }
          const pending = (window as any).__captionPending as
            | Map<string, { timerId: ReturnType<typeof setTimeout> }>
            | undefined;
          if (pending) {
            for (const entry of pending.values()) {
              clearTimeout(entry.timerId);
            }
            pending.clear();
            (window as any).__captionPending = null;
          }
        })
        .catch(() => {});
    },
  };
}

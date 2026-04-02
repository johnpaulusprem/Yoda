import { Page } from "playwright";
import { logger } from "../../utils/logger.js";

/**
 * Speaker event emitted from the browser context to Node.js.
 * Mirrors the Vexa bot's SPEAKER_START / SPEAKER_END model.
 */
export interface SpeakerEvent {
  eventType: "SPEAKER_START" | "SPEAKER_END";
  participantId: string;
  participantName: string;
  /** Milliseconds since audio capture started (session-relative) */
  relativeTimestampMs: number;
}

export type SpeakerCallback = (
  speakerId: string,
  speakerName: string,
  isSpeaking: boolean
) => void;

export type SpeakerEventCallback = (event: SpeakerEvent) => void;

/**
 * Detects who is currently speaking in a Teams meeting by observing DOM changes.
 *
 * Implements the Vexa.ai approach documented in teams-speaker-identification-deep-dive.md:
 *
 * 1. **Detection**: Finds `[data-tid="voice-level-stream-outline"]` elements and walks
 *    UP the DOM tree to check for `vdi-frame-occlusion` class on element or any ancestor.
 *
 * 2. **Participant ID**: Uses a priority chain of stable DOM attributes:
 *    data-acc-element-id → data-tid → data-participant-id → data-user-id → data-object-id → id → synthetic
 *
 * 3. **Participant Name**: Tries 14+ selectors + ARIA label regex + forbidden-substring filter.
 *
 * 4. **Observation**: Per-participant MutationObserver on voice element (attributes) +
 *    container observer (childList/subtree) + requestAnimationFrame backup polling.
 *    Body-level MutationObserver detects new/removed participants.
 *
 * 5. **State Machine**: 200ms debounce between state transitions per participant.
 *    300ms event debouncer before emitting SPEAKER_START/SPEAKER_END.
 *
 * 6. **Timestamps**: Relative to `audioSessionStartMs` (set on first audio chunk).
 *    Events are dropped until audio starts to ensure time alignment.
 *
 * Returns a cleanup function that stops all detection and frees resources.
 */
export function startSpeakerDetection(
  page: Page,
  callback: SpeakerCallback,
  onSpeakerEvent?: SpeakerEventCallback
): () => void {
  // ── Inject the entire speaker detection system into the browser context ──
  page
    .evaluate(() => {
      // ═══════════════════════════════════════════════════════════════════
      // BROWSER CONTEXT — everything below runs inside the Teams page
      // ═══════════════════════════════════════════════════════════════════

      const LOG_PREFIX = "[YodaBot][SpeakerDetect]";

      // ── Event queue (read by Node.js via polling) ──
      (window as any).__speakerEvents = [] as Array<{
        id: string;
        name: string;
        speaking: boolean;
        eventType: string;
        relativeTimestampMs: number;
      }>;
      const MAX_EVENTS = 500;

      // ── Audio session start time (set by audio-capture.ts via window.__yodaAudioStartMs) ──
      // If not set, we use Date.now() at detection start as fallback epoch
      const detectionStartMs = Date.now();

      const getRelativeTimestamp = (): number => {
        const audioStart = (window as any).__yodaAudioStartMs;
        if (typeof audioStart === "number" && audioStart > 0) {
          return Date.now() - audioStart;
        }
        // Fallback: relative to when detection started
        return Date.now() - detectionStartMs;
      };

      // ════════════════════════════════════════════════════
      // 1. TeamsSpeakingDetector (Vexa Phase 1)
      // ════════════════════════════════════════════════════

      const VOICE_LEVEL_SELECTOR = '[data-tid="voice-level-stream-outline"]';

      interface SpeakingDetectionResult {
        isSpeaking: boolean;
        hasSignal: boolean;
      }

      /**
       * Detect speaking state by finding voice-level-stream-outline and walking
       * UP the DOM tree to check for vdi-frame-occlusion class.
       * This handles BOTH Case A (class on element) and Case B (class on ancestor).
       */
      const detectSpeakingState = (element: HTMLElement): SpeakingDetectionResult => {
        const voiceOutline = element.querySelector(VOICE_LEVEL_SELECTOR) as HTMLElement | null;
        if (!voiceOutline) {
          return { isSpeaking: false, hasSignal: false };
        }

        // Walk UP from voice-level element checking for vdi-frame-occlusion
        let current: HTMLElement | null = voiceOutline;
        let hasVdiFrameOcclusion = false;

        while (current && !hasVdiFrameOcclusion) {
          if (current.classList.contains("vdi-frame-occlusion")) {
            hasVdiFrameOcclusion = true;
            break;
          }
          current = current.parentElement;
        }

        return {
          isSpeaking: hasVdiFrameOcclusion,
          hasSignal: true,
        };
      };

      const hasRequiredSignal = (element: HTMLElement): boolean => {
        return element.querySelector(VOICE_LEVEL_SELECTOR) !== null;
      };

      // ════════════════════════════════════════════════════
      // 2. ParticipantRegistry (Vexa Phase 2)
      // ════════════════════════════════════════════════════

      interface ParticipantIdentity {
        id: string;
        name: string;
        element: HTMLElement;
        lastSeen: number;
      }

      const identityCache = new Map<HTMLElement, ParticipantIdentity>();
      const idToElement = new Map<string, HTMLElement>();

      // Forbidden substrings that indicate UI controls, not participant names
      const FORBIDDEN_NAME_SUBSTRINGS = [
        "more_vert", "mic_off", "mic", "videocam", "videocam_off",
        "present_to_all", "devices", "speaker", "speakers", "microphone",
        "camera", "camera_off", "share", "chat", "participant", "user",
      ];

      const NAME_SELECTORS = [
        'div[class*="___2u340f0"]',
        '[data-tid*="display-name"]',
        '[data-tid*="participant-name"]',
        '[data-tid*="user-name"]',
        '[data-cid="display-name"]',
        '[aria-label*="name"]',
        '.participant-name',
        '.display-name',
        '.user-name',
        '.roster-item-name',
        '.video-tile-name',
        'span[title]',
        '[title*="name"]',
        '.ms-Persona-primaryText',
        '.ms-Persona-secondaryText',
        '[class*="displayName"]',
      ];

      const extractId = (element: HTMLElement): string => {
        // Priority chain: most stable → least stable
        let id =
          element.getAttribute("data-acc-element-id") ||
          element.getAttribute("data-tid") ||
          element.getAttribute("data-participant-id") ||
          element.getAttribute("data-user-id") ||
          element.getAttribute("data-object-id") ||
          element.getAttribute("id");

        // Search children for stable ID attributes
        if (!id) {
          const stableChild = element.querySelector(
            "[data-tid], [data-participant-id], [data-user-id]"
          );
          if (stableChild) {
            id =
              stableChild.getAttribute("data-tid") ||
              stableChild.getAttribute("data-participant-id") ||
              stableChild.getAttribute("data-user-id");
          }
        }

        // Synthetic fallback
        if (!id) {
          const ds = (element as any).dataset;
          if (!ds.yodaGeneratedId) {
            ds.yodaGeneratedId = "yoda-id-" + Math.random().toString(36).substr(2, 9);
          }
          id = ds.yodaGeneratedId as string;
        }

        return id!;
      };

      const isValidName = (text: string): boolean => {
        if (text.length < 2 || text.length > 49) return false;
        const lower = text.toLowerCase();
        return !FORBIDDEN_NAME_SUBSTRINGS.some((f) => lower.includes(f));
      };

      const extractName = (element: HTMLElement, id: string): string => {
        for (const selector of NAME_SELECTORS) {
          const el = element.querySelector(selector);
          if (!el) continue;

          const text =
            (el.textContent?.trim()) ||
            ((el as HTMLElement).innerText?.trim()) ||
            (el.getAttribute("title")?.trim()) ||
            (el.getAttribute("aria-label")?.trim());

          if (text && isValidName(text)) return text;
        }

        // ARIA label fallback: parse "name: John Doe" pattern
        const ariaLabel = element.getAttribute("aria-label");
        if (ariaLabel && ariaLabel.includes("name")) {
          const nameMatch = ariaLabel.match(/name[:\s]+([^,]+)/i);
          if (nameMatch && nameMatch[1]) {
            const nameText = nameMatch[1].trim();
            if (nameText.length > 1 && nameText.length < 50) return nameText;
          }
        }

        return `Teams Participant (${id.substring(0, 12)})`;
      };

      const getIdentity = (element: HTMLElement): ParticipantIdentity => {
        const cached = identityCache.get(element);
        if (cached) return cached;

        const id = extractId(element);
        const name = extractName(element, id);
        const identity: ParticipantIdentity = {
          id,
          name,
          element,
          lastSeen: Date.now(),
        };

        identityCache.set(element, identity);
        idToElement.set(id, element);
        return identity;
      };

      const invalidateIdentity = (element: HTMLElement) => {
        const cached = identityCache.get(element);
        if (cached) {
          idToElement.delete(cached.id);
          identityCache.delete(element);
        }
      };

      // ════════════════════════════════════════════════════
      // 3. SpeakerStateMachine (Vexa Phase 3)
      // ════════════════════════════════════════════════════

      type SpeakingState = "speaking" | "silent" | "unknown";

      interface ParticipantState {
        state: SpeakingState;
        hasSignal: boolean;
        lastChangeTime: number;
        lastEventTime: number;
      }

      const MIN_STATE_CHANGE_MS = 200;
      const participantStates = new Map<string, ParticipantState>();

      const updateState = (
        participantId: string,
        detectionResult: SpeakingDetectionResult
      ): boolean => {
        const current = participantStates.get(participantId);
        const now = Date.now();

        // Rule 1: No signal → unknown (no event)
        if (!detectionResult.hasSignal) {
          if (current?.hasSignal) {
            participantStates.set(participantId, {
              state: "unknown",
              hasSignal: false,
              lastChangeTime: now,
              lastEventTime: current.lastEventTime,
            });
          }
          return false;
        }

        const newState: SpeakingState = detectionResult.isSpeaking ? "speaking" : "silent";

        // Rule 2: No change
        if (current?.state === newState && current?.hasSignal) return false;

        // Rule 3: Debounce (200ms min between state changes)
        if (current && now - current.lastChangeTime < MIN_STATE_CHANGE_MS) return false;

        // Rule 4: Genuine transition
        participantStates.set(participantId, {
          state: newState,
          hasSignal: true,
          lastChangeTime: now,
          lastEventTime: current?.lastEventTime || 0,
        });

        return true;
      };

      const getState = (participantId: string): SpeakingState => {
        return participantStates.get(participantId)?.state || "unknown";
      };

      const removeState = (participantId: string) => {
        participantStates.delete(participantId);
      };

      // ════════════════════════════════════════════════════
      // 4. EventDebouncer (Vexa Phase 3b) — 300ms delay
      // ════════════════════════════════════════════════════

      const EVENT_DEBOUNCE_MS = 300;
      const debouncerTimers = new Map<string, ReturnType<typeof setTimeout>>();

      const debounce = (key: string, fn: () => void) => {
        const existing = debouncerTimers.get(key);
        if (existing) clearTimeout(existing);

        const timer = setTimeout(() => {
          fn();
          debouncerTimers.delete(key);
        }, EVENT_DEBOUNCE_MS);
        debouncerTimers.set(key, timer);
      };

      const cancelDebounce = (key: string) => {
        const timer = debouncerTimers.get(key);
        if (timer) {
          clearTimeout(timer);
          debouncerTimers.delete(key);
        }
      };

      // ════════════════════════════════════════════════════
      // 5. Active speaker tracking + event emission
      // ════════════════════════════════════════════════════

      const speakingStates = new Map<string, SpeakingState>();

      const emitEvent = (state: SpeakingState, identity: ParticipantIdentity) => {
        const eventType = state === "speaking" ? "SPEAKER_START" : "SPEAKER_END";
        const relativeTimestampMs = getRelativeTimestamp();

        // Push to events queue (polled by Node.js)
        const events = (window as any).__speakerEvents;
        if (events) {
          if (events.length >= MAX_EVENTS) {
            events.splice(0, MAX_EVENTS / 2);
          }
          events.push({
            id: identity.id,
            name: identity.name,
            speaking: state === "speaking",
            eventType,
            relativeTimestampMs,
          });
        }

        console.log(
          `${LOG_PREFIX} ${eventType}: "${identity.name}" (id=${identity.id.substring(0, 20)}) at ${relativeTimestampMs}ms`
        );
      };

      // ════════════════════════════════════════════════════
      // 6. checkAndEmit — ties detection → state machine → emission
      // ════════════════════════════════════════════════════

      const checkAndEmit = (identity: ParticipantIdentity) => {
        // Guard: element removed from DOM
        if (!identity.element.isConnected) {
          handleParticipantRemoved(identity);
          return;
        }

        const detectionResult = detectSpeakingState(identity.element);

        if (updateState(identity.id, detectionResult)) {
          if (detectionResult.hasSignal) {
            const newState: SpeakingState = detectionResult.isSpeaking ? "speaking" : "silent";
            speakingStates.set(identity.id, newState);

            // Debounce actual event emission by 300ms
            debounce(identity.id, () => {
              emitEvent(newState, identity);
            });
          }
        }
      };

      // ════════════════════════════════════════════════════
      // 7. Observer System (Vexa Phase 4)
      // ════════════════════════════════════════════════════

      const observers = new Map<HTMLElement, MutationObserver[]>();
      const rafHandles = new Map<string, number>();

      const observeParticipant = (element: HTMLElement) => {
        // Guard: already observing
        if ((element as any).dataset.yodaObserverAttached) return;
        // Guard: no voice signal
        if (!hasRequiredSignal(element)) return;

        const identity = getIdentity(element);
        (element as any).dataset.yodaObserverAttached = "true";

        const voiceOutline = element.querySelector(VOICE_LEVEL_SELECTOR) as HTMLElement | null;
        if (!voiceOutline) return;

        const obs: MutationObserver[] = [];

        // 7.1: MutationObserver on voice-level element (primary signal)
        const voiceObserver = new MutationObserver(() => {
          checkAndEmit(identity);
        });
        voiceObserver.observe(voiceOutline, {
          attributes: true,
          attributeFilter: ["style", "class", "aria-hidden"],
          childList: false,
          subtree: false,
        });
        obs.push(voiceObserver);

        // 7.2: MutationObserver on container element (signal loss detection)
        const containerObserver = new MutationObserver(() => {
          if (!hasRequiredSignal(element)) {
            handleParticipantRemoved(identity);
            return;
          }
          checkAndEmit(identity);
        });
        containerObserver.observe(element, {
          childList: true,
          subtree: true,
          attributes: false,
        });
        obs.push(containerObserver);

        observers.set(element, obs);

        // 7.3: requestAnimationFrame polling (backup — catches non-mutation DOM changes)
        const scheduleRAF = () => {
          const check = () => {
            if (!identity.element.isConnected) {
              handleParticipantRemoved(identity);
              return;
            }
            checkAndEmit(identity);
            const handle = requestAnimationFrame(check);
            rafHandles.set(identity.id, handle);
          };
          const handle = requestAnimationFrame(check);
          rafHandles.set(identity.id, handle);
        };
        scheduleRAF();

        console.log(
          `${LOG_PREFIX} Observing participant: "${identity.name}" (id=${identity.id.substring(0, 20)})`
        );
      };

      // ════════════════════════════════════════════════════
      // 8. Participant removal cleanup (Vexa Phase 4.6)
      // ════════════════════════════════════════════════════

      const handleParticipantRemoved = (identity: ParticipantIdentity) => {
        // 1. Cancel pending debounced events
        cancelDebounce(identity.id);

        // 2. If speaking, emit SPEAKER_END
        if (getState(identity.id) === "speaking") {
          emitEvent("silent", identity);
        }

        // 3. Disconnect MutationObservers
        const obs = observers.get(identity.element);
        if (obs) {
          obs.forEach((o) => o.disconnect());
          observers.delete(identity.element);
        }

        // 4. Cancel RAF
        const rafHandle = rafHandles.get(identity.id);
        if (rafHandle) {
          cancelAnimationFrame(rafHandle);
          rafHandles.delete(identity.id);
        }

        // 5. Clean up all state
        removeState(identity.id);
        speakingStates.delete(identity.id);
        invalidateIdentity(identity.element);
        delete (identity.element as any).dataset.yodaObserverAttached;
      };

      // ════════════════════════════════════════════════════
      // 9. Participant selectors (Vexa Phase 4.4)
      // ════════════════════════════════════════════════════

      const PARTICIPANT_SELECTORS = [
        '[data-tid*="participant"]',
        '[aria-label*="participant"]',
        '[data-tid*="roster"]',
        '[data-tid*="roster-item"]',
        '[data-tid*="video-tile"]',
        '[data-tid*="videoTile"]',
        '[data-tid*="participant-tile"]',
        '[data-tid*="participantTile"]',
        '[role="listitem"]',
        '.participant-tile',
        '.video-tile',
        '.roster-item',
        '[role="menuitem"]',
      ];

      // ════════════════════════════════════════════════════
      // 10. Initial scan + body-level observer for new participants
      // ════════════════════════════════════════════════════

      const scanAndObserveAll = () => {
        let totalFound = 0;
        for (const selector of PARTICIPANT_SELECTORS) {
          const elements = document.querySelectorAll(selector);
          elements.forEach((el) => {
            if (el instanceof HTMLElement && hasRequiredSignal(el)) {
              observeParticipant(el);
              totalFound++;
            }
          });
        }
        console.log(`${LOG_PREFIX} Initial scan found ${totalFound} participant elements with voice signals`);
      };

      // Body-level observer: detect new/removed participant elements
      const meetingContainer =
        document.querySelector('[role="main"]') || document.body;

      const bodyObserver = new MutationObserver((mutationsList) => {
        for (const mutation of mutationsList) {
          if (mutation.type === "childList") {
            // Check added nodes for new participants
            mutation.addedNodes.forEach((node) => {
              if (node.nodeType !== Node.ELEMENT_NODE) return;
              const el = node as HTMLElement;
              for (const selector of PARTICIPANT_SELECTORS) {
                if (el.matches(selector)) {
                  observeParticipant(el);
                }
                el.querySelectorAll(selector).forEach((child) => {
                  if (child instanceof HTMLElement) {
                    observeParticipant(child);
                  }
                });
              }
            });

            // Check removed nodes — force SPEAKER_END if needed
            mutation.removedNodes.forEach((node) => {
              if (node.nodeType !== Node.ELEMENT_NODE) return;
              const el = node as HTMLElement;
              for (const selector of PARTICIPANT_SELECTORS) {
                if (el.matches(selector)) {
                  const cachedIdentity = identityCache.get(el);
                  if (cachedIdentity) {
                    if (speakingStates.get(cachedIdentity.id) === "speaking") {
                      emitEvent("silent", cachedIdentity);
                    }
                    handleParticipantRemoved(cachedIdentity);
                  }
                }
              }
            });
          }
        }
      });

      bodyObserver.observe(meetingContainer, {
        childList: true,
        subtree: true,
      });

      // ════════════════════════════════════════════════════
      // 11. ARIA-based participant counting (every 5s, monitoring only)
      // ════════════════════════════════════════════════════

      const countParticipants = (): string[] => {
        const menuItems = Array.from(document.querySelectorAll('[role="menuitem"]'));
        const names = new Set<string>();
        for (const item of menuItems) {
          const hasImg = !!(item.querySelector("img") || item.querySelector('[role="img"]'));
          if (!hasImg) continue;
          const aria = item.getAttribute("aria-label");
          let name = aria?.trim() || "";
          if (!name) {
            const text = (item.textContent || "").trim();
            if (text) name = text;
          }
          if (name) names.add(name);
        }
        return Array.from(names);
      };

      let participantCountLogInterval = 0;
      const countInterval = setInterval(() => {
        participantCountLogInterval++;
        const names = countParticipants();
        // Log every 30s (6 × 5s)
        if (participantCountLogInterval % 6 === 1) {
          const activeSpeakerList = Array.from(speakingStates.entries())
            .filter(([, s]) => s === "speaking")
            .map(([id]) => {
              const el = idToElement.get(id);
              const identity = el ? identityCache.get(el) : null;
              return identity?.name || id.substring(0, 15);
            });

          console.log(
            `${LOG_PREFIX} Participants (ARIA): ${names.length} [${names.slice(0, 8).join(", ")}] | ` +
            `Active speakers: ${activeSpeakerList.length} [${activeSpeakerList.join(", ")}] | ` +
            `Observed: ${observers.size} elements`
          );
        }
      }, 5000);

      // ════════════════════════════════════════════════════
      // 12. Debug logging: dump all participant-related DOM elements (every 30s)
      // ════════════════════════════════════════════════════

      let debugLogCounter = 0;
      const debugInterval = setInterval(() => {
        debugLogCounter++;
        if (debugLogCounter % 6 !== 1) return; // every 30s

        const voiceEls = document.querySelectorAll(VOICE_LEVEL_SELECTOR);
        const videoTiles = document.querySelectorAll('[data-tid="video-tile"]');

        console.log(
          `${LOG_PREFIX} DOM debug: voiceElements=${voiceEls.length}, videoTiles=${videoTiles.length}, ` +
          `observing=${observers.size}, states=${participantStates.size}`
        );

        // Log each voice element's state
        voiceEls.forEach((el, i) => {
          let hasVdi = false;
          let cur: Element | null = el;
          while (cur) {
            if (cur.classList.contains("vdi-frame-occlusion")) {
              hasVdi = true;
              break;
            }
            cur = cur.parentElement;
          }
          const container = el.closest(
            '[data-tid*="video-tile"], [data-tid*="participant"], [role="listitem"], [role="menuitem"], ' +
            '[data-tid*="roster"], [data-tid*="participantTile"]'
          );
          const containerTid = container?.getAttribute("data-tid") || container?.getAttribute("role") || "none";
          console.log(
            `${LOG_PREFIX}   voice[${i}]: vdi-frame-occlusion=${hasVdi}, container=${containerTid}`
          );
        });

        // Dump interesting data-tid elements
        const allParticipantEls = document.querySelectorAll(
          '[data-tid*="participant"], [data-tid*="roster"], [data-tid*="speaker"], ' +
          '[data-tid*="video-tile"], [data-tid*="display-name"], [data-cid*="display-name"], ' +
          '[data-tid*="person"], [data-tid*="avatar"]'
        );
        const tids = Array.from(allParticipantEls)
          .map((el) => `${el.tagName}[data-tid="${el.getAttribute("data-tid")}"]`)
          .slice(0, 20);
        console.log(`${LOG_PREFIX} Participant-related tids: ${JSON.stringify(tids)}`);
      }, 5000);

      // ── Kick off initial scan ──
      scanAndObserveAll();

      // ── Store references for cleanup ──
      (window as any).__yodaSpeakerCleanup = {
        bodyObserver,
        countInterval,
        debugInterval,
        observers,
        rafHandles,
        debouncerTimers,
        participantStates,
        speakingStates,
        identityCache,
        idToElement,
      };
    })
    .catch((err) => {
      logger.error("Failed to inject speaker detection", { error: String(err) });
    });

  // ── Poll for speaker events from browser context → Node.js ──
  const pollInterval = setInterval(async () => {
    try {
      const events: Array<{
        id: string;
        name: string;
        speaking: boolean;
        eventType: string;
        relativeTimestampMs: number;
      }> = await page.evaluate(() => {
        const evts = (window as any).__speakerEvents || [];
        (window as any).__speakerEvents = [];
        return evts;
      });

      for (const evt of events) {
        // Legacy callback (setActiveSpeaker in transcription.ts)
        callback(evt.id, evt.name, evt.speaking);

        // New SPEAKER_START/SPEAKER_END event callback
        if (onSpeakerEvent) {
          onSpeakerEvent({
            eventType: evt.eventType as "SPEAKER_START" | "SPEAKER_END",
            participantId: evt.id,
            participantName: evt.name,
            relativeTimestampMs: evt.relativeTimestampMs,
          });
        }
      }
    } catch {
      // Page closed
      clearInterval(pollInterval);
    }
  }, 200); // Poll every 200ms (faster than old 300ms for lower latency)

  // ── Return cleanup function ──
  return () => {
    clearInterval(pollInterval);
    page
      .evaluate(() => {
        const cleanup = (window as any).__yodaSpeakerCleanup;
        if (!cleanup) return;

        // Disconnect body observer
        cleanup.bodyObserver?.disconnect();

        // Clear intervals
        clearInterval(cleanup.countInterval);
        clearInterval(cleanup.debugInterval);

        // Disconnect per-participant observers
        for (const [, obs] of cleanup.observers) {
          obs.forEach((o: MutationObserver) => o.disconnect());
        }
        cleanup.observers.clear();

        // Cancel RAF handles
        for (const [, handle] of cleanup.rafHandles) {
          cancelAnimationFrame(handle);
        }
        cleanup.rafHandles.clear();

        // Cancel debouncer timers
        for (const [, timer] of cleanup.debouncerTimers) {
          clearTimeout(timer);
        }
        cleanup.debouncerTimers.clear();

        // Clear all state maps
        cleanup.participantStates.clear();
        cleanup.speakingStates.clear();
        cleanup.identityCache.clear();
        cleanup.idToElement.clear();

        // Clear events
        (window as any).__speakerEvents = null;
        (window as any).__yodaSpeakerCleanup = null;
      })
      .catch(() => {});
  };
}

import crypto from "crypto";

export class PythonBackendClient {
  private baseUrl: string;
  private hmacSecret: string;
  private botInstanceId: string;

  constructor(baseUrl: string, hmacSecret: string, botInstanceId: string) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.hmacSecret = hmacSecret;
    this.botInstanceId = botInstanceId;
    if (!hmacSecret) {
      console.warn("PythonBackendClient: HMAC secret not configured — requests will be unsigned");
    }
  }

  async sendTranscriptChunk(
    meetingId: string,
    segments: TranscriptSegment[]
  ): Promise<void> {
    const body = {
      meeting_id: meetingId,
      bot_instance_id: this.botInstanceId,
      segments: segments.map((s) => ({
        sequence: s.sequence,
        speaker_id: s.speakerId,
        speaker_name: s.speakerName,
        text: s.text,
        start_time_sec: s.startTimeSec,
        end_time_sec: s.endTimeSec,
        confidence: s.confidence,
        is_final: s.isFinal,
        source: s.source,
      })),
    };
    await this.post("/api/bot-events/transcript", body);
  }

  async sendLifecycleEvent(
    meetingId: string,
    eventType: "bot_joined" | "participants_updated" | "meeting_ended" | "bot_error",
    data?: Record<string, unknown>
  ): Promise<void> {
    const body = {
      meeting_id: meetingId,
      bot_instance_id: this.botInstanceId,
      event_type: eventType,
      timestamp: new Date().toISOString(),
      data: data ?? null,
    };
    await this.post("/api/bot-events/lifecycle", body);
  }

  /**
   * Send SPEAKER_START / SPEAKER_END events to the Python backend.
   * These are stored and used to map speakers to transcript segments
   * via the overlap-based algorithm (Vexa-style).
   */
  async sendSpeakerEvent(
    meetingId: string,
    eventType: "SPEAKER_START" | "SPEAKER_END",
    participantId: string,
    participantName: string,
    relativeTimestampMs: number
  ): Promise<void> {
    const body = {
      meeting_id: meetingId,
      bot_instance_id: this.botInstanceId,
      event_type: eventType,
      participant_id: participantId,
      participant_name: participantName,
      relative_timestamp_ms: relativeTimestampMs,
      timestamp: new Date().toISOString(),
    };
    // Fire-and-forget with single retry — speaker events are high volume,
    // occasional loss is acceptable (overlap algorithm is resilient)
    await this.post("/api/bot-events/speaker", body, 1);
  }

  private async post(path: string, body: unknown, retries = 2): Promise<void> {
    const url = `${this.baseUrl}${path}`;
    const bodyStr = JSON.stringify(body);
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };

    // HMAC signing — matches Python's validate_hmac exactly:
    //   payload = f"{timestamp}{nonce}{method}{path}{body_hash}"
    //   signature = hmac(secret, payload, sha256).hexdigest()
    if (this.hmacSecret) {
      const timestamp = Math.floor(Date.now() / 1000).toString();
      const nonce = crypto.randomUUID();
      const bodyHash = crypto.createHash("sha256").update(bodyStr).digest("hex");
      const payload = `${timestamp}${nonce}POST${path}${bodyHash}`;
      const signature = crypto
        .createHmac("sha256", this.hmacSecret)
        .update(payload)
        .digest("hex");

      console.log(`[HMAC-DEBUG] path=${path} timestamp=${timestamp} nonce=${nonce} bodyHash=${bodyHash.substring(0, 16)}... sig=${signature.substring(0, 16)}...`);

      headers["X-Request-Timestamp"] = timestamp;
      headers["X-Request-Nonce"] = nonce;
      headers["X-Request-Signature"] = signature;
    }

    let lastError: Error | null = null;
    for (let attempt = 0; attempt <= retries; attempt++) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10_000);
      try {
        const resp = await fetch(url, {
          method: "POST",
          headers,
          body: bodyStr,
          signal: controller.signal,
        });

        if (!resp.ok) {
          const text = await resp.text().catch(() => "");
          const err = new Error(`POST ${path} failed: ${resp.status} ${text}`);
          // Only retry on 5xx (server errors), not 4xx (client errors)
          if (resp.status >= 500 && attempt < retries) {
            lastError = err;
            await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
            continue;
          }
          throw err;
        }
        return; // Success
      } catch (err: any) {
        lastError = err;
        if (err.name === "AbortError") {
          lastError = new Error(`POST ${path} timed out after 10s`);
        }
        if (attempt < retries) {
          await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
          continue;
        }
      } finally {
        clearTimeout(timeout);
      }
    }
    throw lastError!;
  }
}

export interface TranscriptSegment {
  sequence: number;
  speakerId: string;
  speakerName: string;
  text: string;
  startTimeSec: number;
  endTimeSec: number;
  confidence: number;
  isFinal: boolean;
  source: "caption" | "audio";
}

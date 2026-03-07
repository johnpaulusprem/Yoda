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

  private async post(path: string, body: unknown): Promise<void> {
    const url = `${this.baseUrl}${path}`;
    const bodyStr = JSON.stringify(body);
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };

    // HMAC signing — matches Python's validate_hmac exactly:
    //   payload = f"{timestamp}{method}{path}{body_hash}"
    //   signature = hmac(secret, payload, sha256).hexdigest()
    if (this.hmacSecret) {
      const timestamp = Math.floor(Date.now() / 1000).toString();
      const bodyHash = crypto.createHash("sha256").update(bodyStr).digest("hex");
      const payload = `${timestamp}POST${path}${bodyHash}`;
      const signature = crypto
        .createHmac("sha256", this.hmacSecret)
        .update(payload)
        .digest("hex");

      headers["X-Request-Timestamp"] = timestamp;
      headers["X-Request-Signature"] = signature;
    }

    const resp = await fetch(url, {
      method: "POST",
      headers,
      body: bodyStr,
    });

    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`POST ${path} failed: ${resp.status} ${text}`);
    }
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
}

import { Counter, Gauge, Histogram, Registry } from "prom-client";

export const registry = new Registry();

export const meetingsActive = new Gauge({
  name: "browser_bot_meetings_active",
  help: "Number of active meetings",
  registers: [registry],
});

export const transcriptSegmentsTotal = new Counter({
  name: "browser_bot_transcript_segments_total",
  help: "Total transcript segments sent to backend",
  labelNames: ["source"] as const,
  registers: [registry],
});

export const audioSilenceAlertsTotal = new Counter({
  name: "browser_bot_audio_silence_alerts_total",
  help: "Audio silence alerts triggered",
  registers: [registry],
});

export const joinDurationSeconds = new Histogram({
  name: "browser_bot_join_duration_seconds",
  help: "Time to join a meeting in seconds",
  buckets: [5, 10, 30, 60, 120, 180],
  registers: [registry],
});

export const browserMemoryMB = new Gauge({
  name: "browser_bot_browser_memory_mb",
  help: "Browser process memory usage in MB",
  registers: [registry],
});

export const errorsTotal = new Counter({
  name: "browser_bot_errors_total",
  help: "Total errors by type",
  labelNames: ["type"] as const,
  registers: [registry],
});

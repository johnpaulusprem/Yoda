import "dotenv/config";
import crypto from "crypto";
import express, { Request, Response, NextFunction } from "express";
import helmet from "helmet";
import rateLimit from "express-rate-limit";
import { v5 as uuidv5 } from "uuid";
import { BotManager } from "./services/bot-manager.js";
import { LobbyDeniedError } from "./platforms/msteams/join.js";
import { logger } from "./utils/logger.js";
import { registry } from "./utils/metrics.js";

// --- Config with validation ---
const PORT = parseInt(process.env.PORT || "3001", 10);
const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || "http://localhost:10000";
const HMAC_SECRET = process.env.HMAC_SECRET || "";
const BOT_NAME = process.env.BOT_NAME || "Yoda Assistant";
const API_KEY = process.env.API_KEY || "";
const NODE_ENV = process.env.NODE_ENV || "development";

// Fail fast if secrets not configured in production
if (NODE_ENV === "production" && !HMAC_SECRET) {
  logger.error("FATAL: HMAC_SECRET is required in production");
  process.exit(1);
}
if (NODE_ENV === "production" && !API_KEY) {
  logger.error("FATAL: API_KEY is required in production");
  process.exit(1);
}

// --- Allowed Teams URL patterns (SSRF protection) ---
// Only allow actual meeting join URLs — block redirects and arbitrary paths
const ALLOWED_JOIN_URL_PATTERNS = [
  /^https:\/\/teams\.microsoft\.com\/meet\//,
  /^https:\/\/teams\.microsoft\.com\/l\/meetup-join\//,
  /^https:\/\/teams\.live\.com\/meet\//,
  /^https:\/\/[a-z0-9-]+\.teams\.microsoft\.com\/meet\//,
];

function isAllowedJoinUrl(url: string): boolean {
  if (typeof url !== "string" || url.length > 2048) return false;
  // Block URLs with auth components (@) that could redirect
  if (url.includes("@")) return false;
  return ALLOWED_JOIN_URL_PATTERNS.some((pattern) => pattern.test(url));
}

// --- Input validation ---
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const MEETING_ID_PATTERN = /^[a-zA-Z0-9\-]{1,128}$/;
const CALL_ID_PATTERN = /^browser-[a-f0-9\-]{1,64}$/;

// Namespace for deterministic UUID v5 generation from meeting IDs
const MEETING_ID_NAMESPACE = "a1b2c3d4-e5f6-7890-abcd-ef1234567890";

function isValidMeetingId(id: unknown): id is string {
  return typeof id === "string" && MEETING_ID_PATTERN.test(id);
}

/**
 * Ensure meetingId is a valid UUID. If it already is, return as-is.
 * Otherwise, deterministically generate a UUID v5 from the string
 * so the same meetingId always maps to the same UUID.
 */
function toUuidMeetingId(meetingId: string): string {
  if (UUID_PATTERN.test(meetingId)) {
    return meetingId.toLowerCase();
  }
  return uuidv5(meetingId, MEETING_ID_NAMESPACE);
}

function isValidCallId(id: unknown): id is string {
  return typeof id === "string" && CALL_ID_PATTERN.test(id);
}

// --- Auth middleware ---
function authenticateRequest(req: Request, res: Response, next: NextFunction): void {
  // Skip auth in development if API_KEY not set
  if (!API_KEY) {
    if (NODE_ENV === "production") {
      res.status(401).json({ error: "Unauthorized" });
      return;
    }
    next();
    return;
  }

  const provided = req.headers["x-api-key"];
  if (!provided || typeof provided !== "string") {
    res.status(401).json({ error: "Unauthorized" });
    return;
  }

  // Constant-time comparison to prevent timing attacks
  const expected = Buffer.from(API_KEY);
  const actual = Buffer.from(provided);
  if (expected.length !== actual.length || !crypto.timingSafeEqual(expected, actual)) {
    res.status(401).json({ error: "Unauthorized" });
    return;
  }

  next();
}

// --- Express app ---
const app = express();

// Security headers
app.use(helmet());
app.disable("x-powered-by");

// Body size limit
app.use(express.json({ limit: "10kb" }));

// Rate limiting
app.use(
  rateLimit({
    windowMs: 60 * 1000, // 1 minute
    max: 30, // 30 requests per minute
    standardHeaders: true,
    legacyHeaders: false,
    message: { error: "Too many requests" },
  })
);

// Stricter rate limit on join endpoint
const joinLimiter = rateLimit({
  windowMs: 60 * 1000,
  max: 10, // 10 join requests per minute
  standardHeaders: true,
  legacyHeaders: false,
  message: { error: "Too many join requests" },
});

const botManager = new BotManager({
  pythonBackendUrl: PYTHON_BACKEND_URL,
  hmacSecret: HMAC_SECRET,
  botName: BOT_NAME,
});

// Health check (no auth required)
app.get("/health/live", (_req, res) => {
  res.json({ status: "ok" });
});

app.get("/metrics", async (_req, res) => {
  try {
    res.set("Content-Type", registry.contentType);
    res.send(await registry.metrics());
  } catch {
    res.status(500).json({ error: "Metrics unavailable" });
  }
});

app.get("/health/ready", authenticateRequest, (_req, res) => {
  const active = botManager.activeMeetingCount;
  const capacity = botManager.canAccept;

  let status: "ok" | "degraded" | "unhealthy" = "ok";
  if (active === 0 && !capacity) {
    status = "unhealthy";
  }

  res.json({
    status,
    meetings: {
      active,
      canAccept: capacity,
    },
    uptime: Math.round(process.uptime()),
    memoryMB: Math.round(process.memoryUsage().rss / 1024 / 1024),
  });
});

// Join a Teams meeting
app.post("/api/meetings/join", authenticateRequest, joinLimiter, async (req, res) => {
  const { meetingId, joinUrl } = req.body;

  if (!meetingId || !joinUrl) {
    res.status(400).json({ error: "meetingId and joinUrl are required" });
    return;
  }

  if (!isValidMeetingId(meetingId)) {
    res.status(400).json({ error: "Invalid meetingId format" });
    return;
  }

  // Normalize meetingId to UUID format for Python backend compatibility
  const normalizedMeetingId = toUuidMeetingId(meetingId);

  if (!isAllowedJoinUrl(joinUrl)) {
    res.status(400).json({ error: "Invalid joinUrl — must be a Teams meeting URL" });
    return;
  }

  if (!botManager.canAccept) {
    res.status(503).json({ error: "At capacity" });
    return;
  }

  try {
    const callId = await botManager.joinMeeting(normalizedMeetingId, joinUrl);
    res.json({ callId, meetingId: normalizedMeetingId, status: "joining" });
  } catch (err: any) {
    logger.error("Failed to join meeting", { error: err.message });
    if (err instanceof LobbyDeniedError) {
      res.status(403).json({ error: "lobby_denied", message: err.message });
    } else if (err.message?.includes("Already in meeting")) {
      res.status(409).json({ error: "already_joined", message: err.message });
    } else {
      res.status(500).json({ error: "Failed to join meeting", message: err.message });
    }
  }
});

// Leave a meeting
app.post("/api/meetings/leave", authenticateRequest, async (req, res) => {
  const { callId } = req.body;

  if (!callId) {
    res.status(400).json({ error: "callId is required" });
    return;
  }

  if (!isValidCallId(callId)) {
    res.status(400).json({ error: "Invalid callId format" });
    return;
  }

  try {
    await botManager.leaveMeeting(callId);
    res.json({ status: "left" });
  } catch (err: any) {
    logger.error("Failed to leave meeting", { error: err.message });
    if (err.message?.includes("No active meeting")) {
      res.status(404).json({ error: "Meeting not found" });
    } else {
      res.status(500).json({ error: "Failed to leave meeting" });
    }
  }
});

// Capacity check
app.get("/api/meetings/capacity", authenticateRequest, (_req, res) => {
  res.json({
    canAccept: botManager.canAccept,
  });
});

// Global error handler — never leak internals
app.use((err: Error, _req: Request, res: Response, _next: NextFunction) => {
  logger.error("Unhandled error", { error: err.message });
  res.status(500).json({ error: "Internal server error" });
});

// Graceful shutdown
async function shutdown(signal: string) {
  logger.info(`${signal} received — shutting down`);
  await botManager.shutdown();
  process.exit(0);
}
process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));
process.on("unhandledRejection", (err) => {
  logger.error("Unhandled rejection", { error: String(err) });
});

app.listen(PORT, () => {
  logger.info("Browser bot started", { port: PORT, env: NODE_ENV, auth: !!API_KEY });
});

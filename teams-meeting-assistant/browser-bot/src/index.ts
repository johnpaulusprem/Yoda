import crypto from "crypto";
import express, { Request, Response, NextFunction } from "express";
import helmet from "helmet";
import rateLimit from "express-rate-limit";
import { BotManager } from "./services/bot-manager.js";

// --- Config with validation ---
const PORT = parseInt(process.env.PORT || "3001", 10);
const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || "http://localhost:8000";
const HMAC_SECRET = process.env.HMAC_SECRET || "";
const BOT_NAME = process.env.BOT_NAME || "Yoda Assistant";
const API_KEY = process.env.API_KEY || "";
const NODE_ENV = process.env.NODE_ENV || "development";

// Fail fast if secrets not configured in production
if (NODE_ENV === "production" && !HMAC_SECRET) {
  console.error("FATAL: HMAC_SECRET is required in production");
  process.exit(1);
}
if (NODE_ENV === "production" && !API_KEY) {
  console.error("FATAL: API_KEY is required in production");
  process.exit(1);
}

// --- Allowed Teams URL patterns (SSRF protection) ---
const ALLOWED_JOIN_URL_PATTERNS = [
  /^https:\/\/teams\.microsoft\.com\//,
  /^https:\/\/teams\.live\.com\//,
  /^https:\/\/.*\.teams\.microsoft\.com\//,
];

function isAllowedJoinUrl(url: string): boolean {
  if (typeof url !== "string" || url.length > 2048) return false;
  return ALLOWED_JOIN_URL_PATTERNS.some((pattern) => pattern.test(url));
}

// --- Input validation ---
const MEETING_ID_PATTERN = /^[a-zA-Z0-9\-]{1,128}$/;
const CALL_ID_PATTERN = /^browser-[a-f0-9\-]{1,64}$/;

function isValidMeetingId(id: unknown): id is string {
  return typeof id === "string" && MEETING_ID_PATTERN.test(id);
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

  if (!isAllowedJoinUrl(joinUrl)) {
    res.status(400).json({ error: "Invalid joinUrl — must be a Teams meeting URL" });
    return;
  }

  if (!botManager.canAccept) {
    res.status(503).json({ error: "At capacity" });
    return;
  }

  try {
    const callId = await botManager.joinMeeting(meetingId, joinUrl);
    res.json({ callId, status: "joining" });
  } catch (err: any) {
    console.error(`Failed to join meeting:`, err.message);
    res.status(500).json({ error: "Failed to join meeting" });
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
    console.error(`Failed to leave meeting:`, err.message);
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
  console.error("Unhandled error:", err.message);
  res.status(500).json({ error: "Internal server error" });
});

// Graceful shutdown
async function shutdown(signal: string) {
  console.log(`${signal} received — shutting down`);
  await botManager.shutdown();
  process.exit(0);
}
process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));
process.on("unhandledRejection", (err) => {
  console.error("Unhandled rejection:", err);
});

app.listen(PORT, () => {
  console.log(`Browser bot listening on port ${PORT}`);
  console.log(`Environment: ${NODE_ENV}`);
  console.log(`Auth: ${API_KEY ? "enabled" : "DISABLED (dev mode)"}`);
});

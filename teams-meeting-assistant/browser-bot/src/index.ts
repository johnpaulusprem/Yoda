import express from "express";
import { BotManager } from "./services/bot-manager.js";

const PORT = parseInt(process.env.PORT || "3001", 10);
const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || "http://localhost:8000";
const HMAC_SECRET = process.env.HMAC_SECRET || "";
const BOT_NAME = process.env.BOT_NAME || "Yoda Assistant";

const app = express();
app.use(express.json());

const botManager = new BotManager({
  pythonBackendUrl: PYTHON_BACKEND_URL,
  hmacSecret: HMAC_SECRET,
  botName: BOT_NAME,
});

// Health check
app.get("/health/live", (_req, res) => {
  res.json({
    status: "ok",
    activeMeetings: botManager.activeMeetingCount,
    maxMeetings: BotManager.MAX_MEETINGS,
  });
});

// Join a Teams meeting
app.post("/api/meetings/join", async (req, res) => {
  const { meetingId, joinUrl } = req.body;

  if (!meetingId || !joinUrl) {
    res.status(400).json({ error: "meetingId and joinUrl are required" });
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
    console.error(`Failed to join meeting ${meetingId}:`, err.message);
    res.status(500).json({ error: err.message });
  }
});

// Leave a meeting
app.post("/api/meetings/leave", async (req, res) => {
  const { callId } = req.body;

  if (!callId) {
    res.status(400).json({ error: "callId is required" });
    return;
  }

  try {
    await botManager.leaveMeeting(callId);
    res.json({ status: "left" });
  } catch (err: any) {
    console.error(`Failed to leave meeting ${callId}:`, err.message);
    res.status(500).json({ error: err.message });
  }
});

// Capacity check
app.get("/api/meetings/capacity", (_req, res) => {
  res.json({
    currentMeetings: botManager.activeMeetingCount,
    maxMeetings: BotManager.MAX_MEETINGS,
    canAccept: botManager.canAccept,
  });
});

app.listen(PORT, () => {
  console.log(`Browser bot listening on port ${PORT}`);
  console.log(`Python backend: ${PYTHON_BACKEND_URL}`);
  console.log(`Bot name: ${BOT_NAME}`);
});

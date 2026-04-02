import { createLogger, format, transports } from "winston";

const LOG_LEVEL = process.env.LOG_LEVEL || "info";

export const logger = createLogger({
  level: LOG_LEVEL,
  format: format.combine(
    format.timestamp({ format: "ISO" }),
    format.errors({ stack: true }),
    format.json()
  ),
  defaultMeta: { service: "browser-bot" },
  transports: [new transports.Console()],
});

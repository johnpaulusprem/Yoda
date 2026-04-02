-- ═══════════════════════════════════════════════════════════════
-- Init script: creates both databases in a single Postgres instance
-- Runs automatically on first container start via docker-entrypoint-initdb.d
-- ═══════════════════════════════════════════════════════════════

-- The "yoda" database is already created by POSTGRES_DB env var.
-- Create the meeting_assistant database for the Teams meeting assistant service.
CREATE DATABASE meeting_assistant;

-- Enable pgvector extension in both databases
\c yoda
CREATE EXTENSION IF NOT EXISTS vector;

\c meeting_assistant
CREATE EXTENSION IF NOT EXISTS vector;

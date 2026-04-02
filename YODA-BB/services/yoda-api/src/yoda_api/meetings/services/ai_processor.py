"""
AI Processor service for extracting structured meeting insights from transcripts.

Sends meeting transcripts to Azure AI Foundry (GPT-4o-mini or GPT-4o) and parses
the response into summaries, action items, decisions, key topics, and unresolved
questions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import timedelta
from typing import Any

from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential

from yoda_api.config import Settings
from yoda_foundation.models import Meeting, TranscriptSegment

logger = logging.getLogger(__name__)

# Default schema returned when AI extraction fails or returns malformed JSON
_EMPTY_RESULT: dict[str, Any] = {
    "summary": "",
    "action_items": [],
    "decisions": [],
    "key_topics": [],
    "unresolved_questions": [],
}

# Chunk duration for splitting long meeting transcripts (in minutes)
_CHUNK_DURATION_MINUTES = 30


class AIProcessor:
    """Processes meeting transcripts via Azure AI Foundry to extract structured insights."""

    def __init__(self, settings: Settings) -> None:
        self.client = ChatCompletionsClient(
            endpoint=settings.AI_FOUNDRY_ENDPOINT,
            credential=AzureKeyCredential(settings.AI_FOUNDRY_API_KEY),
        )
        self.settings = settings

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def process_meeting(
        self,
        meeting: Meeting,
        transcript_segments: list[TranscriptSegment],
    ) -> dict[str, Any]:
        """
        Process a complete meeting transcript and return structured extraction.

        Steps:
        1. Format transcript into human-readable text.
        2. Choose model based on meeting length.
        3. For short meetings: single LLM call with extraction prompt.
           For long meetings: chunked summarisation with final merge pass.
        4. Parse JSON response into a dict containing summary, action_items,
           decisions, key_topics, and unresolved_questions.
        5. Track and log processing time.

        Returns a dict with keys: summary, action_items, decisions,
        key_topics, unresolved_questions, model_used, processing_time_seconds.
        """
        start = time.monotonic()

        # Determine meeting duration in minutes
        meeting_duration_minutes = self._meeting_duration_minutes(meeting)
        is_long = meeting_duration_minutes >= self.settings.LONG_MEETING_THRESHOLD_MINUTES

        if is_long:
            model = self.settings.AI_FOUNDRY_DEPLOYMENT_NAME_COMPLEX  # gpt-4o
            logger.info(
                "Long meeting detected (%.1f min) — using chunked processing with %s",
                meeting_duration_minutes,
                model,
            )
            result = await self._process_chunked(meeting, transcript_segments)
        else:
            model = self.settings.AI_FOUNDRY_DEPLOYMENT_NAME  # gpt-4o-mini
            logger.info(
                "Short meeting (%.1f min) — using single-pass processing with %s",
                meeting_duration_minutes,
                model,
            )
            formatted_transcript = self._format_transcript(transcript_segments)
            participant_names = [p.display_name for p in meeting.participants]
            system_prompt, user_prompt = self._build_extraction_prompt(
                formatted_transcript, meeting.subject, participant_names
            )
            raw_response = await self._call_llm(system_prompt, user_prompt, model)
            result = self._parse_response(raw_response)

        elapsed = time.monotonic() - start
        result["model_used"] = model
        result["processing_time_seconds"] = round(elapsed, 2)

        logger.info(
            "Meeting %s processed in %.2fs — %d action items, %d decisions",
            meeting.id,
            elapsed,
            len(result.get("action_items", [])),
            len(result.get("decisions", [])),
        )
        return result

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_extraction_prompt(
        self,
        transcript: str,
        meeting_subject: str,
        participants: list[str],
    ) -> tuple[str, str]:
        """
        Build the system and user prompts for the LLM extraction call.

        Returns (system_prompt, user_prompt).
        """
        system_prompt = (
            "You are a meeting analyst. You will receive a meeting transcript "
            "and must extract structured information.\n"
            "Respond ONLY with valid JSON matching the schema below. "
            "Do not include any other text.\n\n"
            "JSON Schema:\n"
            "{\n"
            '    "summary": "3-5 paragraph summary of the meeting, covering all key points discussed",\n'
            '    "action_items": [\n'
            "        {\n"
            '            "description": "Clear description of what needs to be done",\n'
            '            "assigned_to": "Person\'s name as mentioned in the transcript",\n'
            '            "deadline": "ISO 8601 date if mentioned, null otherwise",\n'
            '            "priority": "high | medium | low",\n'
            '            "confidence": "high | medium | low — how confident you are this is a real action item (high = explicitly stated, medium = implied, low = inferred)",\n'
            '            "source_quote": "Exact quote from transcript where this was discussed"\n'
            "        }\n"
            "    ],\n"
            '    "decisions": [\n'
            "        {\n"
            '            "decision": "What was decided",\n'
            '            "context": "Brief context of why/how this decision was reached"\n'
            "        }\n"
            "    ],\n"
            '    "key_topics": [\n'
            "        {\n"
            '            "topic": "Topic name",\n'
            '            "timestamp": "Approximate timestamp when discussed",\n'
            '            "detail": "Brief description of what was discussed about this topic"\n'
            "        }\n"
            "    ],\n"
            '    "unresolved_questions": [\n'
            '        "Question or issue that was raised but not resolved"\n'
            "    ]\n"
            "}"
        )

        participants_str = ", ".join(participants) if participants else "Unknown"

        user_prompt = (
            f"Meeting Subject: {meeting_subject}\n"
            f"Participants: {participants_str}\n\n"
            f"Transcript:\n{transcript}"
        )

        return system_prompt, user_prompt

    # ------------------------------------------------------------------
    # Chunked processing for long meetings
    # ------------------------------------------------------------------

    async def _process_chunked(
        self,
        meeting: Meeting,
        transcript_segments: list[TranscriptSegment],
    ) -> dict[str, Any]:
        """
        Process a long meeting by splitting the transcript into 30-minute chunks.

        1. Split transcript segments into time-based chunks.
        2. Summarise each chunk independently.
        3. Run a final "summary of summaries" pass for a cohesive top-level summary.
        4. Merge and deduplicate action items across all chunks.
        """
        model = self.settings.AI_FOUNDRY_DEPLOYMENT_NAME_COMPLEX
        participant_names = [p.display_name for p in meeting.participants]

        # --- Step 1: Split into 30-minute chunks ---
        chunks = self._split_into_chunks(transcript_segments)
        logger.info("Split transcript into %d chunks for processing", len(chunks))

        # --- Step 2: Summarise each chunk ---
        chunk_results: list[dict[str, Any]] = []
        for idx, chunk_segments in enumerate(chunks, start=1):
            formatted = self._format_transcript(chunk_segments)
            chunk_start_ts = self._seconds_to_timestamp(chunk_segments[0].start_time)
            chunk_end_ts = self._seconds_to_timestamp(chunk_segments[-1].end_time)

            system_prompt, user_prompt = self._build_extraction_prompt(
                formatted,
                f"{meeting.subject} (Part {idx}/{len(chunks)}, {chunk_start_ts}–{chunk_end_ts})",
                participant_names,
            )
            raw = await self._call_llm(system_prompt, user_prompt, model)
            parsed = self._parse_response(raw)
            chunk_results.append(parsed)
            logger.info("Chunk %d/%d processed", idx, len(chunks))

        # --- Step 3: Final summary-of-summaries pass ---
        combined_summaries = "\n\n".join(
            f"--- Part {i+1} ---\n{cr.get('summary', '')}"
            for i, cr in enumerate(chunk_results)
        )

        final_system = (
            "You are a meeting analyst. You will receive chunk-by-chunk summaries "
            "of a long meeting. Produce a single cohesive 3-5 paragraph summary that "
            "covers the entire meeting. Respond ONLY with valid JSON matching this schema:\n"
            '{\n    "summary": "Cohesive 3-5 paragraph summary of the entire meeting"\n}'
        )
        final_user = (
            f"Meeting Subject: {meeting.subject}\n"
            f"Participants: {', '.join(participant_names)}\n\n"
            f"Chunk Summaries:\n{combined_summaries}"
        )
        final_raw = await self._call_llm(final_system, final_user, model)
        final_parsed = self._parse_response(final_raw)

        # --- Step 4: Merge results across all chunks ---
        merged = self._merge_chunk_results(chunk_results, final_parsed.get("summary", ""))
        return merged

    def _split_into_chunks(
        self, segments: list[TranscriptSegment]
    ) -> list[list[TranscriptSegment]]:
        """Split transcript segments into 30-minute time-based chunks."""
        if not segments:
            return []

        chunk_duration_seconds = _CHUNK_DURATION_MINUTES * 60
        chunks: list[list[TranscriptSegment]] = []
        current_chunk: list[TranscriptSegment] = []
        chunk_start_time = segments[0].start_time

        for segment in segments:
            # Start a new chunk if this segment exceeds the chunk window
            if segment.start_time - chunk_start_time >= chunk_duration_seconds and current_chunk:
                chunks.append(current_chunk)
                current_chunk = []
                chunk_start_time = segment.start_time

            current_chunk.append(segment)

        # Append the last chunk if non-empty
        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def _merge_chunk_results(
        self,
        chunk_results: list[dict[str, Any]],
        final_summary: str,
    ) -> dict[str, Any]:
        """
        Merge extraction results from multiple chunks into a single result dict.

        Deduplicates action items by normalising descriptions.
        """
        merged: dict[str, Any] = {
            "summary": final_summary,
            "action_items": [],
            "decisions": [],
            "key_topics": [],
            "unresolved_questions": [],
        }

        seen_action_descriptions: set[str] = set()
        seen_decisions: set[str] = set()
        seen_questions: set[str] = set()

        for cr in chunk_results:
            # Action items — deduplicate by normalised description
            for item in cr.get("action_items", []):
                desc = item.get("description", "").strip().lower()
                if desc and desc not in seen_action_descriptions:
                    seen_action_descriptions.add(desc)
                    merged["action_items"].append(item)

            # Decisions — deduplicate by normalised decision text
            for dec in cr.get("decisions", []):
                dec_text = dec.get("decision", "").strip().lower()
                if dec_text and dec_text not in seen_decisions:
                    seen_decisions.add(dec_text)
                    merged["decisions"].append(dec)

            # Key topics — keep all (order matters for timeline)
            merged["key_topics"].extend(cr.get("key_topics", []))

            # Unresolved questions — deduplicate
            for q in cr.get("unresolved_questions", []):
                q_norm = q.strip().lower()
                if q_norm and q_norm not in seen_questions:
                    seen_questions.add(q_norm)
                    merged["unresolved_questions"].append(q)

        return merged

    # ------------------------------------------------------------------
    # LLM call and response parsing
    # ------------------------------------------------------------------

    async def _call_llm(
        self, system_prompt: str, user_prompt: str, model: str
    ) -> str:
        """Send a chat completion request to Azure AI Foundry and return the raw text."""
        logger.debug("Calling AI Foundry model=%s, user_prompt_len=%d", model, len(user_prompt))

        response = await asyncio.to_thread(
            self.client.complete,
            model=model,
            messages=[
                SystemMessage(content=system_prompt),
                UserMessage(content=user_prompt),
            ],
            temperature=0.1,  # Low temperature for deterministic structured extraction
        )

        content = response.choices[0].message.content
        logger.debug("AI Foundry response length: %d chars", len(content))
        return content

    def _parse_response(self, raw: str) -> dict[str, Any]:
        """
        Parse the LLM's raw text response as JSON.

        Handles common LLM quirks:
        - Markdown code fences (```json ... ```)
        - Leading/trailing whitespace
        - Malformed JSON (returns empty result as fallback)
        """
        text = raw.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            # Remove opening fence (possibly ```json)
            first_newline = text.index("\n") if "\n" in text else len(text)
            text = text[first_newline + 1 :]
            # Remove closing fence
            if text.endswith("```"):
                text = text[: -3].rstrip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.error(
                "Failed to parse LLM response as JSON: %s — raw (first 500 chars): %s",
                exc,
                raw[:500],
            )
            return dict(_EMPTY_RESULT)

        # Validate expected top-level keys, filling in defaults for missing ones
        result: dict[str, Any] = {}
        for key, default in _EMPTY_RESULT.items():
            result[key] = parsed.get(key, default)

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_transcript(segments: list[TranscriptSegment]) -> str:
        """
        Format transcript segments into human-readable timestamped lines.

        Format: [HH:MM:SS] Speaker Name: Text
        """
        lines: list[str] = []
        for seg in segments:
            ts = AIProcessor._seconds_to_timestamp(seg.start_time)
            lines.append(f"[{ts}] {seg.speaker_name}: {seg.text}")
        return "\n".join(lines)

    @staticmethod
    def _seconds_to_timestamp(seconds: float) -> str:
        """Convert seconds offset to HH:MM:SS string."""
        td = timedelta(seconds=int(seconds))
        total_seconds = int(td.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    @staticmethod
    def _meeting_duration_minutes(meeting: Meeting) -> float:
        """
        Calculate meeting duration in minutes.

        Uses actual_start/actual_end if available, otherwise falls back to
        scheduled_start/scheduled_end.
        """
        start = meeting.actual_start or meeting.scheduled_start
        end = meeting.actual_end or meeting.scheduled_end
        delta = end - start
        return delta.total_seconds() / 60.0

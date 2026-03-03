"""AI Processor service -- enterprise edition.

Sends meeting transcripts to Azure AI Foundry (GPT-4o-mini or GPT-4o) and
parses the response into summaries, action items, decisions, key topics,
and unresolved questions.

Ported from ``teams-meeting-assistant/app/services/ai_processor.py`` with:
- CXO exceptions (AIProcessingError)
- Tracing spans for LLM calls
- Metrics (processing time, tokens)
- Kept chunked processing for long meetings
- Uses asyncio.to_thread for sync SDK call
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import timedelta
from typing import Any

from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential

from cxo_ai_companion.exceptions import AIProcessingError
from cxo_ai_companion.models.meeting import Meeting
from cxo_ai_companion.models.transcript import TranscriptSegment
from cxo_ai_companion.observability import get_logger, metrics, trace_span

logger = get_logger("services.ai_processor")

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
    """Processes meeting transcripts via Azure AI Foundry to extract structured insights.

    When a DSPy adapter is provided, the ``MeetingExtraction`` signature
    is used for typed, structured extraction with confidence scores.
    Falls back to the original prompt-based approach otherwise.
    """

    def __init__(
        self,
        settings: Any,
        dspy_adapter: Any | None = None,
    ) -> None:
        """Initialize the AI processor with Azure AI Foundry credentials.

        Args:
            settings: Application settings with AI_FOUNDRY_ENDPOINT and API key.
            dspy_adapter: Optional DSPy adapter for structured extraction with
                confidence scores. Falls back to prompt-based extraction if None.
        """
        self.client = ChatCompletionsClient(
            endpoint=settings.AI_FOUNDRY_ENDPOINT,
            credential=AzureKeyCredential(settings.AI_FOUNDRY_API_KEY),
        )
        self.settings = settings
        self._dspy_adapter = dspy_adapter

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def process_meeting(
        self,
        meeting: Meeting,
        transcript_segments: list[TranscriptSegment],
    ) -> dict[str, Any]:
        """Run the full post-meeting AI pipeline on a transcript.

        Selects model (gpt-4o-mini for short, gpt-4o for long meetings),
        extracts summary, action items, decisions, topics, and questions.

        Args:
            meeting: The Meeting ORM object with schedule and participant data.
            transcript_segments: Ordered list of TranscriptSegment records.

        Returns:
            Dict with keys: summary, action_items, decisions, key_topics,
            unresolved_questions, model_used, processing_time_seconds.

        Raises:
            AIProcessingError: When the LLM call or response parsing fails.
        """
        async with trace_span(
            "ai.process_meeting",
            attributes={"meeting_id": str(meeting.id), "segments": len(transcript_segments)},
        ) as span:
            start = time.monotonic()

            try:
                # Determine meeting duration in minutes
                meeting_duration_minutes = self._meeting_duration_minutes(meeting)
                is_long = meeting_duration_minutes >= self.settings.LONG_MEETING_THRESHOLD_MINUTES

                if is_long:
                    model = self.settings.AI_FOUNDRY_DEPLOYMENT_NAME_COMPLEX  # gpt-4o
                    logger.info(
                        "Long meeting detected (%.1f min) -- using chunked processing with %s",
                        meeting_duration_minutes,
                        model,
                    )
                    result = await self._process_chunked(meeting, transcript_segments)
                elif self._dspy_adapter is not None and not is_long:
                    # Use DSPy MeetingExtraction signature for structured extraction
                    model = self.settings.AI_FOUNDRY_DEPLOYMENT_NAME  # gpt-4o-mini
                    logger.info(
                        "Short meeting (%.1f min) -- using DSPy extraction with %s",
                        meeting_duration_minutes,
                        model,
                    )
                    result = await self._process_with_dspy(
                        meeting, transcript_segments
                    )
                else:
                    model = self.settings.AI_FOUNDRY_DEPLOYMENT_NAME  # gpt-4o-mini
                    logger.info(
                        "Short meeting (%.1f min) -- using single-pass processing with %s",
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

                # Record metrics
                metrics["ai_processing_time"].record(elapsed)

                span["model_used"] = model
                span["processing_time_seconds"] = round(elapsed, 2)
                span["action_items_count"] = len(result.get("action_items", []))

                logger.info(
                    "Meeting %s processed in %.2fs -- %d action items, %d decisions",
                    meeting.id,
                    elapsed,
                    len(result.get("action_items", [])),
                    len(result.get("decisions", [])),
                )
                return result

            except AIProcessingError:
                raise
            except Exception as exc:
                elapsed = time.monotonic() - start
                raise AIProcessingError(
                    message=f"Failed to process meeting {meeting.id} after {elapsed:.2f}s",
                    model=getattr(self.settings, "AI_FOUNDRY_DEPLOYMENT_NAME", None),
                    cause=exc,
                ) from exc

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_extraction_prompt(
        self,
        transcript: str,
        meeting_subject: str,
        participants: list[str],
    ) -> tuple[str, str]:
        """Build the system and user prompts for the LLM extraction call.

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
    # DSPy-powered extraction
    # ------------------------------------------------------------------

    async def _process_with_dspy(
        self,
        meeting: Meeting,
        transcript_segments: list[TranscriptSegment],
    ) -> dict[str, Any]:
        """Use DSPy MeetingExtraction signature for typed extraction.

        Returns the same dict shape as ``_parse_response()`` for
        compatibility with the rest of the pipeline.
        """
        from cxo_ai_companion.dspy.modules.predict import Predict
        from cxo_ai_companion.dspy.signatures.rag_signatures import (
            MeetingExtraction,
        )

        formatted_transcript = self._format_transcript(transcript_segments)
        participant_names = [p.display_name for p in meeting.participants]

        predict = Predict(
            signature=MeetingExtraction,
            adapter=self._dspy_adapter,
        )
        predict_result = await predict.forward(
            transcript=formatted_transcript,
            subject=meeting.subject or "Meeting",
            participants=", ".join(participant_names),
        )

        outputs = predict_result.outputs

        # Map DSPy output fields to our standard result dict
        action_items = self._parse_list_field(
            outputs.get("action_items", "")
        )
        # Attach per-item confidence from DSPy prediction metadata
        confidence = getattr(predict_result, "confidence", None)
        if confidence is not None:
            for item in action_items:
                if isinstance(item, dict) and "confidence" not in item:
                    item["confidence"] = confidence
        else:
            for item in action_items:
                if isinstance(item, dict) and "confidence" not in item:
                    item["confidence"] = 1.0

        return {
            "summary": outputs.get("summary", ""),
            "action_items": action_items,
            "decisions": self._parse_list_field(
                outputs.get("decisions", "")
            ),
            "key_topics": self._parse_list_field(
                outputs.get("key_topics", "")
            ),
            "unresolved_questions": self._parse_list_field(
                outputs.get("unresolved_questions", "")
            ),
        }

    @staticmethod
    def _parse_list_field(raw: str | list[Any]) -> list[Any]:
        """Parse a field that may be a string or list into a list.

        DSPy outputs may return comma/newline-separated strings for
        list fields.  This helper normalises them.
        """
        if isinstance(raw, list):
            return raw
        if not raw or not isinstance(raw, str):
            return []
        # Try JSON first
        try:
            import json

            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
        # Fall back to newline/comma splitting
        items = [
            item.strip().lstrip("- ").strip()
            for item in raw.replace("\n", ",").split(",")
            if item.strip()
        ]
        return items

    # ------------------------------------------------------------------
    # Chunked processing for long meetings
    # ------------------------------------------------------------------

    async def _process_chunked(
        self,
        meeting: Meeting,
        transcript_segments: list[TranscriptSegment],
    ) -> dict[str, Any]:
        """Process a long meeting by splitting the transcript into 30-minute chunks.

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
            async with trace_span(
                "ai.process_chunk",
                attributes={"chunk_index": idx, "total_chunks": len(chunks)},
            ):
                formatted = self._format_transcript(chunk_segments)
                chunk_start_ts = self._seconds_to_timestamp(chunk_segments[0].start_time)
                chunk_end_ts = self._seconds_to_timestamp(chunk_segments[-1].end_time)

                system_prompt, user_prompt = self._build_extraction_prompt(
                    formatted,
                    f"{meeting.subject} (Part {idx}/{len(chunks)}, {chunk_start_ts}-{chunk_end_ts})",
                    participant_names,
                )
                raw = await self._call_llm(system_prompt, user_prompt, model)
                parsed = self._parse_response(raw)
                chunk_results.append(parsed)
                logger.info("Chunk %d/%d processed", idx, len(chunks))

        # --- Step 3: Final summary-of-summaries pass ---
        combined_summaries = "\n\n".join(
            f"--- Part {i + 1} ---\n{cr.get('summary', '')}"
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
            if segment.start_time - chunk_start_time >= chunk_duration_seconds and current_chunk:
                chunks.append(current_chunk)
                current_chunk = []
                chunk_start_time = segment.start_time

            current_chunk.append(segment)

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def _merge_chunk_results(
        self,
        chunk_results: list[dict[str, Any]],
        final_summary: str,
    ) -> dict[str, Any]:
        """Merge extraction results from multiple chunks, deduplicating items."""
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
            for item in cr.get("action_items", []):
                desc = item.get("description", "").strip().lower()
                if desc and desc not in seen_action_descriptions:
                    seen_action_descriptions.add(desc)
                    merged["action_items"].append(item)

            for dec in cr.get("decisions", []):
                dec_text = dec.get("decision", "").strip().lower()
                if dec_text and dec_text not in seen_decisions:
                    seen_decisions.add(dec_text)
                    merged["decisions"].append(dec)

            merged["key_topics"].extend(cr.get("key_topics", []))

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
        """Send a chat completion request to Azure AI Foundry and return the raw text.

        Raises:
            AIProcessingError: When the API call fails.
        """
        async with trace_span(
            "ai.call_llm",
            attributes={"model": model, "user_prompt_len": len(user_prompt)},
        ) as span:
            try:
                logger.debug(
                    "Calling AI Foundry model=%s, user_prompt_len=%d",
                    model,
                    len(user_prompt),
                )

                response = await asyncio.to_thread(
                    self.client.complete,
                    model=model,
                    messages=[
                        SystemMessage(content=system_prompt),
                        UserMessage(content=user_prompt),
                    ],
                    temperature=0.1,
                )

                content = response.choices[0].message.content

                # Track token usage if available
                usage = getattr(response, "usage", None)
                if usage is not None:
                    total_tokens = getattr(usage, "total_tokens", 0)
                    if total_tokens:
                        metrics["ai_tokens_used"].add(total_tokens)
                        span["tokens_used"] = total_tokens

                logger.debug("AI Foundry response length: %d chars", len(content))
                return content

            except Exception as exc:
                raise AIProcessingError(
                    message=f"AI Foundry API call failed for model {model}",
                    model=model,
                    cause=exc,
                ) from exc

    def _parse_response(self, raw: str) -> dict[str, Any]:
        """Parse the LLM's raw text response as JSON.

        Handles common LLM quirks:
        - Markdown code fences (```json ... ```)
        - Leading/trailing whitespace
        - Malformed JSON (returns empty result as fallback)
        """
        text = raw.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            first_newline = text.index("\n") if "\n" in text else len(text)
            text = text[first_newline + 1:]
            if text.endswith("```"):
                text = text[:-3].rstrip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.error(
                "Failed to parse LLM response as JSON: %s -- raw (first 500 chars): %s",
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
        """Format transcript segments into human-readable timestamped lines.

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
        """Calculate meeting duration in minutes.

        Uses actual_start/actual_end if available, otherwise falls back to
        scheduled_start/scheduled_end.
        """
        start = meeting.actual_start or meeting.scheduled_start
        end = meeting.actual_end or meeting.scheduled_end
        delta = end - start
        return delta.total_seconds() / 60.0

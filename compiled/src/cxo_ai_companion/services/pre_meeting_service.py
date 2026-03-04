"""Pre-meeting brief service -- generates contextual briefs for executives.

Gathers attendee context, past decisions, related documents, recent
email threads, and AI-suggested questions to prepare an executive for
an upcoming meeting.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cxo_ai_companion.exceptions import AIProcessingError
from cxo_ai_companion.models.action_item import ActionItem
from cxo_ai_companion.models.meeting import Meeting, MeetingParticipant
from cxo_ai_companion.models.summary import MeetingSummary
from cxo_ai_companion.observability import get_logger, trace_span
from cxo_ai_companion.security.context import SecurityContext, create_system_context
from cxo_ai_companion.utilities.caching.cache import CacheInterface

logger = get_logger("services.pre_meeting")


@dataclass
class AttendeeContext:
    """Context about a meeting attendee for the pre-meeting brief."""

    user_id: str | None = None
    display_name: str = ""
    email: str | None = None
    role: str = "attendee"
    job_title: str | None = None
    department: str | None = None
    recent_interactions: int = 0
    overdue_action_items: int = 0
    last_meeting_subject: str | None = None


@dataclass
class PastDecision:
    """A decision from a past meeting with the same attendees."""

    decision_text: str
    meeting_subject: str
    meeting_date: datetime
    context: str | None = None


@dataclass
class RelatedDocument:
    """A document related to the meeting or its attendees."""

    title: str
    source: str  # sharepoint | onedrive | email_attachment
    source_url: str | None = None
    relevance_reason: str | None = None


@dataclass
class EmailThread:
    """An email thread related to the meeting."""

    subject: str
    sender_name: str = ""
    sender_email: str = ""
    snippet: str = ""
    received_at: datetime | None = None


@dataclass
class PreMeetingBrief:
    """Complete pre-meeting brief for an executive."""

    meeting_id: UUID
    meeting_subject: str
    scheduled_start: datetime
    attendees: list[AttendeeContext] = field(default_factory=list)
    past_decisions: list[PastDecision] = field(default_factory=list)
    related_documents: list[RelatedDocument] = field(default_factory=list)
    recent_email_subjects: list[str] = field(default_factory=list)
    recent_email_threads: list[EmailThread] = field(default_factory=list)
    suggested_questions: list[str] = field(default_factory=list)
    executive_summary: str = ""
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class PreMeetingService:
    """Generates pre-meeting briefs for executives.

    Aggregates attendee context (role, recent interactions, overdue items),
    last meeting decisions with these attendees, related documents from
    SharePoint/OneDrive, recent email threads with attendees, and
    AI-suggested questions based on context.
    """

    def __init__(
        self,
        db: AsyncSession,
        graph_client: Any | None = None,
        ai_processor: Any | None = None,
        cache: CacheInterface | None = None,
    ) -> None:
        """Initialize the pre-meeting service.

        Args:
            db: Async SQLAlchemy session for querying meetings and participants.
            graph_client: Optional GraphClient for fetching user profiles,
                documents, and emails. Skips those sections if None.
            ai_processor: Optional AIProcessor for generating suggested
                questions. Uses fallback heuristics if None.
            cache: Optional cache for storing generated briefs.
        """
        self.db = db
        self.graph = graph_client
        self.ai_processor = ai_processor
        self._cache = cache

    async def generate_brief(
        self,
        meeting_id: UUID,
        user_id: str,
        ctx: SecurityContext | None = None,
    ) -> PreMeetingBrief:
        """Generate a complete pre-meeting brief for the given meeting.

        Args:
            meeting_id: Database UUID of the meeting.
            user_id: Azure AD user ID of the executive requesting the brief.
            ctx: Security context.

        Returns:
            A PreMeetingBrief containing attendee context, decisions, docs,
            email threads, and AI-suggested questions.
        """
        ctx = ctx or create_system_context()

        # Check cache for existing brief
        cache_key = f"brief:{meeting_id}:{user_id}"
        if self._cache is not None:
            try:
                cached = await self._cache.get(cache_key)
                if cached is not None:
                    logger.info("Cache hit for pre-meeting brief %s", meeting_id)
                    return PreMeetingBrief(**cached)
            except Exception:
                logger.debug("Brief cache get failed, generating fresh brief")

        async with trace_span(
            "pre_meeting.generate_brief",
            attributes={"meeting_id": str(meeting_id), "user_id": user_id},
        ):
            # Fetch the meeting with participants
            stmt = (
                select(Meeting)
                .where(Meeting.id == meeting_id)
                .options(selectinload(Meeting.participants))
            )
            result = await self.db.execute(stmt)
            meeting = result.scalar_one_or_none()

            if meeting is None:
                logger.warning("Meeting %s not found for brief generation", meeting_id)
                return PreMeetingBrief(
                    meeting_id=meeting_id,
                    meeting_subject="Unknown Meeting",
                    scheduled_start=datetime.now(timezone.utc),
                )

            brief = PreMeetingBrief(
                meeting_id=meeting_id,
                meeting_subject=meeting.subject,
                scheduled_start=meeting.scheduled_start,
            )

            # Run all sub-tasks concurrently
            attendee_task = self._gather_attendee_context(meeting, user_id, ctx)
            decisions_task = self._gather_past_decisions(meeting, ctx)
            documents_task = self._gather_related_documents(meeting, ctx)
            emails_task = self._gather_recent_emails(meeting, user_id, ctx)

            attendees, past_decisions, related_documents, email_result = await asyncio.gather(
                attendee_task,
                decisions_task,
                documents_task,
                emails_task,
            )
            brief.attendees = attendees
            brief.past_decisions = past_decisions
            brief.related_documents = related_documents
            brief.recent_email_subjects, brief.recent_email_threads = email_result

            # Generate AI-suggested questions based on context
            brief.suggested_questions = await self._generate_suggested_questions(
                brief, ctx,
            )

            logger.info(
                "Generated pre-meeting brief for meeting %s: "
                "%d attendees, %d past decisions, %d documents, %d questions",
                meeting_id,
                len(brief.attendees),
                len(brief.past_decisions),
                len(brief.related_documents),
                len(brief.suggested_questions),
            )

            # Cache the generated brief
            if self._cache is not None:
                try:
                    import dataclasses

                    def _serialize_brief(obj: Any) -> Any:
                        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
                            return {k: _serialize_brief(v) for k, v in dataclasses.asdict(obj).items()}
                        if isinstance(obj, datetime):
                            return obj.isoformat()
                        if isinstance(obj, UUID):
                            return str(obj)
                        return obj

                    await self._cache.set(
                        cache_key,
                        _serialize_brief(brief),
                        ttl_seconds=7200,
                    )
                except Exception:
                    logger.debug("Brief cache set failed")

            return brief

    # ------------------------------------------------------------------
    # Sub-tasks
    # ------------------------------------------------------------------

    async def _gather_attendee_context(
        self,
        meeting: Meeting,
        user_id: str,
        ctx: SecurityContext,
    ) -> list[AttendeeContext]:
        """Build context for each meeting attendee."""
        attendees: list[AttendeeContext] = []
        now = datetime.now(timezone.utc)
        thirty_days_ago = now - timedelta(days=30)

        for participant in meeting.participants:
            attendee = AttendeeContext(
                user_id=participant.user_id,
                display_name=participant.display_name,
                email=participant.email,
                role=participant.role,
            )

            # Fetch additional user info from Graph if available
            if self.graph and participant.user_id:
                try:
                    user_info = await self.graph.get_user(participant.user_id, ctx=ctx)
                    attendee.job_title = user_info.get("jobTitle")
                    attendee.department = user_info.get("department")
                except Exception:
                    logger.debug(
                        "Could not fetch Graph profile for %s",
                        participant.user_id,
                    )

            # Count recent interactions (meetings together)
            if participant.user_id:
                interaction_q = await self.db.execute(
                    select(MeetingParticipant)
                    .join(Meeting)
                    .where(
                        MeetingParticipant.user_id == participant.user_id,
                        Meeting.organizer_id == user_id,
                        Meeting.scheduled_start >= thirty_days_ago,
                    )
                )
                attendee.recent_interactions = len(interaction_q.scalars().all())

                # Count overdue action items assigned to this person
                overdue_q = await self.db.execute(
                    select(func.count(ActionItem.id)).where(
                        ActionItem.assigned_to_user_id == participant.user_id,
                        ActionItem.status.in_(["pending", "in_progress"]),
                        ActionItem.deadline.isnot(None),
                        ActionItem.deadline < now,
                    )
                )
                attendee.overdue_action_items = overdue_q.scalar_one() or 0

            attendees.append(attendee)

        return attendees

    async def _gather_past_decisions(
        self,
        meeting: Meeting,
        ctx: SecurityContext,
    ) -> list[PastDecision]:
        """Fetch decisions from past meetings that included the same attendees."""
        participant_ids = [
            p.user_id for p in meeting.participants if p.user_id
        ]
        if not participant_ids:
            return []

        # Find meetings in the last 90 days with overlapping participants
        ninety_days_ago = datetime.now(timezone.utc) - timedelta(days=90)
        past_meetings_q = await self.db.execute(
            select(Meeting)
            .join(MeetingParticipant)
            .where(
                MeetingParticipant.user_id.in_(participant_ids),
                Meeting.id != meeting.id,
                Meeting.status == "completed",
                Meeting.scheduled_start >= ninety_days_ago,
            )
            .options(selectinload(Meeting.summary))
            .distinct()
            .limit(10)
        )

        decisions: list[PastDecision] = []
        for past_meeting in past_meetings_q.scalars().all():
            if past_meeting.summary and past_meeting.summary.decisions:
                for dec in past_meeting.summary.decisions:
                    decision_text = ""
                    dec_context = ""
                    if isinstance(dec, dict):
                        decision_text = dec.get("decision") or dec.get("text", "")
                        dec_context = dec.get("context", "")
                    else:
                        decision_text = str(dec)

                    if decision_text:
                        decisions.append(
                            PastDecision(
                                decision_text=decision_text,
                                meeting_subject=past_meeting.subject,
                                meeting_date=past_meeting.scheduled_start,
                                context=dec_context or None,
                            )
                        )

        return decisions[:20]  # Cap at 20 decisions

    async def _gather_related_documents(
        self,
        meeting: Meeting,
        ctx: SecurityContext,
    ) -> list[RelatedDocument]:
        """Fetch documents related to the meeting via Graph API."""
        if not self.graph:
            return []

        participant_ids = [
            p.user_id for p in meeting.participants if p.user_id
        ]
        if not participant_ids:
            return []

        try:
            files = await self.graph.get_recent_files(participant_ids, ctx=ctx)
            documents: list[RelatedDocument] = []
            for f in files[:10]:
                documents.append(
                    RelatedDocument(
                        title=f.get("name", "Untitled"),
                        source="onedrive",
                        source_url=f.get("webUrl"),
                        relevance_reason="Recently shared by a meeting participant",
                    )
                )
            return documents
        except Exception:
            logger.debug("Failed to gather related documents from Graph")
            return []

    async def _gather_recent_emails(
        self,
        meeting: Meeting,
        user_id: str,
        ctx: SecurityContext,
    ) -> tuple[list[str], list[EmailThread]]:
        """Fetch recent email subjects and thread details between the executive and meeting attendees."""
        if not self.graph:
            return [], []

        try:
            emails = await self.graph.get_user_emails(user_id, days=7, ctx=ctx)
            # Filter to emails involving meeting participants
            participant_emails = {
                p.email.lower() for p in meeting.participants if p.email
            }

            relevant_subjects: list[str] = []
            threads: list[EmailThread] = []
            seen_subjects: set[str] = set()

            for email in emails:
                sender_info = email.get("from", {}).get("emailAddress", {})
                sender_email = sender_info.get("address", "")
                sender_name = sender_info.get("name", "")
                recipients = [
                    r.get("emailAddress", {}).get("address", "")
                    for r in email.get("toRecipients", [])
                ]
                all_addresses = {sender_email.lower()} | {r.lower() for r in recipients}

                if all_addresses & participant_emails:
                    subject = email.get("subject", "")
                    if subject and subject not in seen_subjects:
                        seen_subjects.add(subject)
                        relevant_subjects.append(subject)

                        # Extract snippet from bodyPreview
                        snippet = email.get("bodyPreview", "")[:150]
                        received_str = email.get("receivedDateTime")
                        received_at = None
                        if received_str:
                            try:
                                received_at = datetime.fromisoformat(received_str.replace("Z", "+00:00"))
                            except (ValueError, TypeError):
                                pass

                        threads.append(EmailThread(
                            subject=subject,
                            sender_name=sender_name,
                            sender_email=sender_email,
                            snippet=snippet,
                            received_at=received_at,
                        ))

            return relevant_subjects[:10], threads[:10]
        except Exception:
            logger.debug("Failed to gather recent emails from Graph")
            return [], []

    async def _generate_suggested_questions(
        self,
        brief: PreMeetingBrief,
        ctx: SecurityContext,
    ) -> list[str]:
        """Use AI to generate suggested questions based on the brief context."""
        if not self.ai_processor:
            return self._generate_fallback_questions(brief)

        try:
            context_parts: list[str] = [
                f"Meeting: {brief.meeting_subject}",
                f"Attendees: {', '.join(a.display_name for a in brief.attendees)}",
            ]

            if brief.past_decisions:
                decisions_text = "; ".join(
                    d.decision_text for d in brief.past_decisions[:5]
                )
                context_parts.append(f"Recent decisions with these attendees: {decisions_text}")

            overdue_attendees = [
                a.display_name for a in brief.attendees if a.overdue_action_items > 0
            ]
            if overdue_attendees:
                context_parts.append(
                    f"Attendees with overdue items: {', '.join(overdue_attendees)}"
                )

            context = "\n".join(context_parts)

            system_prompt = (
                "You are an executive assistant. Generate 3-5 focused questions "
                "an executive should consider asking in the upcoming meeting, based "
                "on the provided context. Respond ONLY with valid JSON:\n"
                '{"questions": ["question1", "question2", ...]}'
            )
            user_prompt = f"Meeting Context:\n{context}"

            raw = await self.ai_processor._call_llm(
                system_prompt, user_prompt,
                self.ai_processor.settings.AI_FOUNDRY_DEPLOYMENT_NAME,
            )
            import json
            parsed = json.loads(raw.strip().strip("`").replace("```json", "").replace("```", ""))
            questions = parsed.get("questions", [])
            return questions[:5] if isinstance(questions, list) else []

        except Exception:
            logger.debug("AI question generation failed, using fallback")
            return self._generate_fallback_questions(brief)

    @staticmethod
    def _generate_fallback_questions(brief: PreMeetingBrief) -> list[str]:
        """Generate basic questions when AI is unavailable."""
        questions: list[str] = []

        overdue = [a for a in brief.attendees if a.overdue_action_items > 0]
        if overdue:
            names = ", ".join(a.display_name for a in overdue[:3])
            questions.append(
                f"What is the status of overdue items from {names}?"
            )

        if brief.past_decisions:
            questions.append(
                "Are the decisions from our last meeting still on track?"
            )

        questions.append(
            f"What are the key objectives for '{brief.meeting_subject}'?"
        )

        return questions[:5]

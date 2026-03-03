#!/usr/bin/env python3
"""Seed the database with test data.

Creates sample records for local development and manual testing:
  - UserPreference records (opted-in users)
  - A Meeting with MeetingParticipants
  - TranscriptSegments for that meeting
  - A MeetingSummary
  - ActionItems tied to the meeting

Usage:
    python -m scripts.seed_db          # from project root
    python scripts/seed_db.py          # also works

Requires DATABASE_URL to be set (reads from .env via pydantic-settings).
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure the project root is importable when running as ``python scripts/seed_db.py``
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.models.base import Base
from app.models.meeting import Meeting, MeetingParticipant
from app.models.transcript import TranscriptSegment
from app.models.summary import MeetingSummary
from app.models.action_item import ActionItem
from app.models.subscription import GraphSubscription, UserPreference


async def seed(db: AsyncSession) -> None:
    """Insert all seed data inside a single transaction."""

    now = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # 1. User Preferences (opted-in users the bot watches)
    # ------------------------------------------------------------------
    users = [
        UserPreference(
            user_id="aad-user-001",
            display_name="Alice Johnson",
            email="alice.johnson@contoso.com",
            opted_in=True,
            summary_delivery="chat",
            nudge_enabled=True,
        ),
        UserPreference(
            user_id="aad-user-002",
            display_name="Bob Williams",
            email="bob.williams@contoso.com",
            opted_in=True,
            summary_delivery="both",
            nudge_enabled=True,
        ),
        UserPreference(
            user_id="aad-user-003",
            display_name="Carol Martinez",
            email="carol.martinez@contoso.com",
            opted_in=False,
            summary_delivery="email",
            nudge_enabled=False,
        ),
    ]
    db.add_all(users)
    await db.flush()
    print(f"  Created {len(users)} UserPreference records.")

    # ------------------------------------------------------------------
    # 2. Meeting
    # ------------------------------------------------------------------
    meeting_id = uuid.uuid4()
    meeting = Meeting(
        id=meeting_id,
        teams_meeting_id="MSo1MjY5YTg2LTJiOGEtNGE5Zi1iNmIzLTZhN2NkMzAzMDcwNw==",
        thread_id="19:meeting_NTc5NjVkMTUtMjdhMi00OTFmLTlkNjctNWIzZTk4@thread.v2",
        join_url=(
            "https://teams.microsoft.com/l/meetup-join/"
            "19%3ameeting_NTc5NjVkMTUtMjdhMi00OTFmLTlkNjctNWIzZTk4%40thread.v2/0"
        ),
        subject="Sprint 23 Planning",
        organizer_id="aad-user-001",
        organizer_name="Alice Johnson",
        organizer_email="alice.johnson@contoso.com",
        scheduled_start=now - timedelta(hours=2),
        scheduled_end=now - timedelta(hours=1),
        actual_start=now - timedelta(hours=2, minutes=1),
        actual_end=now - timedelta(hours=1, minutes=3),
        status="completed",
        acs_call_connection_id="acs-conn-test-12345",
        participant_count=3,
    )
    db.add(meeting)
    await db.flush()
    print(f"  Created Meeting '{meeting.subject}' (id={meeting.id}).")

    # ------------------------------------------------------------------
    # 3. Participants
    # ------------------------------------------------------------------
    participants_data = [
        {
            "user_id": "aad-user-001",
            "display_name": "Alice Johnson",
            "email": "alice.johnson@contoso.com",
            "role": "organizer",
            "joined_at": now - timedelta(hours=2, minutes=1),
            "left_at": now - timedelta(hours=1, minutes=3),
        },
        {
            "user_id": "aad-user-002",
            "display_name": "Bob Williams",
            "email": "bob.williams@contoso.com",
            "role": "presenter",
            "joined_at": now - timedelta(hours=2),
            "left_at": now - timedelta(hours=1, minutes=3),
        },
        {
            "user_id": None,
            "display_name": "David Lee",
            "email": "david.lee@external.com",
            "role": "attendee",
            "joined_at": now - timedelta(hours=1, minutes=55),
            "left_at": now - timedelta(hours=1, minutes=5),
        },
    ]
    participants = []
    for p_data in participants_data:
        p = MeetingParticipant(meeting_id=meeting_id, **p_data)
        participants.append(p)
    db.add_all(participants)
    await db.flush()
    print(f"  Created {len(participants)} MeetingParticipant records.")

    # ------------------------------------------------------------------
    # 4. Transcript Segments
    # ------------------------------------------------------------------
    transcript_lines = [
        ("Alice Johnson", "aad-user-001", "Alright, let's kick off the sprint 23 planning. We have a full backlog to go through.", 0.0, 6.5, 0.97),
        ("Bob Williams", "aad-user-002", "Sounds good. I think we should prioritize the authentication refactor first.", 7.0, 12.3, 0.95),
        ("Alice Johnson", "aad-user-001", "Agreed. That's been blocking the new user onboarding flow for two sprints now.", 13.0, 18.5, 0.96),
        ("David Lee", None, "From the design side, we have the updated mockups ready for the dashboard redesign.", 19.0, 25.0, 0.93),
        ("Bob Williams", "aad-user-002", "Great. Can you share those in the Teams channel after the meeting?", 25.5, 29.0, 0.94),
        ("David Lee", None, "Sure, I will upload them by end of day.", 29.5, 32.0, 0.92),
        ("Alice Johnson", "aad-user-001", "Bob, can you take the lead on the auth refactor? Deadline is next Friday.", 32.5, 38.0, 0.96),
        ("Bob Williams", "aad-user-002", "Yes, I can handle that. I will need access to the staging environment though.", 38.5, 43.5, 0.95),
        ("Alice Johnson", "aad-user-001", "I will get you access today. David, can you prepare the design specs for the dashboard by Wednesday?", 44.0, 51.0, 0.97),
        ("David Lee", None, "Wednesday works for me. I will coordinate with the frontend team.", 51.5, 55.5, 0.91),
        ("Alice Johnson", "aad-user-001", "Perfect. Any other items we should discuss?", 56.0, 59.0, 0.96),
        ("Bob Williams", "aad-user-002", "We should decide on the API versioning strategy. Are we going with URL-based or header-based versioning?", 59.5, 66.5, 0.94),
        ("Alice Johnson", "aad-user-001", "Let's go with URL-based versioning. It is more explicit and easier to test.", 67.0, 72.0, 0.96),
        ("Bob Williams", "aad-user-002", "Works for me. I will document the convention in the wiki.", 72.5, 76.0, 0.93),
        ("Alice Johnson", "aad-user-001", "Great. I think we are good for today. Thanks everyone!", 76.5, 80.0, 0.97),
    ]

    segments = []
    for seq, (speaker, speaker_id, text_content, start, end, conf) in enumerate(transcript_lines):
        seg = TranscriptSegment(
            meeting_id=meeting_id,
            speaker_name=speaker,
            speaker_id=speaker_id,
            text=text_content,
            start_time=start,
            end_time=end,
            confidence=conf,
            sequence_number=seq,
        )
        segments.append(seg)
    db.add_all(segments)
    await db.flush()
    print(f"  Created {len(segments)} TranscriptSegment records.")

    # ------------------------------------------------------------------
    # 5. Meeting Summary
    # ------------------------------------------------------------------
    summary = MeetingSummary(
        meeting_id=meeting_id,
        summary_text=(
            "The team held their Sprint 23 planning meeting, focusing on prioritization "
            "of the backlog. The authentication refactor was identified as the top priority "
            "since it has been blocking the new user onboarding flow for two sprints.\n\n"
            "David Lee from the design team confirmed that updated mockups for the dashboard "
            "redesign are ready and will be shared in the Teams channel. Bob Williams will "
            "lead the auth refactor with a deadline of next Friday, pending staging environment "
            "access from Alice.\n\n"
            "The team also made a decision on API versioning strategy, choosing URL-based "
            "versioning over header-based for its explicitness and ease of testing. Bob will "
            "document this convention in the wiki.\n\n"
            "David will prepare design specs for the dashboard by Wednesday, coordinating "
            "with the frontend team."
        ),
        decisions=[
            {
                "decision": "Use URL-based API versioning instead of header-based",
                "context": "The team discussed both approaches and chose URL-based for explicitness and easier testing.",
            },
            {
                "decision": "Prioritize the authentication refactor in Sprint 23",
                "context": "The auth refactor has been blocking the new user onboarding flow for two sprints.",
            },
        ],
        key_topics=[
            {
                "topic": "Authentication Refactor",
                "timestamp": "00:07",
                "detail": "Identified as top priority; has been blocking new user onboarding for two sprints.",
            },
            {
                "topic": "Dashboard Redesign Mockups",
                "timestamp": "00:19",
                "detail": "Updated mockups are ready from design team; will be shared in Teams channel.",
            },
            {
                "topic": "API Versioning Strategy",
                "timestamp": "00:59",
                "detail": "Team decided on URL-based versioning over header-based versioning.",
            },
        ],
        unresolved_questions=[
            "What specific staging environment access does Bob need for the auth refactor?",
            "Which frontend team members will David coordinate with for the dashboard specs?",
        ],
        model_used="gpt-4o-mini",
        processing_time_seconds=3.72,
        delivered=True,
        delivered_at=now - timedelta(minutes=55),
    )
    db.add(summary)
    await db.flush()
    print("  Created MeetingSummary.")

    # ------------------------------------------------------------------
    # 6. Action Items
    # ------------------------------------------------------------------
    action_items_data = [
        {
            "description": "Lead the authentication refactor",
            "assigned_to_name": "Bob Williams",
            "assigned_to_user_id": "aad-user-002",
            "assigned_to_email": "bob.williams@contoso.com",
            "deadline": now + timedelta(days=5),
            "priority": "high",
            "status": "in_progress",
            "nudge_count": 0,
            "source_quote": "Bob, can you take the lead on the auth refactor? Deadline is next Friday.",
        },
        {
            "description": "Share updated dashboard mockups in the Teams channel",
            "assigned_to_name": "David Lee",
            "assigned_to_user_id": None,
            "assigned_to_email": "david.lee@external.com",
            "deadline": now + timedelta(hours=8),
            "priority": "medium",
            "status": "pending",
            "nudge_count": 0,
            "source_quote": "Sure, I will upload them by end of day.",
        },
        {
            "description": "Grant Bob staging environment access",
            "assigned_to_name": "Alice Johnson",
            "assigned_to_user_id": "aad-user-001",
            "assigned_to_email": "alice.johnson@contoso.com",
            "deadline": now + timedelta(hours=4),
            "priority": "high",
            "status": "pending",
            "nudge_count": 1,
            "last_nudged_at": now - timedelta(hours=1),
            "source_quote": "I will get you access today.",
        },
        {
            "description": "Prepare design specs for the dashboard redesign",
            "assigned_to_name": "David Lee",
            "assigned_to_user_id": None,
            "assigned_to_email": "david.lee@external.com",
            "deadline": now + timedelta(days=3),
            "priority": "medium",
            "status": "pending",
            "nudge_count": 0,
            "source_quote": "David, can you prepare the design specs for the dashboard by Wednesday?",
        },
        {
            "description": "Document URL-based API versioning convention in the wiki",
            "assigned_to_name": "Bob Williams",
            "assigned_to_user_id": "aad-user-002",
            "assigned_to_email": "bob.williams@contoso.com",
            "deadline": None,
            "priority": "low",
            "status": "pending",
            "nudge_count": 0,
            "source_quote": "I will document the convention in the wiki.",
        },
    ]

    action_items = []
    for ai_data in action_items_data:
        ai = ActionItem(meeting_id=meeting_id, **ai_data)
        action_items.append(ai)
    db.add_all(action_items)
    await db.flush()
    print(f"  Created {len(action_items)} ActionItem records.")

    # ------------------------------------------------------------------
    # 7. GraphSubscription (simulated active subscription)
    # ------------------------------------------------------------------
    sub = GraphSubscription(
        subscription_id="graph-sub-test-00001",
        user_id="aad-user-001",
        resource="/users/aad-user-001/events",
        expiration=now + timedelta(days=2, hours=20),
        status="active",
    )
    db.add(sub)
    await db.flush()
    print("  Created 1 GraphSubscription record.")

    await db.commit()


async def main() -> None:
    print("=" * 60)
    print("  Teams Meeting Assistant - Database Seeder")
    print("=" * 60)
    print()

    settings = Settings()
    print(f"  Database: {settings.DATABASE_URL.split('@')[-1] if '@' in settings.DATABASE_URL else '(local)'}")
    print()

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Ensure tables exist (for local dev; production uses Alembic migrations)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("  Tables verified / created.")

    async with session_factory() as session:
        # Check if data already exists
        result = await session.execute(text("SELECT count(*) FROM user_preferences"))
        count = result.scalar_one()
        if count > 0:
            print(f"\n  Database already has {count} user preferences.")
            answer = input("  Proceed and add more seed data? [y/N] ").strip().lower()
            if answer != "y":
                print("  Aborted.")
                await engine.dispose()
                return

        print("\n  Seeding data...")
        await seed(session)

    await engine.dispose()
    print("\n  Seeding complete.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

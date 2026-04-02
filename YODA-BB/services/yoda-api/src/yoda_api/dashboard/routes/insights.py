"""Analytics and insights routes."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from yoda_api.dependencies import get_db
from yoda_foundation.models import Meeting, ActionItem, MeetingInsight, MeetingSummary, MeetingParticipant, WeeklyDigest
from yoda_foundation.security.auth_dependency import get_current_user
from yoda_foundation.security.context import SecurityContext

router = APIRouter()


@router.get("/meeting-time")
async def meeting_time_analysis(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
):
    """Return meeting time statistics: total count and weekly average over a period."""
    result = await db.execute(
        select(func.count()).select_from(Meeting).where(Meeting.status == "completed")
    )
    total = result.scalar_one()
    return {
        "total_meetings": total,
        "period_days": days,
        "avg_per_week": round(total / max(days / 7, 1), 1),
    }


@router.get("/action-completion")
async def action_completion(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
):
    """Return action item completion rate: total, completed, and percentage."""
    total_r = await db.execute(select(func.count()).select_from(ActionItem))
    completed_r = await db.execute(
        select(func.count()).select_from(ActionItem).where(ActionItem.status == "completed")
    )
    total = total_r.scalar_one()
    completed = completed_r.scalar_one()
    rate = (completed / total * 100) if total > 0 else 0
    return {"total_items": total, "completed": completed, "completion_rate": round(rate, 1)}


@router.get("/collaboration")
async def collaboration_patterns(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
):
    """Analyze collaboration patterns: top collaborators and stale 1:1s."""
    cutoff = datetime.now(UTC) - timedelta(days=days)

    # Count interactions per person
    result = await db.execute(
        select(
            MeetingParticipant.user_id,
            MeetingParticipant.display_name,
            func.count().label("count"),
        )
        .join(Meeting, MeetingParticipant.meeting_id == Meeting.id)
        .where(
            Meeting.scheduled_start >= cutoff,
            MeetingParticipant.user_id.isnot(None),
        )
        .group_by(MeetingParticipant.user_id, MeetingParticipant.display_name)
        .order_by(func.count().desc())
        .limit(20)
    )
    top_collaborators = [
        {"user_id": row.user_id, "display_name": row.display_name, "interaction_count": row.count}
        for row in result.all()
    ]

    # Stale 1:1s -- people not met in >14 days
    fourteen_days_ago = datetime.now(UTC) - timedelta(days=14)
    contacts_result = await db.execute(
        select(
            MeetingParticipant.user_id,
            MeetingParticipant.display_name,
            func.max(Meeting.scheduled_start).label("last_meeting"),
        )
        .join(Meeting, MeetingParticipant.meeting_id == Meeting.id)
        .where(
            MeetingParticipant.user_id.isnot(None),
            Meeting.status == "completed",
        )
        .group_by(MeetingParticipant.user_id, MeetingParticipant.display_name)
    )
    stale_contacts = []
    for row in contacts_result.all():
        if row.last_meeting < fourteen_days_ago:
            stale_contacts.append({
                "user_id": row.user_id,
                "display_name": row.display_name,
                "last_meeting": str(row.last_meeting),
                "days_since": (datetime.now(UTC) - row.last_meeting).days,
            })

    return {
        "top_collaborators": top_collaborators,
        "stale_contacts": stale_contacts[:10],
        "period_days": days,
        "user_id": ctx.user_id,
    }


@router.get("/patterns")
async def topic_patterns(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
):
    """Detect recurring topics and potential decision reversals."""
    cutoff = datetime.now(UTC) - timedelta(days=days)

    result = await db.execute(
        select(MeetingSummary)
        .join(Meeting, MeetingSummary.meeting_id == Meeting.id)
        .where(Meeting.scheduled_start >= cutoff)
        .order_by(Meeting.scheduled_start.desc())
    )
    summaries = result.scalars().all()

    # Count recurring topics
    topic_counter: Counter[str] = Counter()
    for s in summaries:
        for topic in s.key_topics or []:
            topic_name = topic.get("topic", "") if isinstance(topic, dict) else str(topic)
            if topic_name:
                topic_counter[topic_name.lower().strip()] += 1

    recurring_topics = [
        {"topic": topic, "count": count}
        for topic, count in topic_counter.most_common(10)
        if count >= 2
    ]

    # Detect potential decision reversals
    decisions_by_topic: defaultdict[str, list[dict]] = defaultdict(list)
    for s in summaries:
        for d in s.decisions or []:
            dec_text = d.get("decision", "") if isinstance(d, dict) else str(d)
            if dec_text:
                words = [w.lower() for w in dec_text.split()[:5] if len(w) > 3]
                topic_key = " ".join(words)
                if topic_key:
                    decisions_by_topic[topic_key].append({
                        "decision": dec_text,
                        "meeting_id": str(s.meeting_id),
                        "date": str(s.created_at),
                    })

    potential_reversals = [
        {"topic_key": key, "decisions": decs}
        for key, decs in decisions_by_topic.items()
        if len(decs) >= 2
    ][:5]

    return {
        "recurring_topics": recurring_topics,
        "potential_reversals": potential_reversals,
        "period_days": days,
        "summaries_analyzed": len(summaries),
    }


@router.get("/weekly-digest")
async def weekly_digest(
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
):
    """Retrieve the most recent weekly digest for a user."""
    result = await db.execute(
        select(WeeklyDigest)
        .where(WeeklyDigest.user_id == ctx.user_id)
        .order_by(WeeklyDigest.week_end.desc())
        .limit(1)
    )
    digest = result.scalar_one_or_none()
    if digest:
        return {
            "digest": {
                "week_start": str(digest.week_start),
                "week_end": str(digest.week_end),
                "total_meetings": digest.total_meetings,
                "total_action_items": digest.total_action_items,
                "completion_rate": digest.completion_rate,
                "digest_text": digest.digest_text,
            }
        }
    return {"digest": None, "message": "No weekly digest available"}


_DECISION_KEYWORDS = [
    "approve", "decide", "sign off", "review and approve", "finalize", "authorize",
]


@router.get("/decision-velocity")
async def decision_velocity(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
) -> dict:
    """Average days from action item creation to completion for decision-type items.

    Queries completed action items whose description contains decision-related
    keywords (approve, decide, sign off, review and approve, finalize, authorize)
    and computes the mean time-to-completion in days.
    """
    cutoff = datetime.now(UTC) - timedelta(days=days)

    # Build ILIKE filter for decision keywords
    keyword_filters = [
        ActionItem.description.ilike(f"%{kw}%") for kw in _DECISION_KEYWORDS
    ]

    result = await db.execute(
        select(
            func.count(ActionItem.id).label("total"),
            func.avg(
                func.julianday(ActionItem.completed_at) - func.julianday(ActionItem.created_at)
            ).label("avg_days"),
        )
        .where(
            ActionItem.status == "completed",
            ActionItem.completed_at.isnot(None),
            ActionItem.created_at >= cutoff,
            or_(*keyword_filters),
        )
    )
    row = result.one()
    total = row.total or 0
    avg_days = round(float(row.avg_days), 1) if row.avg_days is not None else None

    return {
        "period_days": days,
        "decision_items_completed": total,
        "avg_days_to_completion": avg_days,
    }


@router.get("/recurring-topics")
async def recurring_topics(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
) -> dict:
    """Detect topics that appear in 3+ meetings within the given period."""
    from yoda_api.dashboard.services.topic_detection_service import RecurringTopicService

    svc = RecurringTopicService()
    topics = await svc.detect_recurring_topics(db, days=days)
    return {"recurring_topics": topics, "period_days": days}

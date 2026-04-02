/**
 * TypeScript interfaces for the Pre-Meeting Brief API response.
 * Mirrors backend Pydantic schemas at foundation/schemas/pre_meeting_brief.py.
 *
 * A brief aggregates attendee context, past decisions, related documents,
 * email threads, and AI-suggested questions for a single upcoming meeting.
 *
 * @see PreMeetingBriefResponse -- the full brief payload
 * @see AttendeeContext -- per-attendee profile with overdue action counts
 * @see PastDecision -- historical decision from prior meetings with same participants
 * @see RelatedDocument -- SharePoint/OneDrive document linked to the meeting topic
 */
export interface AttendeeContext {
  display_name: string;
  email: string | null;
  job_title: string | null;
  department: string | null;
  recent_interactions: number;
  overdue_actions: number;
  last_meeting: string | null;
}

export interface PastDecision {
  decision: string;
  context: string;
  meeting_date: string;
}

export interface RelatedDocument {
  title: string;
  source_url: string | null;
  content_type: string | null;
  last_modified_by: string | null;
  updated_at: string | null;
}

export interface PreMeetingBriefResponse {
  meeting_id: string;
  meeting_subject: string;
  scheduled_start: string;
  attendees: AttendeeContext[];
  past_decisions: PastDecision[];
  related_documents: RelatedDocument[];
  recent_email_subjects: string[];
  email_threads: string[];
  suggested_questions: string[];
  executive_summary: string | null;
  generated_at: string;
}

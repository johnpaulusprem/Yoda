/**
 * TypeScript interfaces for Meeting API responses.
 * Mirrors backend Pydantic schemas at foundation/schemas/meeting.py.
 *
 * @see MeetingResponse -- single meeting with join_status computed field
 * @see MeetingDetailResponse -- includes summary, action items, participants
 * @see MeetingListResponse -- paginated list wrapper
 * @see SummaryResponse -- AI-generated meeting summary with decisions and key topics
 */
export interface MeetingResponse {
  id: string;
  teams_meeting_id: string;
  thread_id: string | null;
  join_url: string;
  subject: string;
  organizer_id: string | null;
  organizer_name: string;
  organizer_email: string;
  scheduled_start: string;
  scheduled_end: string;
  actual_start: string | null;
  actual_end: string | null;
  status: 'scheduled' | 'in_progress' | 'completed' | 'failed' | 'cancelled';
  recording_url: string | null;
  participant_count: number;
  join_status: 'upcoming' | 'join_now' | 'in_progress' | 'ended';
  created_at: string;
  updated_at: string;
}

export interface ParticipantResponse {
  id: string;
  display_name: string;
  email: string | null;
  user_id: string | null;
  role: string;
  joined_at: string | null;
  left_at: string | null;
}

export interface SummaryResponse {
  id: string;
  meeting_id: string;
  summary_text: string;
  decisions: DecisionResponse[];
  key_topics: KeyTopicResponse[];
  unresolved_questions: string[];
  model_used: string;
  processing_time_seconds: number;
  created_at: string;
}

export interface DecisionResponse {
  decision: string;
  context: string;
}

export interface KeyTopicResponse {
  topic: string;
  timestamp: string;
  detail: string;
}

export interface MeetingDetailResponse extends MeetingResponse {
  summary: SummaryResponse | null;
  action_items: ActionItemResponse[];
  participants: ParticipantResponse[];
}

export interface MeetingListResponse {
  items: MeetingResponse[];
  total: number;
}

export interface CreateMeetingRequest {
  join_url: string;
  subject?: string;
  organizer_name?: string;
  organizer_email?: string;
}

import type { ActionItemResponse } from './action-item.model';

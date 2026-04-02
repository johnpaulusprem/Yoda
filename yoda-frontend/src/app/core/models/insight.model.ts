/**
 * TypeScript interfaces for Insights, Notifications, Search, and Weekly Digest API responses.
 * Aggregates several smaller API schemas into one model file.
 *
 * @see MeetingTimeResponse -- meeting frequency and average hours per week
 * @see ActionCompletionResponse -- completion rate over a time period
 * @see CollaborationResponse -- top collaborators and stale 1:1 relationships
 * @see NotificationListResponse -- paginated notifications with unread count
 * @see WeeklyDigestResponse -- AI-generated weekly summary with key decisions
 * @see SearchResponse -- cross-entity search results (meetings, documents, action items)
 */
export interface MeetingTimeResponse {
  total_meetings: number;
  period_days: number;
  avg_per_week: number;
}

export interface ActionCompletionResponse {
  total_items: number;
  completed: number;
  completion_rate: number;
}

export interface Collaborator {
  display_name: string;
  email: string | null;
  meeting_count: number;
  last_interaction: string | null;
}

export interface CollaborationResponse {
  top_collaborators: Collaborator[];
  stale_1on1s: Collaborator[];
}

export interface NotificationResponse {
  id: string;
  user_id: string;
  type: string;
  title: string;
  message: string | null;
  is_read: boolean;
  related_meeting_id: string | null;
  related_action_id: string | null;
  created_at: string;
}

export interface NotificationListResponse {
  items: NotificationResponse[];
  total: number;
  unread_count: number;
}

export interface WeeklyDigestResponse {
  id: string;
  user_id: string;
  period_start: string;
  period_end: string;
  summary_text: string;
  total_meetings: number;
  total_action_items: number;
  completion_rate: number;
  key_decisions: string[];
  model_used: string | null;
  created_at: string;
}

export interface SearchResult {
  type: 'meeting' | 'document' | 'action_item';
  id: string;
  title: string;
  snippet: string | null;
  score: number;
  metadata: Record<string, unknown>;
}

export interface SearchResponse {
  results: SearchResult[];
  total: number;
  query: string;
}

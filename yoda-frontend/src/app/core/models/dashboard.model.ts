/**
 * TypeScript interfaces for Dashboard API responses.
 * Mirrors backend Pydantic schemas at foundation/schemas/dashboard.py.
 *
 * @see DashboardStatsResponse -- aggregated counts (meetings today, pending/overdue actions)
 * @see AttentionItemsResponse -- items requiring CXO action (overdue, due today)
 * @see ActivityFeedResponse -- chronological feed of recent events
 */
export interface DashboardStatsResponse {
  meetings_today: number;
  pending_actions: number;
  overdue_actions: number;
  completion_rate: number;
  docs_to_review: number;
}

export interface AttentionItem {
  type: string;
  description: string;
  deadline: string | null;
  meeting_id: string | null;
}

export interface AttentionItemsResponse {
  items: AttentionItem[];
  total: number;
}

export interface ActivityFeedItem {
  type: string;
  title: string;
  timestamp: string;
  meeting_id?: string;
  meeting_subject?: string;
}

export interface ActivityFeedResponse {
  feed: ActivityFeedItem[];
}

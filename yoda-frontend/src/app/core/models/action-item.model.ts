/**
 * TypeScript interfaces for Action Item API responses and requests.
 * Mirrors backend Pydantic schemas at foundation/schemas/action_item.py.
 *
 * @see ActionItemResponse -- single action item with status, priority, nudge tracking
 * @see ActionItemListResponse -- paginated list wrapper
 * @see ActionItemUpdateRequest -- PATCH body for status/priority/assignee changes
 */
export interface ActionItemResponse {
  id: string;
  meeting_id: string;
  description: string;
  assigned_to_name: string;
  assigned_to_user_id: string | null;
  assigned_to_email: string | null;
  deadline: string | null;
  priority: 'high' | 'medium' | 'low';
  status: 'pending' | 'in_progress' | 'completed' | 'cancelled';
  source_quote: string | null;
  nudge_count: number;
  last_nudged_at: string | null;
  completed_at: string | null;
  snoozed_until: string | null;
  confidence: number | null;
  created_at: string;
  updated_at: string;
}

export interface ActionItemListResponse {
  items: ActionItemResponse[];
  total: number;
}

export interface ActionItemUpdateRequest {
  status?: string;
  priority?: string;
  deadline?: string;
  assigned_to_name?: string;
  assigned_to_user_id?: string;
  assigned_to_email?: string;
}

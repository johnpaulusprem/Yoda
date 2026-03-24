/**
 * TypeScript interfaces for Document API responses.
 * Mirrors backend Pydantic schemas at foundation/schemas/document.py.
 *
 * Sources include SharePoint, OneDrive, email attachments, and manual uploads.
 *
 * @see DocumentResponse -- single document with review_status and AI classification fields
 * @see DocumentListResponse -- paginated list wrapper
 * @see ClassificationResponse -- AI-generated category, confidence, and suggested tags
 * @see DocumentSearchResult -- semantic search results from the RAG vector store
 * @see MeetingDocumentsResult -- documents grouped by related meetings
 */
export interface DocumentResponse {
  id: string;
  meeting_id: string | null;
  title: string;
  source: 'sharepoint' | 'onedrive' | 'email_attachment' | 'upload' | 'search';
  source_url: string | null;
  content_type: string | null;
  content_hash: string | null;
  status: 'pending' | 'processed' | 'failed';
  uploaded_by: string | null;
  file_size_bytes: number | null;
  review_status: 'none' | 'pending_review' | 'action_required' | 'approved' | 'rejected';
  folder_path: string | null;
  page_count: number | null;
  shared_by: string | null;
  shared_at: string | null;
  priority: 'high' | 'medium' | 'low' | null;
  last_modified_by: string | null;
  category: string | null;
  classification_confidence: number | null;
  suggested_tags: string[] | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentListResponse {
  items: DocumentResponse[];
  total: number;
}

export interface ClassificationResponse {
  document_id: string;
  category: string;
  category_label: string;
  confidence: number;
  suggested_priority: string;
  suggested_tags: string[];
  top_matches: Record<string, number>[];
}

export interface DocumentSearchResult {
  query: string;
  total_results: number;
  execution_time_ms: number;
  results: { id: string; content: string; score: number; metadata: Record<string, unknown> }[];
}

export interface MeetingDocumentsResult {
  meetings: { meeting_subject: string; meeting_time: string; documents: DocumentResponse[]; total: number }[];
  total_meetings: number;
}

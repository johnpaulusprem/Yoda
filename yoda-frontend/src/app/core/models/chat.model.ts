/**
 * TypeScript interfaces for RAG-powered Chat API responses and requests.
 * Mirrors backend Pydantic schemas at foundation/schemas/chat.py.
 *
 * @see ChatSessionResponse -- a chat session with message history
 * @see ChatMessageResponse -- single message with source citations from RAG pipeline
 * @see ChatSourceCitation -- document/meeting reference attached to AI responses
 * @see ChatMessageRequest -- POST body to send a user message
 */
export interface ChatSourceCitation {
  title: string;
  url: string | null;
  snippet: string;
  document_id: string | null;
  meeting_id: string | null;
}

export interface ChatMessageResponse {
  id: string;
  session_id: string;
  role: 'user' | 'assistant';
  content: string;
  sources: ChatSourceCitation[];
  model_used: string | null;
  tokens_used: number | null;
  created_at: string;
}

export interface ChatSessionResponse {
  id: string;
  user_id: string;
  title: string;
  last_message_at: string | null;
  created_at: string;
  messages: ChatMessageResponse[];
}

export interface ChatMessageRequest {
  content: string;
}

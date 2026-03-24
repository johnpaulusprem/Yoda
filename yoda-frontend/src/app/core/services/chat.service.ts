/**
 * Chat API service -- wraps HTTP calls to /api/chat/*.
 *
 * Manages RAG-powered chat sessions: create session, list sessions,
 * send message (returns AI response with source citations), get history.
 * Used by: ChatComponent.
 */
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import { ChatSessionResponse, ChatMessageResponse, ChatMessageRequest } from '../models';

@Injectable({ providedIn: 'root' })
export class ChatService {
  private api = inject(ApiService);

  createSession(title = 'New Chat'): Observable<ChatSessionResponse> {
    return this.api.post<ChatSessionResponse>('/api/chat/sessions', { title });
  }

  listSessions(): Observable<{ sessions: ChatSessionResponse[] }> {
    return this.api.get<{ sessions: ChatSessionResponse[] }>('/api/chat/sessions');
  }

  sendMessage(sessionId: string, content: string): Observable<ChatMessageResponse> {
    return this.api.post<ChatMessageResponse>(`/api/chat/sessions/${sessionId}/messages`, { content });
  }

  getMessages(sessionId: string): Observable<{ messages: ChatMessageResponse[] }> {
    return this.api.get<{ messages: ChatMessageResponse[] }>(`/api/chat/sessions/${sessionId}/messages`);
  }
}

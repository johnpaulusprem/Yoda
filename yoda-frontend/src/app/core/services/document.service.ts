/**
 * Document API service -- wraps HTTP calls to /api/documents/*.
 *
 * Endpoints: list, get, search (semantic via RAG vector store), sync (trigger M365 import),
 * needsReview, recent, meetingRelated, classify (AI categorization).
 * Used by: DocumentsComponent.
 */
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import { DocumentListResponse, DocumentResponse, ClassificationResponse, DocumentSearchResult, MeetingDocumentsResult } from '../models';

@Injectable({ providedIn: 'root' })
export class DocumentService {
  private api = inject(ApiService);

  list(params?: { doc_type?: string; sort?: string; limit?: number }): Observable<DocumentListResponse> {
    return this.api.get<DocumentListResponse>('/api/documents', params);
  }

  get(id: string): Observable<DocumentResponse> {
    return this.api.get<DocumentResponse>(`/api/documents/${id}`);
  }

  search(query: string, k = 5): Observable<DocumentSearchResult> {
    return this.api.get<DocumentSearchResult>('/api/documents/search', { q: query, k });
  }

  sync(): Observable<void> {
    return this.api.post<void>('/api/documents/sync');
  }

  needsReview(): Observable<DocumentListResponse> {
    return this.api.get<DocumentListResponse>('/api/documents/needs-review');
  }

  recent(params?: { doc_type?: string; limit?: number }): Observable<DocumentListResponse> {
    return this.api.get<DocumentListResponse>('/api/documents/recent', params);
  }

  meetingRelated(): Observable<MeetingDocumentsResult> {
    return this.api.get<MeetingDocumentsResult>('/api/documents/meeting-related');
  }

  classify(id: string): Observable<ClassificationResponse> {
    return this.api.post<ClassificationResponse>(`/api/documents/${id}/classify`);
  }
}

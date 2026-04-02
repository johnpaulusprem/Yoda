/**
 * Meeting API service -- wraps HTTP calls to /api/meetings/*.
 *
 * Endpoints: list, get (detail with summary + action items + participants),
 * getTranscript, join, leave, reprocess.
 * Used by: DashboardComponent, MeetingsListComponent, MeetingDetailComponent,
 * ActionItemsComponent (for meeting subject lookup), BriefComponent.
 */
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import { MeetingResponse, MeetingDetailResponse, MeetingListResponse } from '../models';

@Injectable({ providedIn: 'root' })
export class MeetingService {
  private api = inject(ApiService);

  list(params?: { status?: string; limit?: number; offset?: number }): Observable<MeetingListResponse> {
    return this.api.get<MeetingListResponse>('/api/meetings', params);
  }

  get(id: string): Observable<MeetingDetailResponse> {
    return this.api.get<MeetingDetailResponse>(`/api/meetings/${id}`);
  }

  getTranscript(id: string): Observable<unknown> {
    return this.api.get(`/api/meetings/${id}/transcript`);
  }

  join(id: string): Observable<unknown> {
    return this.api.post(`/api/meetings/${id}/join`);
  }

  leave(id: string): Observable<unknown> {
    return this.api.post(`/api/meetings/${id}/leave`);
  }

  reprocess(id: string): Observable<unknown> {
    return this.api.post(`/api/meetings/${id}/reprocess`);
  }
}

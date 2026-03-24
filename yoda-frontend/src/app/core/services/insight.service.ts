/**
 * Insights API service -- wraps HTTP calls to /api/insights/*.
 *
 * Endpoints: meetingTime (hours/week), actionCompletion (rate over N days),
 * collaboration (top collaborators, stale 1:1s), patterns (AI-detected trends).
 * Used by: InsightsComponent.
 */
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import { MeetingTimeResponse, ActionCompletionResponse, CollaborationResponse } from '../models';

@Injectable({ providedIn: 'root' })
export class InsightService {
  private api = inject(ApiService);

  meetingTime(days = 30): Observable<MeetingTimeResponse> {
    return this.api.get<MeetingTimeResponse>('/api/insights/meeting-time', { days });
  }

  actionCompletion(days = 30): Observable<ActionCompletionResponse> {
    return this.api.get<ActionCompletionResponse>('/api/insights/action-completion', { days });
  }

  collaboration(days = 30): Observable<CollaborationResponse> {
    return this.api.get<CollaborationResponse>('/api/insights/collaboration', { days });
  }

  patterns(): Observable<unknown> {
    return this.api.get('/api/insights/patterns');
  }
}

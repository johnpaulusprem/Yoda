/**
 * Action Item API service -- wraps HTTP calls to /api/action-items/*.
 *
 * Endpoints: list (filterable by status, user, meeting, priority),
 * update (PATCH), complete, snooze.
 * Used by: ActionItemsComponent.
 */
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import { ActionItemListResponse, ActionItemResponse, ActionItemUpdateRequest } from '../models';

@Injectable({ providedIn: 'root' })
export class ActionItemService {
  private api = inject(ApiService);

  list(params?: { status?: string; user_id?: string; meeting_id?: string; priority?: string; limit?: number; offset?: number }): Observable<ActionItemListResponse> {
    return this.api.get<ActionItemListResponse>('/api/action-items', params);
  }

  update(id: string, body: ActionItemUpdateRequest): Observable<ActionItemResponse> {
    return this.api.patch<ActionItemResponse>(`/api/action-items/${id}`, body);
  }

  complete(id: string): Observable<ActionItemResponse> {
    return this.api.post<ActionItemResponse>(`/api/action-items/${id}/complete`);
  }

  snooze(id: string, days = 3): Observable<ActionItemResponse> {
    return this.api.post<ActionItemResponse>(`/api/action-items/${id}/snooze`, { days });
  }
}

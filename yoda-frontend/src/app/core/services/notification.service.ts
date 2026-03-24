/**
 * Notification API service -- wraps HTTP calls to /api/notifications/*.
 *
 * Endpoints: list (filterable by read status), getUnreadCount,
 * markRead (single), markAllRead.
 * Used by: TopbarComponent (bell icon dropdown and badge count).
 */
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import { NotificationListResponse } from '../models';

@Injectable({ providedIn: 'root' })
export class NotificationService {
  private api = inject(ApiService);

  list(params?: { read?: boolean; limit?: number }): Observable<NotificationListResponse> {
    return this.api.get<NotificationListResponse>('/api/notifications', params);
  }

  getUnreadCount(): Observable<{ unread_count: number }> {
    return this.api.get<{ unread_count: number }>('/api/notifications/count');
  }

  markRead(id: string): Observable<unknown> {
    return this.api.patch(`/api/notifications/${id}/read`, {});
  }

  markAllRead(): Observable<unknown> {
    return this.api.post('/api/notifications/read-all');
  }
}

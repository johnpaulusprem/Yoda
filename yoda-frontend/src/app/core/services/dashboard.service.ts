/**
 * Dashboard API service -- wraps HTTP calls to /api/dashboard/*.
 *
 * Endpoints: stats, attention-items, activity-feed.
 * Used by: DashboardComponent.
 */
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import { DashboardStatsResponse, AttentionItemsResponse, ActivityFeedResponse } from '../models';

@Injectable({ providedIn: 'root' })
export class DashboardService {
  private api = inject(ApiService);

  getStats(): Observable<DashboardStatsResponse> {
    return this.api.get<DashboardStatsResponse>('/api/dashboard/stats');
  }

  getAttentionItems(): Observable<AttentionItemsResponse> {
    return this.api.get<AttentionItemsResponse>('/api/dashboard/attention-items');
  }

  getActivityFeed(limit = 20): Observable<ActivityFeedResponse> {
    return this.api.get<ActivityFeedResponse>('/api/dashboard/activity-feed', { limit });
  }
}

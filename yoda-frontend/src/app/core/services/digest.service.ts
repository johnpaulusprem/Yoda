/**
 * Weekly Digest API service -- wraps HTTP calls to /api/digests/*.
 *
 * Endpoints: getLatest (fetch most recent digest for a user),
 * generate (trigger AI generation of a new weekly summary).
 * Used by: DigestComponent.
 */
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import { WeeklyDigestResponse } from '../models';

@Injectable({ providedIn: 'root' })
export class DigestService {
  private api = inject(ApiService);

  getLatest(userId: string): Observable<WeeklyDigestResponse> {
    return this.api.get<WeeklyDigestResponse>('/api/digests/latest', { user_id: userId });
  }

  generate(userId: string): Observable<WeeklyDigestResponse> {
    return this.api.post<WeeklyDigestResponse>('/api/digests/generate', { user_id: userId });
  }
}

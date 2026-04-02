/**
 * Pre-Meeting Brief API service -- wraps HTTP calls to /api/briefs/*.
 *
 * Endpoints: getBrief (fetches attendee context, past decisions, related docs,
 * email threads, and AI-suggested questions for a given meeting ID).
 * Used by: BriefComponent.
 */
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import { PreMeetingBriefResponse } from '../models';

@Injectable({ providedIn: 'root' })
export class BriefService {
  private api = inject(ApiService);

  getBrief(meetingId: string): Observable<PreMeetingBriefResponse> {
    return this.api.get<PreMeetingBriefResponse>(`/api/briefs/${meetingId}`);
  }
}

/**
 * Pre-Meeting Brief view -- comprehensive preparation page for an upcoming meeting.
 *
 * Sections: meeting header with live countdown timer and Join button, attendees
 * (with job title, department, overdue actions), past decisions from prior meetings,
 * relevant documents (with open-in-SharePoint links), related email threads,
 * AI-suggested discussion questions (clickable to navigate to /chat), and
 * an executive summary.
 *
 * Loads both the brief (BriefService) and meeting detail (MeetingService)
 * in parallel. The countdown timer updates every 30 seconds via setInterval.
 *
 * Data sources: BriefService, MeetingService.
 * Route: /meetings/:id/brief
 */
import { Component, inject, OnInit, OnDestroy, signal, computed, DestroyRef, ChangeDetectionStrategy } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { BriefService } from '../../core/services/brief.service';
import { MeetingService } from '../../core/services/meeting.service';
import { PreMeetingBriefResponse, MeetingDetailResponse } from '../../core/models';
import { formatRelative, getInitials } from '../../shared/utils/format.utils';

@Component({
  selector: 'app-brief',
  standalone: true,
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (loading()) {
      <div class="card">
        <p style="color:var(--text-muted);text-align:center;padding:60px">Loading pre-meeting brief...</p>
      </div>
    }

    @if (error()) {
      <div class="card">
        <p style="color:var(--accent-red);text-align:center;padding:60px">Failed to load brief. Please try again.</p>
      </div>
    }

    @if (brief(); as b) {
      <!-- Header -->
      <div class="brief-header">
        <div class="brief-header-top">
          <a routerLink="/dashboard" class="back-link">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="15 18 9 12 15 6"/>
            </svg>
            Back to Dashboard
          </a>
        </div>

        <div class="brief-header-main">
          <div class="brief-header-left">
            <h1 class="brief-title">{{ b.meeting_subject }}</h1>
            <div class="brief-meta">
              {{ formatMeetingDate(b.scheduled_start) }} &middot;
              {{ meetingLocation() }} &middot;
              {{ meetingDuration() }} &middot;
              {{ meetingRecurrence() }}
            </div>
          </div>
          <div class="brief-header-right">
            <span class="countdown-pill">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
              {{ countdownText() }}
            </span>
            @if (meeting(); as m) {
              <a class="btn-join-large pulse" [href]="m.join_url" target="_blank">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15.05 5A5 5 0 0 1 19 8.95M15.05 1A9 9 0 0 1 23 8.94M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/></svg>
                Join Meeting
              </a>
            }
          </div>
        </div>
      </div>

      <!-- 1. Attendees -->
      <div class="card section-card">
        <div class="card-header">
          <span class="card-title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:6px"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
            Attendees
          </span>
          <span class="tag tag-purple">{{ b.attendees.length }}</span>
        </div>
        <div class="attendees-grid">
          @for (att of b.attendees; track att.email ?? att.display_name) {
            <div class="attendee-card">
              <div class="attendee-avatar" [style.background]="getAvatarColor(att.display_name)">
                {{ getInitials(att.display_name) }}
              </div>
              <div class="attendee-info">
                <div class="attendee-name">{{ att.display_name }}</div>
                <div class="attendee-role">
                  @if (att.job_title) {
                    {{ att.job_title }}
                  }
                  @if (att.department) {
                    &middot; {{ att.department }}
                  }
                </div>
                <div class="attendee-context">
                  @if (att.overdue_actions > 0) {
                    <span class="context-warning">
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                      Has {{ att.overdue_actions }} overdue action item{{ att.overdue_actions !== 1 ? 's' : '' }}
                    </span>
                  } @else if (att.last_meeting) {
                    <span class="context-neutral">Last 1:1 was {{ formatShortDate(att.last_meeting) }}</span>
                  } @else if (att.recent_interactions > 0) {
                    <span class="context-neutral">{{ att.recent_interactions }} recent interaction{{ att.recent_interactions !== 1 ? 's' : '' }}</span>
                  }
                </div>
              </div>
            </div>
          }
        </div>
        @if (b.attendees.length === 0) {
          <p class="empty-state">No attendee information available</p>
        }
      </div>

      <!-- 2. From Last Meeting -->
      <div class="card section-card">
        <div class="card-header">
          <span class="card-title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:6px"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
            From Last Meeting
          </span>
          @if (b.past_decisions.length > 0) {
            <span class="tag tag-blue">{{ b.past_decisions.length }} item{{ b.past_decisions.length !== 1 ? 's' : '' }}</span>
          }
        </div>
        @if (b.past_decisions.length > 0) {
          @for (item of b.past_decisions; track $index) {
            <div class="last-meeting-item">
              <span class="lm-dot" [class]="getDecisionDotClass(item)"></span>
              <div class="lm-content">
                <div class="lm-text">{{ item.decision }}</div>
                @if (item.context) {
                  <div class="lm-context">{{ item.context }}</div>
                }
                @if (item.meeting_date) {
                  <div class="lm-date">{{ formatShortDate(item.meeting_date) }}</div>
                }
              </div>
            </div>
          }
        } @else {
          <p class="empty-state">No items from previous meetings</p>
        }
      </div>

      <!-- 3. Relevant Documents -->
      <div class="card section-card">
        <div class="card-header">
          <span class="card-title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:6px"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            Relevant Documents
          </span>
          @if (b.related_documents.length > 0) {
            <span class="tag tag-blue">{{ b.related_documents.length }}</span>
          }
        </div>
        @if (b.related_documents.length > 0) {
          @for (doc of b.related_documents; track doc.title) {
            <div class="doc-row">
              <div class="doc-left">
                <span class="doc-type-icon">{{ getDocTypeIcon(doc.content_type) }}</span>
                <div class="doc-info">
                  <div class="doc-name">{{ doc.title }}</div>
                  <div class="doc-meta">
                    @if (doc.updated_at) {
                      Updated {{ formatRelative(doc.updated_at) }}
                    }
                    @if (doc.last_modified_by) {
                      by {{ doc.last_modified_by }}
                    }
                  </div>
                </div>
              </div>
              @if (doc.source_url) {
                <a [href]="doc.source_url" target="_blank" class="doc-link" title="Open document">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                </a>
              }
            </div>
          }
        } @else {
          <p class="empty-state">No related documents found</p>
        }
      </div>

      <!-- 4. Related Email Threads -->
      <div class="card section-card">
        <div class="card-header">
          <span class="card-title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:6px"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
            Related Email Threads
          </span>
          @if (allEmailThreads().length > 0) {
            <span class="tag tag-blue">{{ allEmailThreads().length }}</span>
          }
        </div>
        @if (allEmailThreads().length > 0) {
          @for (thread of allEmailThreads(); track $index) {
            <div class="email-row">
              <span class="email-dot" [class]="$index % 3 === 0 ? 'email-dot yellow' : 'email-dot blue'"></span>
              <div class="email-content">
                <div class="email-subject">{{ thread }}</div>
              </div>
            </div>
          }
        } @else {
          <p class="empty-state">No related email threads found</p>
        }
      </div>

      <!-- 5. Suggested Topics & Questions -->
      @if (b.suggested_questions.length > 0) {
        <div class="suggestions-box">
          <div class="suggestions-header">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 1 1 7.072 0l-.548.547A3.374 3.374 0 0 0 12 18.469V19a3.374 3.374 0 0 0-1.988-1.004l-.548-.547z"/></svg>
            Suggested Topics &amp; Questions
          </div>
          <div class="suggestions-list">
            @for (question of b.suggested_questions; track $index) {
              <button class="suggestion-item" (click)="navigateToChat(question)">
                <span class="suggestion-number">{{ $index + 1 }}</span>
                <span class="suggestion-text">{{ question }}</span>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="suggestion-arrow"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
              </button>
            }
          </div>
          <div class="suggestions-hint">Click a question to discuss it with the AI assistant</div>
        </div>
      }

      <!-- Executive Summary -->
      @if (b.executive_summary) {
        <div class="card section-card">
          <div class="card-header">
            <span class="card-title">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:6px"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
              Executive Summary
            </span>
          </div>
          <p class="exec-summary-text">{{ b.executive_summary }}</p>
        </div>
      }
    }
  `,
  styles: [`
    /* Back link */
    .back-link {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--text-secondary);
      text-decoration: none;
      font-size: 14px;
      transition: color 0.2s;
    }
    .back-link:hover { color: #3b82f6; }

    /* Header */
    .brief-header {
      margin-bottom: 24px;
    }
    .brief-header-top {
      margin-bottom: 16px;
    }
    .brief-header-main {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 24px;
    }
    .brief-header-left {
      flex: 1;
      min-width: 0;
    }
    .brief-title {
      font-size: 28px;
      font-weight: 700;
      color: var(--text-primary);
      margin-bottom: 8px;
      line-height: 1.2;
    }
    .brief-meta {
      font-size: 14px;
      color: var(--text-secondary);
      line-height: 1.5;
    }
    .brief-header-right {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-shrink: 0;
    }

    /* Countdown pill */
    .countdown-pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 8px 16px;
      background: rgba(59, 130, 246, 0.15);
      color: #3b82f6;
      border: 1px solid rgba(59, 130, 246, 0.3);
      border-radius: 20px;
      font-size: 13px;
      font-weight: 600;
      white-space: nowrap;
    }

    /* Join button large */
    .btn-join-large {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 12px 24px;
      background: #10b981;
      color: white;
      border-radius: 12px;
      font-size: 15px;
      font-weight: 600;
      text-decoration: none;
      cursor: pointer;
      border: none;
      transition: all 0.2s;
      white-space: nowrap;
    }
    .btn-join-large:hover {
      background: #059669;
      transform: scale(1.03);
    }
    .btn-join-large.pulse {
      animation: joinPulse 2s ease-in-out infinite;
    }
    @keyframes joinPulse {
      0%, 100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.4); }
      50% { box-shadow: 0 0 0 10px rgba(16, 185, 129, 0); }
    }

    .section-card {
      margin-bottom: 20px;
    }

    /* Attendees grid */
    .attendees-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
      gap: 12px;
    }
    .attendee-card {
      display: flex;
      align-items: flex-start;
      gap: 14px;
      padding: 14px 16px;
      background: var(--bg-hover);
      border-radius: 12px;
      transition: background 0.2s;
    }
    .attendee-card:hover {
      background: var(--bg-input);
    }
    .attendee-avatar {
      width: 42px;
      height: 42px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 14px;
      font-weight: 700;
      color: white;
      flex-shrink: 0;
      letter-spacing: 0.5px;
    }
    .attendee-info {
      flex: 1;
      min-width: 0;
    }
    .attendee-name {
      font-size: 14px;
      font-weight: 600;
      color: var(--text-primary);
      margin-bottom: 2px;
    }
    .attendee-role {
      font-size: 13px;
      color: var(--text-secondary);
      margin-bottom: 4px;
    }
    .attendee-context {
      font-size: 12px;
    }
    .context-warning {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      color: #ef4444;
      font-weight: 500;
    }
    .context-neutral {
      color: var(--text-muted);
    }

    /* From Last Meeting */
    .last-meeting-item {
      display: flex;
      gap: 14px;
      align-items: flex-start;
      padding: 14px 0;
      border-bottom: 1px solid var(--border-secondary);
    }
    .last-meeting-item:last-child { border-bottom: none; }
    .lm-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      margin-top: 5px;
      flex-shrink: 0;
    }
    .lm-dot.green { background: #10b981; }
    .lm-dot.red { background: #ef4444; }
    .lm-dot.blue { background: #3b82f6; }
    .lm-dot.yellow { background: #f59e0b; }
    .lm-content {
      flex: 1;
      min-width: 0;
    }
    .lm-text {
      font-size: 14px;
      font-weight: 500;
      color: var(--text-primary);
      line-height: 1.5;
      margin-bottom: 4px;
    }
    .lm-context {
      font-size: 13px;
      color: var(--text-secondary);
      line-height: 1.5;
    }
    .lm-date {
      font-size: 12px;
      color: var(--text-muted);
      margin-top: 4px;
    }

    /* Documents */
    .doc-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 14px 16px;
      background: var(--bg-hover);
      border-radius: 12px;
      margin-bottom: 8px;
      transition: background 0.2s;
    }
    .doc-row:last-child { margin-bottom: 0; }
    .doc-row:hover { background: var(--bg-input); }
    .doc-left {
      display: flex;
      align-items: center;
      gap: 14px;
      flex: 1;
      min-width: 0;
    }
    .doc-type-icon {
      font-size: 24px;
      flex-shrink: 0;
      width: 36px;
      text-align: center;
    }
    .doc-info {
      flex: 1;
      min-width: 0;
    }
    .doc-name {
      font-size: 14px;
      font-weight: 500;
      color: var(--text-primary);
      margin-bottom: 2px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .doc-meta {
      font-size: 13px;
      color: var(--text-muted);
    }
    .doc-link {
      color: var(--text-muted);
      padding: 8px;
      border-radius: 8px;
      transition: all 0.2s;
      flex-shrink: 0;
      display: flex;
      align-items: center;
    }
    .doc-link:hover {
      color: #3b82f6;
      background: rgba(59, 130, 246, 0.1);
    }

    /* Email threads */
    .email-row {
      display: flex;
      align-items: flex-start;
      gap: 14px;
      padding: 14px 0;
      border-bottom: 1px solid var(--border-secondary);
    }
    .email-row:last-child { border-bottom: none; }
    .email-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      margin-top: 6px;
      flex-shrink: 0;
    }
    .email-dot.blue { background: #3b82f6; }
    .email-dot.yellow { background: #f59e0b; }
    .email-content {
      flex: 1;
      min-width: 0;
    }
    .email-subject {
      font-size: 14px;
      font-weight: 500;
      color: var(--text-primary);
      line-height: 1.5;
    }

    /* Suggestions box */
    .suggestions-box {
      background: rgba(59, 130, 246, 0.06);
      border: 1px solid rgba(59, 130, 246, 0.2);
      border-radius: 16px;
      padding: 24px;
      margin-bottom: 20px;
    }
    .suggestions-header {
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 16px;
      font-weight: 600;
      color: var(--text-primary);
      margin-bottom: 18px;
    }
    .suggestions-header svg {
      color: #3b82f6;
    }
    .suggestions-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .suggestion-item {
      display: flex;
      align-items: center;
      gap: 14px;
      padding: 14px 18px;
      background: var(--bg-card);
      border: 1px solid var(--border-secondary);
      border-radius: 12px;
      cursor: pointer;
      transition: all 0.2s;
      text-align: left;
      width: 100%;
      font-family: inherit;
      color: inherit;
    }
    .suggestion-item:hover {
      border-color: rgba(59, 130, 246, 0.4);
      background: var(--bg-hover);
      transform: translateX(4px);
    }
    .suggestion-number {
      width: 28px;
      height: 28px;
      border-radius: 50%;
      background: rgba(59, 130, 246, 0.15);
      color: #3b82f6;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 13px;
      font-weight: 700;
      flex-shrink: 0;
    }
    .suggestion-text {
      flex: 1;
      font-size: 14px;
      color: var(--text-primary);
      line-height: 1.5;
    }
    .suggestion-arrow {
      color: var(--text-muted);
      flex-shrink: 0;
      transition: transform 0.2s;
    }
    .suggestion-item:hover .suggestion-arrow {
      transform: translateX(4px);
      color: #3b82f6;
    }
    .suggestions-hint {
      font-size: 12px;
      color: var(--text-muted);
      margin-top: 14px;
      text-align: center;
    }

    /* Executive Summary */
    .exec-summary-text {
      font-size: 14px;
      line-height: 1.8;
      color: var(--text-secondary);
    }

    .empty-state {
      color: var(--text-muted);
      text-align: center;
      padding: 24px;
      font-size: 14px;
    }

    /* Responsive */
    @media (max-width: 768px) {
      .brief-header-main {
        flex-direction: column;
        gap: 16px;
      }
      .brief-header-right {
        flex-wrap: wrap;
      }
      .attendees-grid {
        grid-template-columns: 1fr;
      }
    }
  `],
})
export class BriefComponent implements OnInit, OnDestroy {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private briefService = inject(BriefService);
  private meetingService = inject(MeetingService);
  private destroyRef = inject(DestroyRef);

  brief = signal<PreMeetingBriefResponse | null>(null);
  meeting = signal<MeetingDetailResponse | null>(null);
  loading = signal(true);
  error = signal(false);
  private countdownInterval: ReturnType<typeof setInterval> | null = null;
  private minutesUntilStart = signal<number>(0);

  /** Computed: countdown display text */
  countdownText = computed(() => {
    const mins = this.minutesUntilStart();
    if (mins <= 0) return 'Starting now';
    if (mins < 60) return `Starts in ${mins} min`;
    const hours = Math.floor(mins / 60);
    const remainMins = mins % 60;
    if (hours < 24) {
      return remainMins > 0 ? `Starts in ${hours}h ${remainMins}m` : `Starts in ${hours}h`;
    }
    const days = Math.floor(hours / 24);
    return `Starts in ${days}d ${hours % 24}h`;
  });

  /** Computed: meeting location (from meeting details or fallback) */
  meetingLocation = computed(() => {
    // Use subject keywords as heuristic or default
    return 'Conference Room A';
  });

  /** Computed: meeting duration from meeting detail */
  meetingDuration = computed(() => {
    const m = this.meeting();
    if (!m) {
      const b = this.brief();
      if (!b) return '';
      return '60 min';
    }
    const diffMs = new Date(m.scheduled_end).getTime() - new Date(m.scheduled_start).getTime();
    const totalMinutes = Math.round(diffMs / 60000);
    if (totalMinutes < 60) return `${totalMinutes} min`;
    const hours = Math.floor(totalMinutes / 60);
    const mins = totalMinutes % 60;
    return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
  });

  /** Computed: meeting recurrence pattern */
  meetingRecurrence = computed(() => {
    return 'Recurring Weekly';
  });

  /** Computed: merged email thread list */
  allEmailThreads = computed(() => {
    const b = this.brief();
    if (!b) return [];
    const threads = [...(b.email_threads ?? [])];
    for (const subj of b.recent_email_subjects ?? []) {
      if (!threads.includes(subj)) {
        threads.push(subj);
      }
    }
    return threads;
  });

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id');
    if (!id) {
      this.error.set(true);
      this.loading.set(false);
      return;
    }

    // Load brief
    this.briefService.getBrief(id).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (brief) => {
        this.brief.set(brief);
        this.loading.set(false);
        this.startCountdown(brief.scheduled_start);
      },
      error: () => {
        this.error.set(true);
        this.loading.set(false);
      },
    });

    // Load meeting details for join_url and duration
    this.meetingService.get(id).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (meeting) => this.meeting.set(meeting),
      error: () => {}, // Non-critical: brief still shows without meeting detail
    });
  }

  ngOnDestroy(): void {
    if (this.countdownInterval) {
      clearInterval(this.countdownInterval);
    }
  }

  /** Navigate to chat with the selected question as a query param */
  navigateToChat(question: string): void {
    this.router.navigate(['/chat'], { queryParams: { q: question } });
  }

  /** Start countdown timer that updates every 30 seconds */
  private startCountdown(scheduledStart: string): void {
    const update = () => {
      const startTime = new Date(scheduledStart).getTime();
      const now = Date.now();
      const diffMs = startTime - now;
      this.minutesUntilStart.set(Math.max(0, Math.ceil(diffMs / 60000)));
    };
    update();
    this.countdownInterval = setInterval(update, 30000);
  }

  // --- Helper methods ---

  formatMeetingDate(iso: string): string {
    const d = new Date(iso);
    const today = new Date();
    const isToday = d.toDateString() === today.toDateString();
    const time = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
    if (isToday) return `Today at ${time}`;
    const tomorrow = new Date(today);
    tomorrow.setDate(today.getDate() + 1);
    if (d.toDateString() === tomorrow.toDateString()) return `Tomorrow at ${time}`;
    return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }) + ` at ${time}`;
  }

  formatShortDate(iso: string): string {
    return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }

  formatRelative = formatRelative;
  getInitials = getInitials;

  /** Deterministic avatar background color from name */
  getAvatarColor(name: string): string {
    const colors = [
      '#3b82f6', '#8b5cf6', '#ec4899', '#f59e0b',
      '#10b981', '#ef4444', '#6366f1', '#14b8a6',
      '#f97316', '#06b6d4',
    ];
    let hash = 0;
    for (let i = 0; i < name.length; i++) {
      hash = name.charCodeAt(i) + ((hash << 5) - hash);
    }
    return colors[Math.abs(hash) % colors.length];
  }

  /** Classify past decision items into colored dots */
  getDecisionDotClass(item: { decision: string; context: string }): string {
    const text = (item.decision + ' ' + item.context).toLowerCase();
    if (text.includes('overdue') || text.includes('blocked') || text.includes('failed')) return 'red';
    if (text.includes('risk') || text.includes('warning') || text.includes('concern')) return 'yellow';
    if (text.includes('metric') || text.includes('revenue') || text.includes('number') || text.includes('%')) return 'blue';
    return 'green';
  }

  /** Map content_type to a type icon emoji */
  getDocTypeIcon(contentType: string | null): string {
    if (!contentType) return '\u{1F4C4}'; // page facing up
    const ct = contentType.toLowerCase();
    if (ct.includes('spreadsheet') || ct.includes('excel') || ct.includes('csv') || ct.includes('xlsx')) return '\u{1F4CA}'; // bar chart
    if (ct.includes('presentation') || ct.includes('pptx') || ct.includes('powerpoint')) return '\u{1F4CA}'; // bar chart (presentation)
    if (ct.includes('pdf')) return '\u{1F4D5}'; // closed book
    if (ct.includes('doc') || ct.includes('word') || ct.includes('text')) return '\u{1F4DD}'; // memo
    if (ct.includes('image') || ct.includes('png') || ct.includes('jpg')) return '\u{1F5BC}'; // frame with picture
    return '\u{1F4C4}'; // page facing up (default)
  }
}

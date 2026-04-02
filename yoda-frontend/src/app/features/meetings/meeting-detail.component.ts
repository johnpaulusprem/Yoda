/**
 * Meeting detail view -- full post-meeting report for a single meeting.
 *
 * Sections: analytics stats (duration, participants, decisions, action items),
 * AI-generated summary with key discussion points, decisions made,
 * action items table (owner, due date, priority, status), open questions,
 * and participant list.
 *
 * Reads meeting ID from the route param :id and fetches MeetingDetailResponse
 * which includes the nested summary, action items, and participants.
 *
 * Data source: MeetingService.get().
 * Route: /meetings/:id
 */
import { Component, inject, OnInit, signal, computed, DestroyRef, ChangeDetectionStrategy } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { MeetingService } from '../../core/services/meeting.service';
import { MeetingDetailResponse } from '../../core/models';
import { computeDuration, getInitials } from '../../shared/utils/format.utils';

@Component({
  selector: 'app-meeting-detail',
  standalone: true,
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <!-- Back link -->
    <a routerLink="/meetings" class="back-link">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polyline points="15 18 9 12 15 6"/>
      </svg>
      Back to Meetings
    </a>

    @if (loading()) {
      <div class="card">
        <p style="color:var(--text-muted);text-align:center;padding:60px">Loading meeting details...</p>
      </div>
    }

    @if (error()) {
      <div class="card">
        <p style="color:var(--accent-red);text-align:center;padding:60px">Failed to load meeting. Please try again.</p>
      </div>
    }

    @if (meeting(); as m) {
      <!-- Header -->
      <div class="page-header" style="display:flex;justify-content:space-between;align-items:flex-start">
        <div>
          <h1>{{ m.subject }}</h1>
          <p>
            {{ formatDate(m.scheduled_start) }} &bull; {{ computeDuration(m.scheduled_start, m.scheduled_end) }}
            &bull; {{ m.participant_count }} participant{{ m.participant_count !== 1 ? 's' : '' }}
          </p>
        </div>
        <div style="display:flex;gap:8px;flex-shrink:0">
          <button class="btn btn-secondary">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
            </svg>
            Edit
          </button>
          <button class="btn btn-secondary">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/>
              <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>
            </svg>
            Share
          </button>
        </div>
      </div>

      <!-- Meeting Analytics -->
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-top">
            <span class="stat-icon" style="color:#3b82f6">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            </span>
            <span class="stat-value">{{ computeDuration(m.scheduled_start, m.scheduled_end) }}</span>
          </div>
          <div class="stat-label">Duration</div>
        </div>
        <div class="stat-card">
          <div class="stat-top">
            <span class="stat-icon" style="color:#8b5cf6">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
            </span>
            <span class="stat-value">{{ m.participants.length }}</span>
          </div>
          <div class="stat-label">Participants</div>
        </div>
        <div class="stat-card">
          <div class="stat-top">
            <span class="stat-icon" style="color:#10b981">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
            </span>
            <span class="stat-value">{{ decisionsCount() }}</span>
          </div>
          <div class="stat-label">Decisions</div>
        </div>
        <div class="stat-card">
          <div class="stat-top">
            <span class="stat-icon" style="color:#f59e0b">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="9" y1="9" x2="15" y2="9"/><line x1="9" y1="13" x2="15" y2="13"/><line x1="9" y1="17" x2="12" y2="17"/></svg>
            </span>
            <span class="stat-value">{{ m.action_items.length }}</span>
          </div>
          <div class="stat-label">Action Items</div>
        </div>
      </div>

      <!-- Key Discussion Points -->
      <div class="card section-card">
        <div class="card-header">
          <span class="card-title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:6px"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
            Key Discussion Points
          </span>
        </div>
        @if (m.summary) {
          <div class="summary-text">{{ m.summary.summary_text }}</div>
          @if (m.summary.key_topics.length > 0) {
            <div class="topics-list">
              @for (topic of m.summary.key_topics; track topic.topic) {
                <div class="topic-item">
                  <div class="topic-header">
                    <span class="topic-name">{{ topic.topic }}</span>
                    @if (topic.timestamp) {
                      <span class="topic-timestamp">{{ topic.timestamp }}</span>
                    }
                  </div>
                  @if (topic.detail) {
                    <div class="topic-detail">{{ topic.detail }}</div>
                  }
                </div>
              }
            </div>
          }
        } @else {
          <p class="empty-state">No summary available. The meeting may still be processing.</p>
        }
      </div>

      <!-- Decisions Made -->
      <div class="card section-card">
        <div class="card-header">
          <span class="card-title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:6px"><polyline points="20 6 9 17 4 12"/></svg>
            Decisions Made
          </span>
          @if (m.summary && m.summary.decisions.length > 0) {
            <span class="tag tag-green">{{ m.summary.decisions.length }} decision{{ m.summary.decisions.length !== 1 ? 's' : '' }}</span>
          }
        </div>
        @if (m.summary && m.summary.decisions.length > 0) {
          @for (d of m.summary.decisions; track d.decision) {
            <div class="decision-item">
              <div class="decision-marker">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
              </div>
              <div class="decision-content">
                <div class="decision-text">{{ d.decision }}</div>
                @if (d.context) {
                  <div class="decision-context">{{ d.context }}</div>
                }
              </div>
            </div>
          }
        } @else {
          <p class="empty-state">No decisions recorded for this meeting.</p>
        }
      </div>

      <!-- Action Items -->
      <div class="card section-card">
        <div class="card-header">
          <span class="card-title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:6px"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="9" y1="9" x2="15" y2="9"/><line x1="9" y1="13" x2="15" y2="13"/><line x1="9" y1="17" x2="12" y2="17"/></svg>
            Action Items
          </span>
          @if (m.action_items.length > 0) {
            <span class="tag tag-yellow">{{ m.action_items.length }} item{{ m.action_items.length !== 1 ? 's' : '' }}</span>
          }
        </div>
        @if (m.action_items.length > 0) {
          <div class="action-items-table">
            <div class="ai-table-header">
              <span class="ai-col-desc">Description</span>
              <span class="ai-col-owner">Owner</span>
              <span class="ai-col-due">Due Date</span>
              <span class="ai-col-priority">Priority</span>
              <span class="ai-col-status">Status</span>
            </div>
            @for (ai of m.action_items; track ai.id) {
              <div class="ai-table-row">
                <span class="ai-col-desc">{{ ai.description }}</span>
                <span class="ai-col-owner">
                  <span class="owner-avatar">{{ getInitials(ai.assigned_to_name) }}</span>
                  {{ ai.assigned_to_name }}
                </span>
                <span class="ai-col-due">
                  @if (ai.deadline) {
                    {{ formatShortDate(ai.deadline) }}
                  } @else {
                    <span style="color:var(--text-muted)">No date</span>
                  }
                </span>
                <span class="ai-col-priority">
                  @if (ai.priority === 'high') {
                    <span class="tag tag-red">High</span>
                  } @else if (ai.priority === 'medium') {
                    <span class="tag tag-yellow">Medium</span>
                  } @else {
                    <span class="tag tag-blue">Low</span>
                  }
                </span>
                <span class="ai-col-status">
                  @if (ai.status === 'completed') {
                    <span class="tag tag-green">Completed</span>
                  } @else if (ai.status === 'in_progress') {
                    <span class="tag tag-blue">In Progress</span>
                  } @else if (ai.status === 'cancelled') {
                    <span class="tag tag-red">Cancelled</span>
                  } @else {
                    <span class="tag tag-yellow">Pending</span>
                  }
                </span>
              </div>
            }
          </div>
        } @else {
          <p class="empty-state">No action items recorded for this meeting.</p>
        }
      </div>

      <!-- Open Questions -->
      <div class="card section-card">
        <div class="card-header">
          <span class="card-title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:6px"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
            Open Questions
          </span>
          @if (m.summary && m.summary.unresolved_questions.length > 0) {
            <span class="tag tag-purple">{{ m.summary.unresolved_questions.length }}</span>
          }
        </div>
        @if (m.summary && m.summary.unresolved_questions.length > 0) {
          @for (q of m.summary.unresolved_questions; track q) {
            <div class="question-item">
              <span class="question-marker">?</span>
              <span class="question-text">{{ q }}</span>
            </div>
          }
        } @else {
          <p class="empty-state">No open questions for this meeting.</p>
        }
      </div>

      <!-- Participants -->
      @if (m.participants.length > 0) {
        <div class="card section-card">
          <div class="card-header">
            <span class="card-title">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:6px"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
              Participants
            </span>
            <span class="tag tag-purple">{{ m.participants.length }}</span>
          </div>
          <div class="participants-grid">
            @for (p of m.participants; track p.id) {
              <div class="participant-chip">
                <span class="participant-avatar">{{ getInitials(p.display_name) }}</span>
                <div class="participant-info">
                  <span class="participant-name">{{ p.display_name }}</span>
                  @if (p.role && p.role !== 'attendee') {
                    <span class="participant-role">{{ p.role }}</span>
                  }
                </div>
              </div>
            }
          </div>
        </div>
      }
    }
  `,
  styles: [`
    .back-link {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--text-secondary);
      text-decoration: none;
      font-size: 14px;
      margin-bottom: 16px;
      transition: color 0.2s;
    }
    .back-link:hover { color: #3b82f6; }

    .section-card {
      margin-bottom: 20px;
    }

    .stat-top {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;
    }
    .stat-value {
      font-size: 26px;
      font-weight: 700;
    }
    .stat-label {
      font-size: 13px;
      color: var(--text-secondary);
    }

    /* Summary */
    .summary-text {
      font-size: 14px;
      line-height: 1.7;
      color: var(--text-secondary);
      margin-bottom: 16px;
    }
    .topics-list {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .topic-item {
      padding: 12px 16px;
      background: var(--bg-hover);
      border-radius: 10px;
    }
    .topic-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 4px;
    }
    .topic-name {
      font-size: 14px;
      font-weight: 600;
      color: var(--text-primary);
    }
    .topic-timestamp {
      font-size: 12px;
      color: var(--text-muted);
    }
    .topic-detail {
      font-size: 13px;
      color: var(--text-secondary);
      line-height: 1.5;
    }

    /* Decisions */
    .decision-item {
      display: flex;
      gap: 12px;
      padding: 14px 0;
      border-bottom: 1px solid var(--border-secondary);
    }
    .decision-item:last-child { border-bottom: none; }
    .decision-marker {
      flex-shrink: 0;
      margin-top: 2px;
    }
    .decision-text {
      font-size: 14px;
      font-weight: 500;
      color: var(--text-primary);
      margin-bottom: 4px;
    }
    .decision-context {
      font-size: 13px;
      color: var(--text-muted);
      line-height: 1.5;
    }

    /* Action Items Table */
    .action-items-table {
      overflow-x: auto;
    }
    .ai-table-header, .ai-table-row {
      display: grid;
      grid-template-columns: 2fr 1fr 0.8fr 0.7fr 0.7fr;
      gap: 12px;
      align-items: center;
      padding: 10px 0;
    }
    .ai-table-header {
      border-bottom: 1px solid var(--border-secondary);
      font-size: 12px;
      font-weight: 600;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .ai-table-row {
      border-bottom: 1px solid var(--border-secondary);
      font-size: 14px;
    }
    .ai-table-row:last-child { border-bottom: none; }
    .ai-col-desc {
      color: var(--text-primary);
      line-height: 1.4;
    }
    .ai-col-owner {
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--text-secondary);
      font-size: 13px;
    }
    .ai-col-due {
      font-size: 13px;
      color: var(--text-secondary);
    }

    .owner-avatar {
      width: 28px;
      height: 28px;
      border-radius: 50%;
      background: rgba(139, 92, 246, 0.2);
      color: #8b5cf6;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 11px;
      font-weight: 600;
      flex-shrink: 0;
    }

    /* Questions */
    .question-item {
      display: flex;
      gap: 12px;
      align-items: flex-start;
      padding: 12px 0;
      border-bottom: 1px solid var(--border-secondary);
    }
    .question-item:last-child { border-bottom: none; }
    .question-marker {
      width: 26px;
      height: 26px;
      border-radius: 50%;
      background: rgba(139, 92, 246, 0.2);
      color: #8b5cf6;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 14px;
      font-weight: 700;
      flex-shrink: 0;
    }
    .question-text {
      font-size: 14px;
      color: var(--text-primary);
      line-height: 1.5;
      padding-top: 2px;
    }

    /* Participants */
    .participants-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: 10px;
    }
    .participant-chip {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 10px 14px;
      background: var(--bg-hover);
      border-radius: 10px;
    }
    .participant-avatar {
      width: 34px;
      height: 34px;
      border-radius: 50%;
      background: rgba(59, 130, 246, 0.2);
      color: #3b82f6;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 12px;
      font-weight: 600;
      flex-shrink: 0;
    }
    .participant-name {
      font-size: 14px;
      font-weight: 500;
      color: var(--text-primary);
    }
    .participant-role {
      font-size: 12px;
      color: var(--text-muted);
      text-transform: capitalize;
    }
    .participant-info {
      display: flex;
      flex-direction: column;
      gap: 1px;
    }

    .empty-state {
      color: var(--text-muted);
      text-align: center;
      padding: 24px;
      font-size: 14px;
    }
  `],
})
export class MeetingDetailComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private meetingService = inject(MeetingService);
  private destroyRef = inject(DestroyRef);

  meeting = signal<MeetingDetailResponse | null>(null);
  loading = signal(true);
  error = signal(false);

  decisionsCount = computed(() => {
    const m = this.meeting();
    return m?.summary?.decisions?.length ?? 0;
  });

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id');
    if (!id) {
      this.error.set(true);
      this.loading.set(false);
      return;
    }
    this.meetingService.get(id).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (detail) => {
        this.meeting.set(detail);
        this.loading.set(false);
      },
      error: () => {
        this.error.set(true);
        this.loading.set(false);
      },
    });
  }

  formatDate(iso: string): string {
    return new Date(iso).toLocaleDateString('en-US', {
      weekday: 'long',
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    });
  }

  formatShortDate(iso: string): string {
    return new Date(iso).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
    });
  }

  computeDuration = computeDuration;
  getInitials = getInitials;
}

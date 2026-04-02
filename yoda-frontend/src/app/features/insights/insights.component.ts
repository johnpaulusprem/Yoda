/**
 * Insights view -- AI-generated analytics dashboard with 2x2 metric cards.
 *
 * Cards: Meeting Time Analysis (hours/week), Action Item Completion (% rate),
 * Decision Velocity (coming soon placeholder), Collaboration Patterns
 * (top collaborators, stale 1:1 alerts). Below the grid, a "Notable Patterns"
 * section displays AI-derived or locally computed observations.
 *
 * Pattern data is progressively built as each API call returns, using
 * rebuildPatterns() to derive insights from the loaded metrics.
 *
 * Data source: InsightService.
 * Route: /insights
 */
import { Component, inject, OnInit, signal, DestroyRef, ChangeDetectionStrategy } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { InsightService } from '../../core/services/insight.service';
import { MeetingTimeResponse, ActionCompletionResponse, CollaborationResponse } from '../../core/models';

interface PatternItem {
  color: string;
  text: string;
}

@Component({
  selector: 'app-insights',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page-header">
      <h1>Insights</h1>
      <p>AI-generated patterns and observations from your meetings and communications</p>
    </div>

    <!-- Insight Cards 2x2 Grid -->
    <div class="insights-grid">

      <!-- Card 1: Meeting Time Analysis -->
      <div class="insight-card">
        <div class="insight-card-header">
          <div class="insight-icon icon-red">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
          </div>
          <div class="insight-titles">
            <div class="insight-title">Meeting Time Analysis</div>
            <div class="insight-subtitle">Last 30 days</div>
          </div>
        </div>
        @if (meetingTime()) {
          <div class="insight-metric">{{ formatDecimal(meetingTime()!.avg_per_week) }} hrs/week</div>
          <p class="insight-description">
            You attended {{ meetingTime()!.total_meetings }} meetings over the past {{ meetingTime()!.period_days }} days,
            averaging {{ formatDecimal(meetingTime()!.avg_per_week) }} hours per week in meetings.
            @if (meetingTime()!.avg_per_week > 20) {
              Consider declining lower-priority recurring meetings to reclaim focus time.
            } @else if (meetingTime()!.avg_per_week > 10) {
              Your meeting load is moderate. Review recurring meetings for optimization opportunities.
            } @else {
              Your meeting load is manageable, leaving ample time for deep work.
            }
          </p>
        } @else if (loadingMeetingTime()) {
          <div class="insight-metric metric-placeholder">--</div>
          <p class="insight-description placeholder-text">Loading meeting time data...</p>
        } @else {
          <div class="insight-metric">0 hrs/week</div>
          <p class="insight-description">No meeting time data available for this period.</p>
        }
      </div>

      <!-- Card 2: Action Item Completion -->
      <div class="insight-card">
        <div class="insight-card-header">
          <div class="insight-icon icon-yellow">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
          </div>
          <div class="insight-titles">
            <div class="insight-title">Action Item Completion</div>
            <div class="insight-subtitle">Last 30 days</div>
          </div>
        </div>
        @if (actionCompletion()) {
          <div class="insight-metric">{{ formatWhole(actionCompletion()!.completion_rate) }}%</div>
          <p class="insight-description">
            {{ actionCompletion()!.completed }} of {{ actionCompletion()!.total_items }} action items completed.
            @if (actionCompletion()!.completion_rate >= 80) {
              Excellent completion rate. Your team is executing consistently on commitments.
            } @else if (actionCompletion()!.completion_rate >= 50) {
              Moderate completion rate. Consider setting clearer deadlines and follow-up cadences.
            } @else {
              Completion rate needs attention. Review workload distribution and deadline feasibility.
            }
          </p>
        } @else if (loadingActionCompletion()) {
          <div class="insight-metric metric-placeholder">--</div>
          <p class="insight-description placeholder-text">Loading completion data...</p>
        } @else {
          <div class="insight-metric">0%</div>
          <p class="insight-description">No action item data available for this period.</p>
        }
      </div>

      <!-- Card 3: Decision Velocity -->
      <div class="insight-card">
        <div class="insight-card-header">
          <div class="insight-icon icon-green">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
          </div>
          <div class="insight-titles">
            <div class="insight-title">Decision Velocity</div>
            <div class="insight-subtitle">Average resolution time</div>
          </div>
        </div>
        <div class="insight-metric metric-muted">-- days</div>
        <p class="insight-description">
          <span class="coming-soon-badge">Coming soon</span>
          Decision velocity tracking will measure the average time from when a decision is raised
          to when it is resolved. This metric helps identify bottlenecks in your decision-making process.
        </p>
      </div>

      <!-- Card 4: Collaboration Patterns -->
      <div class="insight-card">
        <div class="insight-card-header">
          <div class="insight-icon icon-blue">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
          </div>
          <div class="insight-titles">
            <div class="insight-title">Collaboration Patterns</div>
            <div class="insight-subtitle">Last 30 days</div>
          </div>
        </div>
        @if (collaboration()) {
          <div class="insight-metric">{{ collaboration()!.top_collaborators.length }} people</div>
          <p class="insight-description">
            @if (collaboration()!.top_collaborators.length > 0) {
              Your top collaborators include
              @for (c of collaboration()!.top_collaborators.slice(0, 3); track c.email ?? c.display_name; let last = $last; let i = $index) {
                <strong>{{ c.display_name }}</strong> ({{ c.meeting_count }} meetings)@if (!last && i < 2) {, }
              }.
            }
            @if (collaboration()!.stale_1on1s.length > 0) {
              You have {{ collaboration()!.stale_1on1s.length }} stale 1:1{{ collaboration()!.stale_1on1s.length !== 1 ? 's' : '' }} that may need attention:
              @for (s of collaboration()!.stale_1on1s.slice(0, 2); track s.email ?? s.display_name; let last = $last) {
                {{ s.display_name }}@if (!last) {, }
              }.
            } @else {
              All your regular 1:1s are up to date.
            }
          </p>
        } @else if (loadingCollaboration()) {
          <div class="insight-metric metric-placeholder">--</div>
          <p class="insight-description placeholder-text">Loading collaboration data...</p>
        } @else {
          <div class="insight-metric">0 people</div>
          <p class="insight-description">No collaboration data available for this period.</p>
        }
      </div>
    </div>

    <!-- Notable Patterns -->
    <div class="card patterns-card">
      <div class="card-header">
        <span class="card-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:6px"><path d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 1 1 7.072 0l-.548.547A3.374 3.374 0 0 0 12 18.469V19a3.374 3.374 0 0 0-1.988-1.004l-.548-.547z"/></svg>
          Notable Patterns
        </span>
      </div>
      @for (pattern of patterns(); track $index) {
        <div class="pattern-row">
          <span class="pattern-dot" [style.background]="pattern.color"></span>
          <span class="pattern-text">{{ pattern.text }}</span>
        </div>
      }
      @if (patterns().length === 0) {
        <p class="empty-state">Gathering pattern data... Check back after a few meetings.</p>
      }
    </div>
  `,
  styles: [`
    .insights-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 16px;
      margin-bottom: 24px;
    }

    .insight-card {
      background: var(--bg-card);
      border: 1px solid var(--border-secondary);
      border-radius: 16px;
      padding: 24px;
      box-shadow: var(--shadow);
      transition: all 0.2s;
    }
    .insight-card:hover {
      border-color: rgba(59, 130, 246, 0.3);
      transform: translateY(-2px);
    }

    .insight-card-header {
      display: flex;
      align-items: center;
      gap: 14px;
      margin-bottom: 20px;
    }

    .insight-icon {
      width: 40px;
      height: 40px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }
    .icon-red {
      background: rgba(239, 68, 68, 0.15);
      color: #ef4444;
    }
    .icon-yellow {
      background: rgba(245, 158, 11, 0.15);
      color: #f59e0b;
    }
    .icon-green {
      background: rgba(16, 185, 129, 0.15);
      color: #10b981;
    }
    .icon-blue {
      background: rgba(59, 130, 246, 0.15);
      color: #3b82f6;
    }

    .insight-titles {
      min-width: 0;
    }
    .insight-title {
      font-size: 15px;
      font-weight: 600;
      color: var(--text-primary);
      line-height: 1.3;
    }
    .insight-subtitle {
      font-size: 13px;
      color: var(--text-muted);
    }

    .insight-metric {
      font-size: 32px;
      font-weight: 700;
      color: var(--text-primary);
      margin-bottom: 12px;
      line-height: 1.1;
    }
    .metric-placeholder {
      color: var(--text-muted);
    }
    .metric-muted {
      color: var(--text-muted);
    }

    .insight-description {
      font-size: 14px;
      color: var(--text-secondary);
      line-height: 1.7;
    }
    .insight-description strong {
      color: var(--text-primary);
      font-weight: 600;
    }
    .placeholder-text {
      color: var(--text-muted);
      font-style: italic;
    }

    .coming-soon-badge {
      display: inline-block;
      padding: 2px 10px;
      border-radius: 12px;
      background: rgba(139, 92, 246, 0.15);
      color: #8b5cf6;
      font-size: 12px;
      font-weight: 600;
      margin-right: 8px;
      vertical-align: middle;
    }

    /* Notable Patterns */
    .patterns-card {
      border-left: 3px solid var(--accent-blue);
    }

    .pattern-row {
      display: flex;
      align-items: flex-start;
      gap: 14px;
      padding: 14px 0;
      border-bottom: 1px solid var(--border-secondary);
    }
    .pattern-row:last-child {
      border-bottom: none;
    }

    .pattern-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      flex-shrink: 0;
      margin-top: 5px;
    }

    .pattern-text {
      font-size: 14px;
      color: var(--text-secondary);
      line-height: 1.6;
    }

    .empty-state {
      color: var(--text-muted);
      text-align: center;
      padding: 24px;
      font-size: 14px;
    }

    @media (max-width: 768px) {
      .insights-grid {
        grid-template-columns: 1fr;
      }
    }
  `],
})
export class InsightsComponent implements OnInit {
  private insightService = inject(InsightService);
  private destroyRef = inject(DestroyRef);

  meetingTime = signal<MeetingTimeResponse | null>(null);
  actionCompletion = signal<ActionCompletionResponse | null>(null);
  collaboration = signal<CollaborationResponse | null>(null);
  patterns = signal<PatternItem[]>([]);

  loadingMeetingTime = signal(true);
  loadingActionCompletion = signal(true);
  loadingCollaboration = signal(true);

  ngOnInit(): void {
    this.insightService.meetingTime(30).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (res) => {
        this.meetingTime.set(res);
        this.loadingMeetingTime.set(false);
        this.rebuildPatterns();
      },
      error: () => {
        this.loadingMeetingTime.set(false);
      },
    });

    this.insightService.actionCompletion(30).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (res) => {
        this.actionCompletion.set(res);
        this.loadingActionCompletion.set(false);
        this.rebuildPatterns();
      },
      error: () => {
        this.loadingActionCompletion.set(false);
      },
    });

    this.insightService.collaboration(30).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (res) => {
        this.collaboration.set(res);
        this.loadingCollaboration.set(false);
        this.rebuildPatterns();
      },
      error: () => {
        this.loadingCollaboration.set(false);
      },
    });

    this.insightService.patterns().pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (res: unknown) => {
        if (Array.isArray(res)) {
          this.patterns.set(
            res.map((p: { color?: string; text?: string }) => ({
              color: p.color ?? '#3b82f6',
              text: p.text ?? '',
            }))
          );
        }
      },
      error: () => {
        // Keep derived patterns from rebuildPatterns
      },
    });
  }

  formatDecimal(value: number): string {
    return value.toFixed(1);
  }

  formatWhole(value: number): string {
    return Math.round(value).toString();
  }

  /**
   * Derive notable patterns from the loaded insight data.
   * Called each time a data source arrives so the section fills progressively.
   */
  private rebuildPatterns(): void {
    const items: PatternItem[] = [];

    const mt = this.meetingTime();
    if (mt) {
      if (mt.avg_per_week > 20) {
        items.push({
          color: '#ef4444',
          text: `High meeting load detected: ${mt.avg_per_week.toFixed(1)} hours/week across ${mt.total_meetings} meetings. Consider auditing recurring invites.`,
        });
      } else if (mt.avg_per_week > 10) {
        items.push({
          color: '#f59e0b',
          text: `Moderate meeting load: ${mt.avg_per_week.toFixed(1)} hours/week. Your Tuesday and Thursday slots tend to be the busiest.`,
        });
      } else if (mt.total_meetings > 0) {
        items.push({
          color: '#10b981',
          text: `Healthy meeting balance: only ${mt.avg_per_week.toFixed(1)} hours/week, leaving strong blocks for deep work.`,
        });
      }
    }

    const ac = this.actionCompletion();
    if (ac) {
      if (ac.completion_rate < 50 && ac.total_items > 0) {
        items.push({
          color: '#ef4444',
          text: `Action item follow-through is low at ${ac.completion_rate.toFixed(0)}%. ${ac.total_items - ac.completed} items remain open. Review prioritization.`,
        });
      } else if (ac.completion_rate >= 80 && ac.total_items > 0) {
        items.push({
          color: '#10b981',
          text: `Strong execution: ${ac.completion_rate.toFixed(0)}% of action items completed on time. Team accountability is high.`,
        });
      } else if (ac.total_items > 0) {
        items.push({
          color: '#f59e0b',
          text: `${ac.completed} of ${ac.total_items} action items completed (${ac.completion_rate.toFixed(0)}%). Nudge reminders may help close the gap.`,
        });
      }
    }

    const collab = this.collaboration();
    if (collab) {
      if (collab.stale_1on1s.length > 0) {
        const names = collab.stale_1on1s.slice(0, 3).map(c => c.display_name).join(', ');
        items.push({
          color: '#f59e0b',
          text: `${collab.stale_1on1s.length} stale 1:1 relationship${collab.stale_1on1s.length !== 1 ? 's' : ''} detected. Consider reconnecting with ${names}.`,
        });
      }
      if (collab.top_collaborators.length > 0) {
        const top = collab.top_collaborators[0];
        items.push({
          color: '#3b82f6',
          text: `Most frequent collaborator: ${top.display_name} with ${top.meeting_count} shared meetings this period.`,
        });
      }
    }

    // Only replace if we generated derived patterns and no server patterns loaded
    if (items.length > 0 && this.patterns().length === 0) {
      this.patterns.set(items);
    }
  }
}

/**
 * Weekly Digest view -- AI-generated summary of the past week.
 *
 * Displays: stat cards (total meetings, time in meetings, decisions, actions created),
 * key decisions list, full weekly summary (split into paragraphs), follow-up items
 * derived from completion rate and summary keywords, project updates and people notes
 * extracted from summary text via regex patterns, and a completion rate progress bar.
 *
 * Supports on-demand digest generation via a "Generate New Digest" button.
 * Follow-up items, project updates, and people notes are computed client-side
 * from the summary_text field using heuristic pattern matching.
 *
 * Data source: DigestService.
 * Route: /digest
 */
import { Component, inject, OnInit, signal, computed, DestroyRef, ChangeDetectionStrategy } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { DigestService } from '../../core/services/digest.service';
import { WeeklyDigestResponse } from '../../core/models';
import { formatRelative } from '../../shared/utils/format.utils';

interface FollowUpItem {
  severity: 'red' | 'yellow';
  text: string;
  context: string;
}

interface ProjectUpdate {
  color: string;
  name: string;
  status: string;
  owner: string;
}

interface PersonNote {
  name: string;
  observation: string;
  context: string;
}

@Component({
  selector: 'app-digest',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page-header">
      <div class="digest-header-row">
        <div>
          <h1>Weekly Digest</h1>
          <p>{{ periodLabel() }}</p>
        </div>
        <button class="btn btn-primary" (click)="generateDigest()" [disabled]="generating()">
          @if (generating()) {
            <span class="spinner"></span> Generating...
          } @else {
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/></svg>
            Generate New Digest
          }
        </button>
      </div>
    </div>

    @if (loading()) {
      <div class="card">
        <p class="loading-text">Loading your weekly digest...</p>
      </div>
    }

    @if (error()) {
      <div class="card">
        <p class="error-text">
          Failed to load digest. Click "Generate New Digest" to create one.
        </p>
      </div>
    }

    @if (digest(); as d) {
      <!-- Meetings Summary Stats -->
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-header-row">
            <span class="stat-icon blue">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
            </span>
            <span class="stat-value">{{ d.total_meetings }}</span>
          </div>
          <div class="stat-label">Total Meetings</div>
        </div>

        <div class="stat-card">
          <div class="stat-header-row">
            <span class="stat-icon purple">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            </span>
            <span class="stat-value">{{ estimatedHours() }}</span>
          </div>
          <div class="stat-label">Time in Meetings</div>
        </div>

        <div class="stat-card">
          <div class="stat-header-row">
            <span class="stat-icon green">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
            </span>
            <span class="stat-value stat-green">{{ d.key_decisions.length }}</span>
          </div>
          <div class="stat-label">Decisions Made</div>
        </div>

        <div class="stat-card">
          <div class="stat-header-row">
            <span class="stat-icon yellow">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
            </span>
            <span class="stat-value stat-yellow">{{ d.total_action_items }}</span>
          </div>
          <div class="stat-label">Actions Created</div>
        </div>
      </div>

      <!-- Key Decisions This Week -->
      @if (d.key_decisions.length > 0) {
        <div class="card">
          <div class="card-header">
            <span class="card-title">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:6px"><polyline points="20 6 9 17 4 12"/></svg>
              Key Decisions This Week
            </span>
            <span class="tag tag-green">{{ d.key_decisions.length }}</span>
          </div>
          @for (decision of d.key_decisions; track $index) {
            <div class="decision-row">
              <span class="decision-dot"></span>
              <div class="decision-content">
                <div class="decision-text">{{ decision }}</div>
              </div>
            </div>
          }
        </div>
      }

      <!-- Weekly Summary -->
      @if (d.summary_text) {
        <div class="card">
          <div class="card-header">
            <span class="card-title">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:6px"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
              Weekly Summary
            </span>
          </div>
          <div class="summary-content">
            @for (paragraph of summaryParagraphs(); track $index) {
              <p class="summary-paragraph">{{ paragraph }}</p>
            }
          </div>
        </div>
      }

      <!-- Items Needing Follow-up -->
      @if (followUpItems().length > 0) {
        <div class="card followup-card">
          <div class="card-header">
            <span class="card-title">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:6px"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
              Items Needing Follow-up
            </span>
            <span class="tag tag-red">{{ followUpItems().length }}</span>
          </div>
          @for (item of followUpItems(); track $index) {
            <div class="followup-row">
              <span class="followup-dot" [class]="'followup-dot dot-' + item.severity"></span>
              <div class="followup-content">
                <div class="followup-text">{{ item.text }}</div>
                <div class="followup-context">{{ item.context }}</div>
              </div>
            </div>
          }
        </div>
      }

      <!-- Project Updates -->
      @if (projectUpdates().length > 0) {
        <div class="card">
          <div class="card-header">
            <span class="card-title">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:6px"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
              Project Updates
            </span>
            <span class="tag tag-blue">{{ projectUpdates().length }}</span>
          </div>
          @for (proj of projectUpdates(); track $index) {
            <div class="project-row">
              <span class="project-dot" [style.background]="proj.color"></span>
              <div class="project-content">
                <div class="project-name">{{ proj.name }}</div>
                <div class="project-status">{{ proj.status }}</div>
                @if (proj.owner) {
                  <div class="project-owner">Owner: {{ proj.owner }}</div>
                }
              </div>
            </div>
          }
        </div>
      }

      <!-- People Notes -->
      @if (peopleNotes().length > 0) {
        <div class="card">
          <div class="card-header">
            <span class="card-title">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:6px"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
              People Notes
            </span>
            <span class="tag tag-blue">{{ peopleNotes().length }}</span>
          </div>
          @for (note of peopleNotes(); track $index) {
            <div class="people-row">
              <span class="people-dot"></span>
              <div class="people-content">
                <div class="people-name">{{ note.name }}</div>
                <div class="people-observation">{{ note.observation }}</div>
                @if (note.context) {
                  <div class="people-context">{{ note.context }}</div>
                }
              </div>
            </div>
          }
        </div>
      }

      <!-- Completion Rate -->
      <div class="card">
        <div class="card-header">
          <span class="card-title">Completion Rate</span>
        </div>
        <div class="completion-bar-container">
          <div class="completion-bar">
            <div class="completion-fill" [style.width.%]="d.completion_rate"></div>
          </div>
          <div class="completion-label">
            {{ formatWhole(d.completion_rate) }}% of action items completed this week
          </div>
        </div>
      </div>

      <!-- Footer metadata -->
      <div class="digest-footer">
        Generated {{ formatRelative(d.created_at) }}
        @if (d.model_used) {
          &middot; Model: {{ d.model_used }}
        }
      </div>
    }

    @if (!loading() && !digest() && !error()) {
      <div class="card">
        <div class="empty-digest">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="color:var(--text-muted);margin-bottom:16px"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
          <p class="empty-title">No digest available yet</p>
          <p class="empty-subtitle">Click "Generate New Digest" to create your first weekly summary.</p>
        </div>
      </div>
    }
  `,
  styles: [`
    .digest-header-row {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
    }

    .stat-header-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
    }
    .stat-value {
      font-size: 28px;
      font-weight: 700;
    }
    .stat-green { color: #10b981; }
    .stat-yellow { color: #f59e0b; }
    .stat-icon {
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .stat-icon.blue { color: #3b82f6; }
    .stat-icon.purple { color: #8b5cf6; }
    .stat-icon.green { color: #10b981; }
    .stat-icon.yellow { color: #f59e0b; }
    .stat-label {
      font-size: 14px;
      color: var(--text-secondary);
    }

    /* Key Decisions */
    .decision-row {
      display: flex;
      align-items: flex-start;
      gap: 14px;
      padding: 14px 0;
      border-bottom: 1px solid var(--border-secondary);
    }
    .decision-row:last-child { border-bottom: none; }
    .decision-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: #10b981;
      flex-shrink: 0;
      margin-top: 5px;
      box-shadow: 0 0 6px rgba(16, 185, 129, 0.5);
    }
    .decision-content {
      flex: 1;
      min-width: 0;
    }
    .decision-text {
      font-size: 14px;
      font-weight: 500;
      color: var(--text-primary);
      line-height: 1.6;
    }

    /* Summary */
    .summary-content {
      padding-top: 4px;
    }
    .summary-paragraph {
      font-size: 14px;
      color: var(--text-secondary);
      line-height: 1.8;
      margin-bottom: 14px;
    }
    .summary-paragraph:last-child {
      margin-bottom: 0;
    }

    /* Follow-up Items */
    .followup-card {
      border-left: 3px solid var(--accent-red);
    }
    .followup-row {
      display: flex;
      align-items: flex-start;
      gap: 14px;
      padding: 14px 0;
      border-bottom: 1px solid var(--border-secondary);
    }
    .followup-row:last-child { border-bottom: none; }
    .followup-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      flex-shrink: 0;
      margin-top: 5px;
    }
    .dot-red {
      background: #ef4444;
      box-shadow: 0 0 6px rgba(239, 68, 68, 0.5);
    }
    .dot-yellow {
      background: #f59e0b;
      box-shadow: 0 0 6px rgba(245, 158, 11, 0.5);
    }
    .followup-content {
      flex: 1;
      min-width: 0;
    }
    .followup-text {
      font-size: 14px;
      font-weight: 500;
      color: var(--text-primary);
      line-height: 1.5;
      margin-bottom: 4px;
    }
    .followup-context {
      font-size: 13px;
      color: var(--text-muted);
      line-height: 1.5;
    }

    /* Project Updates */
    .project-row {
      display: flex;
      align-items: flex-start;
      gap: 14px;
      padding: 14px 0;
      border-bottom: 1px solid var(--border-secondary);
    }
    .project-row:last-child { border-bottom: none; }
    .project-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      flex-shrink: 0;
      margin-top: 5px;
    }
    .project-content {
      flex: 1;
      min-width: 0;
    }
    .project-name {
      font-size: 14px;
      font-weight: 600;
      color: var(--text-primary);
      margin-bottom: 2px;
    }
    .project-status {
      font-size: 13px;
      color: var(--text-secondary);
      line-height: 1.5;
    }
    .project-owner {
      font-size: 12px;
      color: var(--text-muted);
      margin-top: 4px;
    }

    /* People Notes */
    .people-row {
      display: flex;
      align-items: flex-start;
      gap: 14px;
      padding: 14px 0;
      border-bottom: 1px solid var(--border-secondary);
    }
    .people-row:last-child { border-bottom: none; }
    .people-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: #3b82f6;
      flex-shrink: 0;
      margin-top: 5px;
      box-shadow: 0 0 6px rgba(59, 130, 246, 0.5);
    }
    .people-content {
      flex: 1;
      min-width: 0;
    }
    .people-name {
      font-size: 14px;
      font-weight: 600;
      color: var(--text-primary);
      margin-bottom: 2px;
    }
    .people-observation {
      font-size: 13px;
      color: var(--text-secondary);
      line-height: 1.5;
    }
    .people-context {
      font-size: 12px;
      color: var(--text-muted);
      margin-top: 4px;
    }

    /* Completion Bar */
    .completion-bar-container {
      padding-top: 4px;
    }
    .completion-bar {
      height: 8px;
      background: var(--bg-hover);
      border-radius: 4px;
      overflow: hidden;
      margin-bottom: 10px;
    }
    .completion-fill {
      height: 100%;
      background: linear-gradient(90deg, #10b981, #3b82f6);
      border-radius: 4px;
      transition: width 0.6s ease;
    }
    .completion-label {
      font-size: 13px;
      color: var(--text-secondary);
    }

    /* Footer */
    .digest-footer {
      text-align: center;
      font-size: 12px;
      color: var(--text-muted);
      padding: 16px 0;
    }

    /* Empty & Loading States */
    .loading-text {
      color: var(--text-muted);
      text-align: center;
      padding: 60px 40px;
    }
    .error-text {
      color: var(--accent-red);
      text-align: center;
      padding: 60px 40px;
    }
    .empty-digest {
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 60px 40px;
      text-align: center;
    }
    .empty-title {
      font-size: 16px;
      font-weight: 600;
      color: var(--text-secondary);
      margin-bottom: 8px;
    }
    .empty-subtitle {
      font-size: 14px;
      color: var(--text-muted);
      max-width: 400px;
    }

    /* Spinner */
    .spinner {
      display: inline-block;
      width: 14px;
      height: 14px;
      border: 2px solid rgba(255, 255, 255, 0.3);
      border-top-color: white;
      border-radius: 50%;
      animation: spin 0.6s linear infinite;
    }
    @keyframes spin {
      to { transform: rotate(360deg); }
    }
  `],
})
export class DigestComponent implements OnInit {
  private digestService = inject(DigestService);
  private destroyRef = inject(DestroyRef);

  digest = signal<WeeklyDigestResponse | null>(null);
  loading = signal(true);
  error = signal(false);
  generating = signal(false);

  // Placeholder user ID -- in a real app this comes from an auth service
  private readonly userId = 'current-user';

  /** Formatted period label derived from the digest dates */
  periodLabel = computed(() => {
    const d = this.digest();
    if (!d) return '';
    const start = new Date(d.period_start);
    const end = new Date(d.period_end);
    const opts: Intl.DateTimeFormatOptions = { month: 'long', day: 'numeric' };
    const startStr = start.toLocaleDateString('en-US', opts);
    const endStr = end.toLocaleDateString('en-US', { ...opts, year: 'numeric' });
    return `Week of ${startStr} - ${endStr}`;
  });

  /** Estimated hours from meeting count (rough: 45 min avg per meeting) */
  estimatedHours = computed(() => {
    const d = this.digest();
    if (!d) return '0h';
    const hours = Math.round(d.total_meetings * 0.75 * 10) / 10;
    if (hours < 1) return `${Math.round(hours * 60)}m`;
    return `${hours}h`;
  });

  /** Split summary_text into paragraphs for display */
  summaryParagraphs = computed(() => {
    const d = this.digest();
    if (!d || !d.summary_text) return [];
    return d.summary_text
      .split(/\n\n|\n/)
      .map(p => p.trim())
      .filter(p => p.length > 0);
  });

  /** Derive follow-up items from the summary text */
  followUpItems = computed<FollowUpItem[]>(() => {
    const d = this.digest();
    if (!d) return [];
    const items: FollowUpItem[] = [];

    // Derive from completion rate
    const incomplete = d.total_action_items - Math.round(d.total_action_items * d.completion_rate / 100);
    if (incomplete > 0) {
      items.push({
        severity: incomplete > 3 ? 'red' : 'yellow',
        text: `${incomplete} action item${incomplete !== 1 ? 's' : ''} still open from this week`,
        context: `${d.completion_rate.toFixed(0)}% completion rate across ${d.total_action_items} total items`,
      });
    }

    // Derive from summary text keywords
    const text = d.summary_text.toLowerCase();
    if (text.includes('overdue') || text.includes('blocked')) {
      items.push({
        severity: 'red',
        text: 'Overdue or blocked items mentioned in summary',
        context: 'Review the weekly summary for details on stalled items',
      });
    }
    if (text.includes('risk') || text.includes('delayed') || text.includes('concern')) {
      items.push({
        severity: 'yellow',
        text: 'Risks or delays flagged in meeting discussions',
        context: 'Address flagged concerns before they escalate',
      });
    }

    return items;
  });

  /** Derive project updates from summary text (structured extraction) */
  projectUpdates = computed<ProjectUpdate[]>(() => {
    const d = this.digest();
    if (!d || !d.summary_text) return [];

    // Try to extract project-like sections from the summary
    const updates: ProjectUpdate[] = [];
    const lines = d.summary_text.split('\n');
    const projectColors = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ef4444', '#14b8a6'];

    for (const line of lines) {
      // Look for patterns like "Project X: status" or "- Project X ..."
      const match = line.match(/^[-*]?\s*(?:Project\s+)?([A-Z][A-Za-z0-9\s]+?):\s*(.+)/);
      if (match) {
        updates.push({
          color: projectColors[updates.length % projectColors.length],
          name: match[1].trim(),
          status: match[2].trim(),
          owner: '',
        });
      }
    }

    return updates;
  });

  /** Derive people notes from summary text */
  peopleNotes = computed<PersonNote[]>(() => {
    const d = this.digest();
    if (!d || !d.summary_text) return [];

    const notes: PersonNote[] = [];
    const lines = d.summary_text.split('\n');

    for (const line of lines) {
      // Look for patterns mentioning specific people
      const match = line.match(/(?:^[-*]\s*)?(\b[A-Z][a-z]+\s[A-Z][a-z]+)\b.*?(?:mentioned|noted|raised|suggested|committed|volunteered|proposed)\s+(.+)/i);
      if (match && notes.length < 5) {
        notes.push({
          name: match[1],
          observation: match[2].trim().replace(/[.;,]$/, ''),
          context: '',
        });
      }
    }

    return notes;
  });

  ngOnInit(): void {
    this.digestService.getLatest(this.userId).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (res) => {
        this.digest.set(res);
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
        // Not setting error -- show empty state with generate button instead
      },
    });
  }

  generateDigest(): void {
    this.generating.set(true);
    this.error.set(false);
    this.digestService.generate(this.userId).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (res) => {
        this.digest.set(res);
        this.generating.set(false);
      },
      error: () => {
        this.error.set(true);
        this.generating.set(false);
      },
    });
  }

  formatWhole(value: number): string {
    return Math.round(value).toString();
  }

  formatRelative = formatRelative;
}

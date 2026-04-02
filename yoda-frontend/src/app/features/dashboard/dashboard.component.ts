/**
 * Dashboard view -- main landing screen for the CXO.
 *
 * Displays: 4 stat cards (meetings today, open actions, overdue items, docs to review),
 * today's meetings with join buttons, attention items (overdue/due today),
 * activity feed, and quick action shortcuts to other features.
 *
 * Data sources: DashboardService, MeetingService.
 * Route: /dashboard
 */
import { Component, inject, OnInit, signal, computed, DestroyRef, ChangeDetectionStrategy } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { DashboardService } from '../../core/services/dashboard.service';
import { MeetingService } from '../../core/services/meeting.service';
import { UserService } from '../../core/services/user.service';
import { DashboardStatsResponse, MeetingResponse, AttentionItem, ActivityFeedItem } from '../../core/models';
import { formatTime, formatRelative } from '../../shared/utils/format.utils';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page-header">
      <h1>{{ greeting() }}, {{ userService.profile().displayName }}</h1>
      <p>{{ today }} &bull; You have {{ stats()?.meetings_today ?? 0 }} meetings today</p>
    </div>

    <!-- Stats Cards -->
    <div class="stats-grid">
      <div class="stat-card" routerLink="/meetings">
        <div class="stat-header-row">
          <span class="stat-icon blue">&#128197;</span>
          <span class="stat-value">{{ stats()?.meetings_today ?? '-' }}</span>
        </div>
        <div class="stat-label">Meetings Today</div>
      </div>
      <div class="stat-card" routerLink="/actions">
        <div class="stat-header-row">
          <span class="stat-icon yellow">&#9989;</span>
          <span class="stat-value">{{ stats()?.pending_actions ?? '-' }}</span>
        </div>
        <div class="stat-label">Open Actions</div>
      </div>
      <div class="stat-card">
        <div class="stat-header-row">
          <span class="stat-icon red">&#9888;&#65039;</span>
          <span class="stat-value">{{ stats()?.overdue_actions ?? '-' }}</span>
        </div>
        <div class="stat-label">Overdue Items</div>
      </div>
      <div class="stat-card" routerLink="/documents">
        <div class="stat-header-row">
          <span class="stat-icon green">&#128196;</span>
          <span class="stat-value">{{ stats()?.docs_to_review ?? '-' }}</span>
        </div>
        <div class="stat-label">Docs to Review</div>
      </div>
    </div>

    <!-- Today's Meetings -->
    <div class="card">
      <div class="card-header">
        <span class="card-title">Today's Meetings</span>
        <a routerLink="/meetings" class="view-all">View all &rarr;</a>
      </div>
      @for (m of meetings(); track m.id) {
        <div class="meeting-row" [routerLink]="['/meetings', m.id, 'brief']">
          <div class="meeting-left">
            <div class="meeting-time">{{ formatTime(m.scheduled_start) }}</div>
            <div>
              <div class="meeting-title">{{ m.subject }}</div>
              <div class="meeting-meta">{{ m.participant_count }} attendees</div>
            </div>
          </div>
          <div class="meeting-right">
            @if (m.join_status === 'join_now') {
              <a class="btn-join pulse" [href]="m.join_url" target="_blank" (click)="$event.stopPropagation()">&#128222; Join Now</a>
            } @else if (m.join_status === 'in_progress') {
              <a class="btn-join-progress" [href]="m.join_url" target="_blank" (click)="$event.stopPropagation()">&#128308; In Progress &middot; Join</a>
            } @else {
              <span class="tag tag-green">Upcoming</span>
            }
            <span class="chevron">&rsaquo;</span>
          </div>
        </div>
      }
      @if (meetings().length === 0) {
        <p class="empty-state">No meetings today</p>
      }
    </div>

    <!-- Needs Your Attention -->
    @if (attentionItems().length > 0) {
      <div class="attention-box">
        <div class="attention-title">
          <span style="color:#ef4444">&#9888;&#65039;</span>
          Needs Your Attention
        </div>
        @for (item of attentionItems(); track $index) {
          <div class="action-row">
            <div class="action-left">
              <div class="action-dot" [class]="getDotClass(item)"></div>
              <div>
                <div class="action-title">{{ item.description }}</div>
                <div class="action-meta">{{ item.type }}</div>
              </div>
            </div>
            <span class="tag" [class]="getTagClass(item)">{{ getTagLabel(item) }}</span>
          </div>
        }
      </div>
    }

    <!-- Recent Activity -->
    <div class="card" style="margin-top:16px">
      <div class="card-header">
        <span class="card-title">Recent Activity</span>
      </div>
      @for (item of activityFeed(); track $index) {
        <div class="activity-row">
          <span class="activity-icon">{{ getActivityIcon(item.type) }}</span>
          <span class="activity-text">
            <strong>{{ item.title }}</strong>
            @if (item.meeting_subject) {
              &middot; {{ item.meeting_subject }}
            }
          </span>
          <span class="activity-time">{{ formatRelative(item.timestamp) }}</span>
        </div>
      }
      @if (activityFeed().length === 0) {
        <p class="empty-state">No recent activity</p>
      }
    </div>

    <!-- Quick Actions -->
    <div class="card" style="margin-top:16px">
      <div class="card-header">
        <span class="card-title">Quick Actions</span>
      </div>
      <div class="journeys">
        <div class="journey-btn" routerLink="/meetings">
          <div class="journey-icon">&#128197;</div>
          <div class="journey-title">Pre-Meeting Brief</div>
        </div>
        <div class="journey-btn" routerLink="/chat">
          <div class="journey-icon">&#128172;</div>
          <div class="journey-title">Ask AI Anything</div>
        </div>
        <div class="journey-btn" routerLink="/meetings">
          <div class="journey-icon">&#128221;</div>
          <div class="journey-title">Meeting Summary</div>
        </div>
        <div class="journey-btn" routerLink="/actions">
          <div class="journey-icon">&#9989;</div>
          <div class="journey-title">Track Actions</div>
        </div>
        <div class="journey-btn" routerLink="/digest">
          <div class="journey-icon">&#128203;</div>
          <div class="journey-title">Weekly Digest</div>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .stat-header-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
    .stat-value { font-size: 28px; font-weight: 700; }
    .stat-icon { font-size: 24px; }
    .stat-icon.blue { color: #3b82f6; }
    .stat-icon.yellow { color: #f59e0b; }
    .stat-icon.red { color: #ef4444; }
    .stat-icon.green { color: #10b981; }
    .stat-label { font-size: 14px; color: var(--text-secondary); }
    .view-all { color: #3b82f6; font-size: 14px; cursor: pointer; text-decoration: none; }
    .view-all:hover { text-decoration: underline; }

    .meeting-row {
      display: flex; align-items: center; justify-content: space-between;
      padding: 16px; background: var(--bg-hover); border-radius: 12px;
      cursor: pointer; transition: all 0.2s; margin-bottom: 8px; text-decoration: none; color: inherit;
    }
    .meeting-row:hover { background: var(--bg-input); transform: translateX(4px); }
    .meeting-left { display: flex; align-items: center; gap: 16px; }
    .meeting-right { display: flex; align-items: center; gap: 8px; }
    .meeting-time { min-width: 70px; font-weight: 600; }
    .meeting-title { font-weight: 500; }
    .meeting-meta { font-size: 13px; color: var(--text-muted); }
    .chevron { color: var(--text-muted); font-size: 18px; }

    .attention-box {
      background: rgba(239, 68, 68, 0.05);
      border: 1px solid rgba(239, 68, 68, 0.2);
      border-radius: 16px; padding: 20px; margin-bottom: 16px;
    }
    .attention-title {
      display: flex; align-items: center; gap: 8px;
      font-weight: 600; margin-bottom: 16px; font-size: 16px;
    }
    .action-row {
      display: flex; align-items: flex-start; justify-content: space-between;
      padding: 12px 16px; background: var(--bg-hover); border-radius: 12px; margin-bottom: 8px;
    }
    .action-left { display: flex; align-items: flex-start; gap: 12px; }
    .action-dot { width: 8px; height: 8px; border-radius: 50%; margin-top: 6px; }
    .action-dot.red { background: #ef4444; }
    .action-dot.yellow { background: #f59e0b; }
    .action-title { font-weight: 500; margin-bottom: 2px; }
    .action-meta { font-size: 13px; color: var(--text-muted); }

    .activity-row {
      display: flex; align-items: center; gap: 12px;
      padding: 10px 0; border-bottom: 1px solid var(--border-secondary);
      font-size: 14px; color: var(--text-secondary);
    }
    .activity-row:last-child { border-bottom: none; }
    .activity-icon { font-size: 16px; }
    .activity-text { flex: 1; }
    .activity-text strong { color: var(--text-primary); }
    .activity-time { font-size: 12px; color: var(--text-muted); white-space: nowrap; }

    .journeys { display: flex; gap: 12px; flex-wrap: wrap; }
    .journey-btn {
      flex: 1; min-width: 140px; padding: 16px; text-align: center;
      background: var(--bg-hover); border-radius: 12px; cursor: pointer;
      transition: all 0.2s; text-decoration: none; color: inherit;
    }
    .journey-btn:hover { background: var(--bg-input); transform: translateY(-2px); }
    .journey-icon { font-size: 28px; margin-bottom: 8px; }
    .journey-title { font-size: 13px; font-weight: 500; }

    .empty-state { color: var(--text-muted); text-align: center; padding: 20px; }
  `],
})
export class DashboardComponent implements OnInit {
  private dashboardService = inject(DashboardService);
  private meetingService = inject(MeetingService);
  private destroyRef = inject(DestroyRef);
  userService = inject(UserService);

  greeting = computed(() => {
    const hour = new Date().getHours();
    if (hour < 12) return 'Good morning';
    if (hour < 18) return 'Good afternoon';
    return 'Good evening';
  });

  stats = signal<DashboardStatsResponse | null>(null);
  meetings = signal<MeetingResponse[]>([]);
  attentionItems = signal<AttentionItem[]>([]);
  activityFeed = signal<ActivityFeedItem[]>([]);
  today = new Date().toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });

  ngOnInit() {
    this.dashboardService.getStats().pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (s) => this.stats.set(s),
      error: () => {},
    });
    this.meetingService.list({ limit: 10 }).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (res) => this.meetings.set(res.items),
      error: () => {},
    });
    this.dashboardService.getAttentionItems().pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (res) => this.attentionItems.set(res.items),
      error: () => {},
    });
    this.dashboardService.getActivityFeed().pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (res) => this.activityFeed.set(res.feed),
      error: () => {},
    });
  }

  formatTime = formatTime;
  formatRelative = formatRelative;

  getDotClass(item: AttentionItem): string {
    return item.type.includes('overdue') ? 'red' : 'yellow';
  }

  getTagClass(item: AttentionItem): string {
    if (item.type.includes('overdue')) return 'tag-red';
    if (item.type.includes('today')) return 'tag-red';
    return 'tag-yellow';
  }

  getTagLabel(item: AttentionItem): string {
    if (item.type.includes('overdue')) return 'OVERDUE';
    if (item.type.includes('today')) return 'DUE TODAY';
    return 'Decision Pending';
  }

  getActivityIcon(type: string): string {
    const icons: Record<string, string> = {
      meeting_completed: '\u{1F4C4}',
      summary_delivered: '\u{1F4C5}',
      action_created: '\u2705',
      action_completed: '\u2705',
      nudge_sent: '\u{1F514}',
      digest_delivered: '\u{1F4CB}',
    };
    return icons[type] ?? '\u{1F4AC}';
  }
}

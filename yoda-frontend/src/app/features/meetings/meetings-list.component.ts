/**
 * Meetings list view -- displays all meetings grouped by day.
 *
 * Features: filter tabs (Today / This Week / This Month), meetings grouped
 * by date with time, duration, attendee count, and status tags.
 * Join buttons appear for meetings that are starting or in progress.
 * Clicking a meeting card navigates to /meetings/:id/brief.
 *
 * Uses computed signals for client-side filtering and grouping.
 * Data source: MeetingService.
 * Route: /meetings
 */
import { Component, inject, OnInit, signal, computed, DestroyRef, ChangeDetectionStrategy } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { switchMap } from 'rxjs/operators';
import { MeetingService } from '../../core/services/meeting.service';
import { MeetingResponse } from '../../core/models';
import { formatTime, computeDuration } from '../../shared/utils/format.utils';

type FilterTab = 'today' | 'week' | 'month';

interface MeetingGroup {
  label: string;
  date: string;
  meetings: MeetingResponse[];
}

@Component({
  selector: 'app-meetings-list',
  standalone: true,
  imports: [RouterLink, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page-header">
      <div class="page-header-row">
        <div>
          <h1>Meetings</h1>
          <p>This week: {{ weekMeetingCount() }} meetings &bull; {{ weekTotalHours() }} hours</p>
        </div>
        <form class="join-bar" (ngSubmit)="joinMeeting()">
          <input
            type="url"
            placeholder="Paste Teams meeting link..."
            [(ngModel)]="joinUrl"
            name="joinUrl"
            class="join-input" />
          <button type="submit" class="btn-join-now" [disabled]="creating() || !joinUrl">
            @if (creating()) {
              Joining...
            } @else {
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"/></svg>
              Join Now
            }
          </button>
        </form>
      </div>
      @if (createError()) {
        <div class="join-error">{{ createError() }}</div>
      }
    </div>

    <!-- Filter Tabs -->
    <div class="filter-tabs" role="tablist">
      <button
        class="filter-btn"
        role="tab"
        [attr.aria-selected]="activeFilter() === 'today'"
        [class.active]="activeFilter() === 'today'"
        (click)="setFilter('today')">
        Today
      </button>
      <button
        class="filter-btn"
        role="tab"
        [attr.aria-selected]="activeFilter() === 'week'"
        [class.active]="activeFilter() === 'week'"
        (click)="setFilter('week')">
        This Week
      </button>
      <button
        class="filter-btn"
        role="tab"
        [attr.aria-selected]="activeFilter() === 'month'"
        [class.active]="activeFilter() === 'month'"
        (click)="setFilter('month')">
        This Month
      </button>
    </div>

    <!-- Loading state -->
    @if (loading()) {
      <div class="card">
        <p style="color:var(--text-muted);text-align:center;padding:40px">Loading meetings...</p>
      </div>
    }

    <!-- Meeting Groups -->
    @if (!loading()) {
      @for (group of groupedMeetings(); track group.date) {
        <div class="day-group">
          <div class="day-label">
            <span class="day-label-text">{{ group.label }}</span>
            <span class="day-label-count">{{ group.meetings.length }} meeting{{ group.meetings.length !== 1 ? 's' : '' }}</span>
          </div>

          @for (m of group.meetings; track m.id) {
            <div class="meeting-card card" [routerLink]="['/meetings', m.id, 'brief']">
              <div class="meeting-card-content">
                <div class="meeting-time-block">
                  <div class="meeting-time">{{ formatTime(m.scheduled_start) }}</div>
                  <div class="meeting-duration">{{ computeDuration(m.scheduled_start, m.scheduled_end) }}</div>
                </div>

                <div class="meeting-divider"></div>

                <div class="meeting-info">
                  <div class="meeting-subject">{{ m.subject }}</div>
                  <div class="meeting-meta">
                    <span class="meeting-attendees">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
                      {{ m.participant_count }} attendee{{ m.participant_count !== 1 ? 's' : '' }}
                    </span>
                    <span class="meeting-time-range">
                      {{ formatTime(m.scheduled_start) }} &ndash; {{ formatTime(m.scheduled_end) }}
                    </span>
                  </div>
                  <div class="meeting-tags">
                    @if (m.status === 'completed') {
                      <span class="tag tag-green">Completed</span>
                    }
                    @if (m.status === 'in_progress') {
                      <span class="tag tag-blue">In Progress</span>
                    }
                    @if (m.status === 'scheduled') {
                      <span class="tag tag-purple">Scheduled</span>
                    }
                    @if (m.status === 'cancelled') {
                      <span class="tag tag-red">Cancelled</span>
                    }
                    @if (m.status === 'failed') {
                      <span class="tag tag-red">Failed</span>
                    }
                    @if (m.recording_url) {
                      <span class="tag tag-blue">Recorded</span>
                    }
                  </div>
                </div>

                <div class="meeting-action">
                  @if (m.join_status === 'join_now') {
                    <a class="btn-join pulse" [href]="m.join_url" target="_blank"
                       (click)="$event.stopPropagation()">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"/></svg>
                      Join Now
                    </a>
                  }
                  @if (m.join_status === 'in_progress') {
                    <a class="btn-join-progress" [href]="m.join_url" target="_blank"
                       (click)="$event.stopPropagation()">
                      <span class="live-dot"></span>
                      In Progress &middot; Join
                    </a>
                  }
                  @if (m.join_status === 'upcoming' && isWithinOneHour(m.scheduled_start)) {
                    <span class="btn-join-soon">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                      Starts in {{ minutesUntil(m.scheduled_start) }}m
                    </span>
                  }
                </div>
              </div>
            </div>
          }
        </div>
      }

      @if (groupedMeetings().length === 0 && !loading()) {
        <div class="card">
          <div style="text-align:center;padding:60px 20px">
            <div style="font-size:48px;margin-bottom:16px;opacity:0.3">&#128197;</div>
            <div style="font-size:16px;color:var(--text-secondary);margin-bottom:4px">No meetings found</div>
            <div style="font-size:14px;color:var(--text-muted)">
              @if (activeFilter() === 'today') {
                You have no meetings scheduled for today.
              } @else if (activeFilter() === 'week') {
                You have no meetings scheduled this week.
              } @else {
                You have no meetings scheduled this month.
              }
            </div>
          </div>
        </div>
      }
    }
  `,
  styles: [`
    .filter-tabs {
      display: flex;
      gap: 8px;
      margin-bottom: 24px;
    }
    .filter-btn {
      padding: 8px 20px;
      border-radius: 10px;
      font-size: 14px;
      font-weight: 500;
      cursor: pointer;
      border: 1px solid var(--border-secondary);
      background: var(--bg-card);
      color: var(--text-secondary);
      transition: all 0.2s;
    }
    .filter-btn:hover {
      background: var(--bg-hover);
      color: var(--text-primary);
    }
    .filter-btn.active {
      background: #3b82f6;
      color: white;
      border-color: #3b82f6;
    }

    .day-group {
      margin-bottom: 28px;
    }
    .day-label {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 12px;
      padding: 0 4px;
    }
    .day-label-text {
      font-size: 15px;
      font-weight: 600;
      color: var(--text-primary);
    }
    .day-label-count {
      font-size: 13px;
      color: var(--text-muted);
    }

    .meeting-card {
      cursor: pointer;
      transition: all 0.2s;
      padding: 16px 20px;
      margin-bottom: 10px;
    }
    .meeting-card:hover {
      border-color: rgba(59, 130, 246, 0.4);
      transform: translateX(4px);
    }

    .meeting-card-content {
      display: flex;
      align-items: center;
      gap: 16px;
    }

    .meeting-time-block {
      min-width: 80px;
      text-align: center;
      flex-shrink: 0;
    }
    .meeting-time {
      font-size: 15px;
      font-weight: 600;
      color: var(--text-primary);
    }
    .meeting-duration {
      font-size: 12px;
      color: var(--text-muted);
      margin-top: 2px;
    }

    .meeting-divider {
      width: 1px;
      height: 40px;
      background: var(--border-secondary);
      flex-shrink: 0;
    }

    .meeting-info {
      flex: 1;
      min-width: 0;
    }
    .meeting-subject {
      font-size: 15px;
      font-weight: 500;
      color: var(--text-primary);
      margin-bottom: 4px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .meeting-meta {
      display: flex;
      align-items: center;
      gap: 16px;
      font-size: 13px;
      color: var(--text-muted);
      margin-bottom: 6px;
    }
    .meeting-attendees, .meeting-time-range {
      display: inline-flex;
      align-items: center;
      gap: 5px;
    }
    .meeting-tags {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }

    .meeting-action {
      flex-shrink: 0;
      display: flex;
      align-items: center;
    }

    .btn-join-progress {
      background: rgba(59, 130, 246, 0.15);
      color: #3b82f6;
      padding: 6px 14px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 600;
      border: 1px solid rgba(59, 130, 246, 0.3);
      display: inline-flex;
      align-items: center;
      gap: 6px;
      cursor: pointer;
      text-decoration: none;
      white-space: nowrap;
      transition: all 0.2s;
    }
    .btn-join-progress:hover {
      background: rgba(59, 130, 246, 0.25);
    }

    .live-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #3b82f6;
      animation: livePulse 1.5s ease-in-out infinite;
    }
    @keyframes livePulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.4; }
    }

    /* Page header with join bar */
    .page-header-row {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 24px;
    }
    .join-bar {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-shrink: 0;
    }
    .join-input {
      width: 320px;
      padding: 10px 14px;
      border-radius: 10px;
      border: 1px solid var(--border-secondary);
      background: var(--bg-primary);
      color: var(--text-primary);
      font-size: 14px;
      transition: border-color 0.2s;
    }
    .join-input:focus {
      outline: none;
      border-color: #3b82f6;
      box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
    }
    .join-input::placeholder {
      color: var(--text-muted);
    }
    .btn-join-now {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 10px 20px;
      border-radius: 10px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      border: none;
      background: #3b82f6;
      color: white;
      transition: all 0.2s;
      white-space: nowrap;
    }
    .btn-join-now:hover:not(:disabled) {
      background: #2563eb;
      transform: translateY(-1px);
    }
    .btn-join-now:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    .join-error {
      background: rgba(239, 68, 68, 0.1);
      border: 1px solid rgba(239, 68, 68, 0.3);
      color: #ef4444;
      padding: 10px 14px;
      border-radius: 8px;
      font-size: 13px;
      margin-top: 8px;
    }
  `],
})
export class MeetingsListComponent implements OnInit {
  private meetingService = inject(MeetingService);
  private destroyRef = inject(DestroyRef);

  allMeetings = signal<MeetingResponse[]>([]);
  loading = signal(true);
  activeFilter = signal<FilterTab>('week');

  // Join bar state
  joinUrl = '';
  creating = signal(false);
  createError = signal<string | null>(null);

  /** Meetings filtered by the active tab */
  filteredMeetings = computed(() => {
    const meetings = this.allMeetings();
    const now = new Date();
    const todayStart = this.startOfDay(now);
    const todayEnd = this.endOfDay(now);

    switch (this.activeFilter()) {
      case 'today':
        return meetings.filter(m => {
          const start = new Date(m.scheduled_start);
          return start >= todayStart && start <= todayEnd;
        });
      case 'week':
        return meetings.filter(m => {
          const start = new Date(m.scheduled_start);
          return start >= this.startOfWeek(now) && start <= this.endOfWeek(now);
        });
      case 'month':
        return meetings.filter(m => {
          const start = new Date(m.scheduled_start);
          return start >= this.startOfMonth(now) && start <= this.endOfMonth(now);
        });
    }
  });

  /** Meetings grouped by day with readable labels */
  groupedMeetings = computed<MeetingGroup[]>(() => {
    const meetings = this.filteredMeetings();
    const groups = new Map<string, MeetingResponse[]>();

    for (const m of meetings) {
      const dateKey = new Date(m.scheduled_start).toISOString().slice(0, 10);
      if (!groups.has(dateKey)) {
        groups.set(dateKey, []);
      }
      groups.get(dateKey)!.push(m);
    }

    // Sort each group by time
    for (const list of groups.values()) {
      list.sort((a, b) => new Date(a.scheduled_start).getTime() - new Date(b.scheduled_start).getTime());
    }

    // Sort groups by date
    const sortedKeys = Array.from(groups.keys()).sort();
    return sortedKeys.map(dateKey => ({
      label: this.formatDayLabel(dateKey),
      date: dateKey,
      meetings: groups.get(dateKey)!,
    }));
  });

  /** Total meetings this week (always computed from full list) */
  weekMeetingCount = computed(() => {
    const now = new Date();
    const weekStart = this.startOfWeek(now);
    const weekEnd = this.endOfWeek(now);
    return this.allMeetings().filter(m => {
      const start = new Date(m.scheduled_start);
      return start >= weekStart && start <= weekEnd;
    }).length;
  });

  /** Total hours of meetings this week */
  weekTotalHours = computed(() => {
    const now = new Date();
    const weekStart = this.startOfWeek(now);
    const weekEnd = this.endOfWeek(now);
    const totalMs = this.allMeetings()
      .filter(m => {
        const start = new Date(m.scheduled_start);
        return start >= weekStart && start <= weekEnd;
      })
      .reduce((sum, m) => {
        const start = new Date(m.scheduled_start).getTime();
        const end = new Date(m.scheduled_end).getTime();
        return sum + (end - start);
      }, 0);
    const hours = totalMs / (1000 * 60 * 60);
    return hours % 1 === 0 ? hours.toString() : hours.toFixed(1);
  });

  ngOnInit(): void {
    this.meetingService.list({ limit: 100 }).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (res) => {
        this.allMeetings.set(res.items);
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
      },
    });
  }

  joinMeeting(): void {
    if (!this.joinUrl || this.creating()) return;

    this.creating.set(true);
    this.createError.set(null);

    this.meetingService.create({ join_url: this.joinUrl } as any).pipe(
      switchMap(meeting => {
        this.allMeetings.update(list => [meeting, ...list]);
        return this.meetingService.join(meeting.id);
      }),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: () => {
        this.creating.set(false);
        this.joinUrl = '';
      },
      error: (err) => {
        this.creating.set(false);
        this.createError.set(err?.error?.detail || err?.message || 'Failed to join meeting');
      },
    });
  }

  setFilter(tab: FilterTab): void {
    this.activeFilter.set(tab);
  }

  formatTime = formatTime;
  computeDuration = computeDuration;

  isWithinOneHour(iso: string): boolean {
    const start = new Date(iso).getTime();
    const now = Date.now();
    return start > now && (start - now) <= 3600000;
  }

  minutesUntil(iso: string): number {
    const diff = new Date(iso).getTime() - Date.now();
    return Math.max(1, Math.ceil(diff / 60000));
  }

  // --- Date helpers ---

  private formatDayLabel(dateKey: string): string {
    const date = new Date(dateKey + 'T12:00:00');
    const now = new Date();
    const todayKey = now.toISOString().slice(0, 10);

    const tomorrow = new Date(now);
    tomorrow.setDate(now.getDate() + 1);
    const tomorrowKey = tomorrow.toISOString().slice(0, 10);

    const yesterday = new Date(now);
    yesterday.setDate(now.getDate() - 1);
    const yesterdayKey = yesterday.toISOString().slice(0, 10);

    if (dateKey === todayKey) return 'Today';
    if (dateKey === tomorrowKey) return 'Tomorrow';
    if (dateKey === yesterdayKey) return 'Yesterday';

    return date.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });
  }

  private startOfDay(d: Date): Date {
    const s = new Date(d);
    s.setHours(0, 0, 0, 0);
    return s;
  }

  private endOfDay(d: Date): Date {
    const e = new Date(d);
    e.setHours(23, 59, 59, 999);
    return e;
  }

  private startOfWeek(d: Date): Date {
    const s = new Date(d);
    const day = s.getDay();
    const diff = day === 0 ? 6 : day - 1; // Monday start
    s.setDate(s.getDate() - diff);
    s.setHours(0, 0, 0, 0);
    return s;
  }

  private endOfWeek(d: Date): Date {
    const start = this.startOfWeek(d);
    const end = new Date(start);
    end.setDate(start.getDate() + 6);
    end.setHours(23, 59, 59, 999);
    return end;
  }

  private startOfMonth(d: Date): Date {
    return new Date(d.getFullYear(), d.getMonth(), 1, 0, 0, 0, 0);
  }

  private endOfMonth(d: Date): Date {
    return new Date(d.getFullYear(), d.getMonth() + 1, 0, 23, 59, 59, 999);
  }
}

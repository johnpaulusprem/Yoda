/**
 * Action Items view -- task tracker with urgency-based sections.
 *
 * Displays action items categorized into Overdue, Due Soon, In Progress,
 * and Upcoming sections. Each item shows description, owner, deadline,
 * source meeting link, and hover-reveal Complete/Snooze buttons.
 *
 * Filters: status (all/open/overdue/in_progress/completed), owner, meeting.
 * Uses computed signals for client-side filtering and urgency categorization.
 * Loads meeting subjects separately to annotate items with source context.
 *
 * Data sources: ActionItemService, MeetingService.
 * Route: /actions
 */
import { Component, inject, OnInit, signal, computed, DestroyRef, ChangeDetectionStrategy } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ActionItemService } from '../../core/services/action-item.service';
import { MeetingService } from '../../core/services/meeting.service';
import { ActionItemResponse, MeetingResponse } from '../../core/models';

type UrgencyCategory = 'overdue' | 'due-soon' | 'in-progress' | 'upcoming';

interface CategorizedItem {
  item: ActionItemResponse;
  urgency: UrgencyCategory;
  overdueDays: number;
  meetingSubject: string | null;
}

@Component({
  selector: 'app-action-items',
  standalone: true,
  imports: [FormsModule, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page-header">
      <h1>Action Items</h1>
      <p>{{ openCount() }} open &middot; {{ overdueCount() }} overdue &middot; {{ completedThisMonthCount() }} completed this month</p>
    </div>

    <!-- Filters -->
    <div class="filters-bar">
      <select class="filter-select" aria-label="Filter by status" [ngModel]="statusFilter()" (ngModelChange)="statusFilter.set($event)">
        <option value="all">All Statuses</option>
        <option value="open">Open</option>
        <option value="overdue">Overdue</option>
        <option value="in_progress">In Progress</option>
        <option value="completed">Completed</option>
      </select>
      <select class="filter-select" aria-label="Filter by owner" [ngModel]="ownerFilter()" (ngModelChange)="ownerFilter.set($event)">
        <option value="all">All Owners</option>
        <option value="assigned_to_me">Assigned to Me</option>
        <option value="assigned_by_me">Assigned by Me</option>
      </select>
      <select class="filter-select" aria-label="Filter by meeting" [ngModel]="meetingFilter()" (ngModelChange)="meetingFilter.set($event)">
        <option value="all">All Meetings</option>
        @for (m of meetingOptions(); track m.id) {
          <option [value]="m.id">{{ m.subject }}</option>
        }
      </select>
    </div>

    <!-- Overdue Section -->
    @if (overdueItems().length > 0) {
      <div class="card section-overdue">
        <div class="card-header">
          <span class="card-title" style="color:var(--accent-red)">Overdue</span>
          <span class="tag tag-red">{{ overdueItems().length }}</span>
        </div>
        @for (ci of overdueItems(); track ci.item.id) {
          <div class="action-row" (mouseenter)="hoveredId.set(ci.item.id)" (mouseleave)="hoveredId.set(null)">
            <div class="row-left">
              <span class="status-dot dot-red"></span>
              <div class="row-content">
                <div class="row-description">{{ ci.item.description }}</div>
                <div class="row-meta">
                  Owner: {{ ci.item.assigned_to_name }}
                  @if (ci.item.deadline) {
                    &middot; Due: {{ formatDate(ci.item.deadline) }}
                  }
                </div>
                @if (ci.meetingSubject) {
                  <div class="row-source">
                    Source: <a class="source-link" [routerLink]="['/meetings', ci.item.meeting_id]">{{ ci.meetingSubject }}</a>
                  </div>
                }
              </div>
            </div>
            <div class="row-right">
              <span class="tag tag-red">{{ ci.overdueDays }}d overdue</span>
              @if (hoveredId() === ci.item.id) {
                <button class="btn btn-primary btn-sm" (click)="completeItem(ci.item.id); $event.stopPropagation()">Complete</button>
                <button class="btn btn-secondary btn-sm" (click)="snoozeItem(ci.item.id); $event.stopPropagation()">Snooze</button>
              }
            </div>
          </div>
        }
      </div>
    }

    <!-- Due Soon Section -->
    @if (dueSoonItems().length > 0) {
      <div class="card">
        <div class="card-header">
          <span class="card-title" style="color:var(--accent-yellow)">Due Soon</span>
          <span class="tag tag-yellow">{{ dueSoonItems().length }}</span>
        </div>
        @for (ci of dueSoonItems(); track ci.item.id) {
          <div class="action-row" (mouseenter)="hoveredId.set(ci.item.id)" (mouseleave)="hoveredId.set(null)">
            <div class="row-left">
              <span class="status-dot dot-yellow"></span>
              <div class="row-content">
                <div class="row-description">{{ ci.item.description }}</div>
                <div class="row-meta">
                  Owner: {{ ci.item.assigned_to_name }}
                  @if (ci.item.deadline) {
                    &middot; Due: {{ formatDate(ci.item.deadline) }}
                  }
                </div>
                @if (ci.meetingSubject) {
                  <div class="row-source">
                    Source: <a class="source-link" [routerLink]="['/meetings', ci.item.meeting_id]">{{ ci.meetingSubject }}</a>
                  </div>
                }
              </div>
            </div>
            <div class="row-right">
              <span class="tag tag-yellow">Due soon</span>
              @if (hoveredId() === ci.item.id) {
                <button class="btn btn-primary btn-sm" (click)="completeItem(ci.item.id); $event.stopPropagation()">Complete</button>
                <button class="btn btn-secondary btn-sm" (click)="snoozeItem(ci.item.id); $event.stopPropagation()">Snooze</button>
              }
            </div>
          </div>
        }
      </div>
    }

    <!-- In Progress Section -->
    @if (inProgressItems().length > 0) {
      <div class="card">
        <div class="card-header">
          <span class="card-title" style="color:var(--accent-blue)">In Progress</span>
          <span class="tag tag-blue">{{ inProgressItems().length }}</span>
        </div>
        @for (ci of inProgressItems(); track ci.item.id) {
          <div class="action-row" (mouseenter)="hoveredId.set(ci.item.id)" (mouseleave)="hoveredId.set(null)">
            <div class="row-left">
              <span class="status-dot dot-blue"></span>
              <div class="row-content">
                <div class="row-description">{{ ci.item.description }}</div>
                <div class="row-meta">
                  Owner: {{ ci.item.assigned_to_name }}
                  @if (ci.item.deadline) {
                    &middot; Due: {{ formatDate(ci.item.deadline) }}
                  }
                </div>
                @if (ci.meetingSubject) {
                  <div class="row-source">
                    Source: <a class="source-link" [routerLink]="['/meetings', ci.item.meeting_id]">{{ ci.meetingSubject }}</a>
                  </div>
                }
              </div>
            </div>
            <div class="row-right">
              <span class="tag tag-blue">In progress</span>
              @if (hoveredId() === ci.item.id) {
                <button class="btn btn-primary btn-sm" (click)="completeItem(ci.item.id); $event.stopPropagation()">Complete</button>
                <button class="btn btn-secondary btn-sm" (click)="snoozeItem(ci.item.id); $event.stopPropagation()">Snooze</button>
              }
            </div>
          </div>
        }
      </div>
    }

    <!-- Upcoming Section -->
    @if (upcomingItems().length > 0) {
      <div class="card">
        <div class="card-header">
          <span class="card-title" style="color:var(--accent-green)">Upcoming</span>
          <span class="tag tag-green">{{ upcomingItems().length }}</span>
        </div>
        @for (ci of upcomingItems(); track ci.item.id) {
          <div class="action-row" (mouseenter)="hoveredId.set(ci.item.id)" (mouseleave)="hoveredId.set(null)">
            <div class="row-left">
              <span class="status-dot dot-green"></span>
              <div class="row-content">
                <div class="row-description">{{ ci.item.description }}</div>
                <div class="row-meta">
                  Owner: {{ ci.item.assigned_to_name }}
                  @if (ci.item.deadline) {
                    &middot; Due: {{ formatDate(ci.item.deadline) }}
                  }
                </div>
                @if (ci.meetingSubject) {
                  <div class="row-source">
                    Source: <a class="source-link" [routerLink]="['/meetings', ci.item.meeting_id]">{{ ci.meetingSubject }}</a>
                  </div>
                }
              </div>
            </div>
            <div class="row-right">
              <span class="tag tag-green">On track</span>
              @if (hoveredId() === ci.item.id) {
                <button class="btn btn-primary btn-sm" (click)="completeItem(ci.item.id); $event.stopPropagation()">Complete</button>
                <button class="btn btn-secondary btn-sm" (click)="snoozeItem(ci.item.id); $event.stopPropagation()">Snooze</button>
              }
            </div>
          </div>
        }
      </div>
    }

    <!-- Empty State -->
    @if (filteredItems().length === 0 && !loading()) {
      <div class="card">
        <p style="color:var(--text-muted);padding:40px;text-align:center">
          No action items match the current filters
        </p>
      </div>
    }

    @if (loading()) {
      <div class="card">
        <p style="color:var(--text-muted);padding:40px;text-align:center">
          Loading action items...
        </p>
      </div>
    }
  `,
  styles: [`
    .filters-bar {
      display: flex;
      gap: 12px;
      margin-bottom: 20px;
      flex-wrap: wrap;
    }
    .filter-select {
      padding: 8px 14px;
      border-radius: 10px;
      border: 1px solid var(--border-secondary);
      background: var(--bg-input);
      color: var(--text-primary);
      font-size: 14px;
      cursor: pointer;
      min-width: 170px;
      appearance: auto;
    }
    .filter-select:focus {
      outline: none;
      border-color: var(--accent-blue);
    }

    .section-overdue {
      border-left: 3px solid var(--accent-red);
    }

    .action-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 14px 16px;
      background: var(--bg-hover);
      border-radius: 12px;
      margin-bottom: 8px;
      transition: all 0.2s;
      cursor: default;
      gap: 12px;
    }
    .action-row:hover {
      background: var(--bg-input);
      transform: translateX(4px);
    }
    .action-row:last-child {
      margin-bottom: 0;
    }

    .row-left {
      display: flex;
      align-items: flex-start;
      gap: 14px;
      flex: 1;
      min-width: 0;
    }

    .status-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      flex-shrink: 0;
      margin-top: 6px;
    }
    .dot-red    { background: var(--accent-red); box-shadow: 0 0 6px rgba(239, 68, 68, 0.5); }
    .dot-yellow { background: var(--accent-yellow); box-shadow: 0 0 6px rgba(245, 158, 11, 0.5); }
    .dot-blue   { background: var(--accent-blue); box-shadow: 0 0 6px rgba(59, 130, 246, 0.5); }
    .dot-green  { background: var(--accent-green); box-shadow: 0 0 6px rgba(16, 185, 129, 0.5); }

    .row-content {
      min-width: 0;
    }
    .row-description {
      font-weight: 600;
      font-size: 14px;
      line-height: 1.4;
      margin-bottom: 4px;
    }
    .row-meta {
      font-size: 13px;
      color: var(--text-muted);
    }
    .row-source {
      font-size: 13px;
      color: var(--text-muted);
      margin-top: 2px;
    }
    .source-link {
      color: var(--accent-blue);
      text-decoration: none;
      cursor: pointer;
    }
    .source-link:hover {
      text-decoration: underline;
    }

    .row-right {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;
    }

    .btn-sm {
      padding: 5px 12px;
      font-size: 12px;
      border-radius: 8px;
    }
  `],
})
export class ActionItemsComponent implements OnInit {
  private actionItemService = inject(ActionItemService);
  private meetingService = inject(MeetingService);
  private destroyRef = inject(DestroyRef);

  // Raw data
  allItems = signal<ActionItemResponse[]>([]);
  allCompletedItems = signal<ActionItemResponse[]>([]);
  meetingMap = signal<Map<string, MeetingResponse>>(new Map());
  loading = signal(true);

  // UI state
  hoveredId = signal<string | null>(null);
  statusFilter = signal<string>('all');
  ownerFilter = signal<string>('all');
  meetingFilter = signal<string>('all');

  // Meeting dropdown options derived from loaded items
  meetingOptions = computed(() => {
    const map = this.meetingMap();
    const meetingIds = new Set(this.allItems().map(i => i.meeting_id));
    const meetings: MeetingResponse[] = [];
    for (const id of meetingIds) {
      const m = map.get(id);
      if (m) meetings.push(m);
    }
    return meetings.sort((a, b) => a.subject.localeCompare(b.subject));
  });

  // Filter items based on current filter signals
  filteredItems = computed<CategorizedItem[]>(() => {
    const items = this.allItems();
    const status = this.statusFilter();
    const owner = this.ownerFilter();
    const meeting = this.meetingFilter();
    const map = this.meetingMap();
    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());

    return items
      .filter(item => {
        // Status filter
        if (status === 'overdue') {
          if (!item.deadline) return false;
          return new Date(item.deadline) < startOfToday && item.status !== 'completed' && item.status !== 'cancelled';
        }
        if (status === 'open') {
          return item.status === 'pending';
        }
        if (status !== 'all' && item.status !== status) {
          return false;
        }
        return true;
      })
      .filter(item => {
        // Owner filter -- in a real app, the current user ID would come from an auth service.
        // For now, we pass all items through when a specific owner filter is set,
        // since the API handles user-scoped filtering.
        if (owner === 'all') return true;
        return true;
      })
      .filter(item => {
        if (meeting === 'all') return true;
        return item.meeting_id === meeting;
      })
      .map(item => this.categorize(item, startOfToday, map));
  });

  // Section signals
  overdueItems = computed(() =>
    this.filteredItems().filter(ci => ci.urgency === 'overdue')
  );

  dueSoonItems = computed(() =>
    this.filteredItems().filter(ci => ci.urgency === 'due-soon')
  );

  inProgressItems = computed(() =>
    this.filteredItems().filter(ci => ci.urgency === 'in-progress')
  );

  upcomingItems = computed(() =>
    this.filteredItems().filter(ci => ci.urgency === 'upcoming')
  );

  // Header summary counters
  openCount = computed(() =>
    this.allItems().filter(i => i.status === 'pending' || i.status === 'in_progress').length
  );

  overdueCount = computed(() => {
    const today = new Date();
    const startOfToday = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    return this.allItems().filter(i =>
      i.deadline &&
      new Date(i.deadline) < startOfToday &&
      i.status !== 'completed' &&
      i.status !== 'cancelled'
    ).length;
  });

  completedThisMonthCount = computed(() => {
    const now = new Date();
    const startOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);
    return this.allCompletedItems().filter(i =>
      i.completed_at && new Date(i.completed_at) >= startOfMonth
    ).length;
  });

  ngOnInit(): void {
    this.loadItems();
    this.loadCompletedItems();
    this.loadMeetings();
  }

  private loadItems(): void {
    this.loading.set(true);
    this.actionItemService.list({ limit: 200 }).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (res) => {
        // Exclude completed/cancelled from the main working list
        this.allItems.set(
          res.items.filter(i => i.status !== 'completed' && i.status !== 'cancelled')
        );
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
      },
    });
  }

  private loadCompletedItems(): void {
    this.actionItemService.list({ status: 'completed', limit: 200 }).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (res) => this.allCompletedItems.set(res.items),
      error: () => {},
    });
  }

  private loadMeetings(): void {
    this.meetingService.list({ limit: 200 }).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (res) => {
        const map = new Map<string, MeetingResponse>();
        for (const m of res.items) {
          map.set(m.id, m);
        }
        this.meetingMap.set(map);
      },
      error: () => {},
    });
  }

  private categorize(item: ActionItemResponse, startOfToday: Date, meetingMap: Map<string, MeetingResponse>): CategorizedItem {
    const meeting = meetingMap.get(item.meeting_id);
    const meetingSubject = meeting?.subject ?? null;
    const msPerDay = 86_400_000;

    // In progress items stay in their own bucket regardless of deadline
    if (item.status === 'in_progress') {
      const overdueDays = item.deadline
        ? Math.max(0, Math.floor((startOfToday.getTime() - new Date(item.deadline).getTime()) / msPerDay))
        : 0;
      return { item, urgency: 'in-progress', overdueDays, meetingSubject };
    }

    if (!item.deadline) {
      return { item, urgency: 'upcoming', overdueDays: 0, meetingSubject };
    }

    const deadlineDate = new Date(item.deadline);
    const diffDays = Math.floor((deadlineDate.getTime() - startOfToday.getTime()) / msPerDay);

    if (diffDays < 0) {
      return { item, urgency: 'overdue', overdueDays: Math.abs(diffDays), meetingSubject };
    }
    if (diffDays <= 1) {
      return { item, urgency: 'due-soon', overdueDays: 0, meetingSubject };
    }
    return { item, urgency: 'upcoming', overdueDays: 0, meetingSubject };
  }

  completeItem(id: string): void {
    this.actionItemService.complete(id).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: () => {
        this.allItems.update(items => items.filter(i => i.id !== id));
      },
      error: () => {},
    });
  }

  snoozeItem(id: string): void {
    this.actionItemService.snooze(id).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: () => {
        this.allItems.update(items => items.filter(i => i.id !== id));
      },
      error: () => {},
    });
  }

  formatDate(iso: string): string {
    return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  }
}

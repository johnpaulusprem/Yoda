/**
 * Top bar component -- 64px header with global search, notifications, and user avatar.
 *
 * Features:
 * - Search: live cross-entity search (meetings, documents, action items) via SearchService,
 *   with a dropdown results panel and keyboard navigation (Enter to search).
 * - Notifications: bell icon with unread badge, dropdown list with mark-read and mark-all-read.
 * - M365 status indicator and user avatar with initials from UserService.
 *
 * Data sources: SearchService, NotificationService, UserService.
 */
import { Component, inject, signal, OnInit, DestroyRef, ChangeDetectionStrategy } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { MsalService } from '@azure/msal-angular';
import { environment } from '../../../environments/environment';
import { NotificationService } from '../../core/services/notification.service';
import { SearchService } from '../../core/services/search.service';
import { UserService } from '../../core/services/user.service';
import { NotificationResponse, SearchResult } from '../../core/models';
import { formatRelative } from '../../shared/utils/format.utils';

@Component({
  selector: 'app-topbar',
  standalone: true,
  imports: [FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="topbar">
      <!-- Search -->
      <div class="search-wrapper">
        <div class="search-box">
          <span class="search-icon">&#128269;</span>
          <input
            type="text"
            [(ngModel)]="searchQuery"
            placeholder="Search meetings, documents, people..."
            (keyup.enter)="onSearch()"
            (focus)="searchFocused.set(true)"
            (blur)="onSearchBlur()"
            role="combobox"
            aria-autocomplete="list"
            [attr.aria-expanded]="searchResults().length > 0"
          />
          @if (searchQuery) {
            <span class="search-clear" (mousedown)="clearSearch()">&#10005;</span>
          }
        </div>
        @if (searchFocused() && searchResults().length > 0) {
          <div class="search-dropdown" role="listbox">
            @for (r of searchResults(); track r.id) {
              <div class="search-result" role="option" (mousedown)="openResult(r)">
                <span class="result-type">{{ getTypeIcon(r.type) }}</span>
                <div class="result-info">
                  <div class="result-title">{{ r.title }}</div>
                  @if (r.snippet) {
                    <div class="result-snippet">{{ r.snippet }}</div>
                  }
                </div>
                <span class="result-type-label tag" [class]="getTypeTag(r.type)">{{ r.type }}</span>
              </div>
            }
          </div>
        }
      </div>

      <div class="topbar-right">
        <!-- M365 Status -->
        <div class="status">
          <div class="status-dot"></div>
          <span class="status-text">Connected to M365</span>
        </div>

        <!-- Notifications -->
        <div class="notification-wrapper">
          <button class="notification-bell" (click)="toggleNotifications()" aria-label="Notifications" [attr.aria-expanded]="showNotifications()">
            <span>&#128276;</span>
            @if (unreadCount() > 0) {
              <span class="badge">{{ unreadCount() }}</span>
            }
          </button>
          @if (showNotifications()) {
            <div class="notification-dropdown" role="menu">
              <div class="notif-header">
                <span class="notif-title">Notifications</span>
                @if (unreadCount() > 0) {
                  <span class="notif-mark-all" (click)="markAllRead()">Mark all read</span>
                }
              </div>
              @for (n of notifications(); track n.id) {
                <div class="notif-item" role="menuitem" [class.unread]="!n.is_read" (click)="onNotifClick(n)">
                  <div class="notif-dot" [class.active]="!n.is_read"></div>
                  <div class="notif-content">
                    <div class="notif-text">{{ n.title }}</div>
                    @if (n.message) {
                      <div class="notif-meta">{{ n.message }}</div>
                    }
                    <div class="notif-time">{{ formatRelative(n.created_at) }}</div>
                  </div>
                </div>
              }
              @if (notifications().length === 0) {
                <div class="notif-empty">No notifications</div>
              }
            </div>
          }
        </div>

        <!-- Avatar -->
        <div class="avatar-wrapper">
          <div class="avatar" (click)="toggleProfileMenu()" [title]="userService.profile().displayName">{{ userService.profile().initials }}</div>
          @if (showProfileMenu()) {
            <div class="profile-dropdown">
              <div class="profile-info">
                <div class="profile-name">{{ userService.profile().displayName }}</div>
                <div class="profile-email">{{ userService.profile().email }}</div>
              </div>
              <div class="profile-divider"></div>
              <button class="profile-action" (click)="logout()">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
                Sign out
              </button>
            </div>
          }
        </div>
      </div>
    </header>
  `,
  styles: [`
    .topbar {
      height: 64px; border-bottom: 1px solid var(--border-primary);
      display: flex; align-items: center; justify-content: space-between;
      padding: 0 24px; background: var(--bg-secondary); position: relative; z-index: 100;
    }
    .search-wrapper { position: relative; }
    .search-box {
      display: flex; align-items: center; gap: 8px;
      background: var(--bg-input); border: 1px solid var(--border-secondary);
      border-radius: 12px; padding: 8px 16px; width: 400px;
    }
    .search-box input {
      background: transparent; border: none; outline: none;
      color: var(--text-primary); width: 100%; font-size: 14px;
    }
    .search-icon { color: var(--text-muted); }
    .search-clear { color: var(--text-muted); cursor: pointer; font-size: 12px; }
    .search-clear:hover { color: var(--text-primary); }

    .search-dropdown {
      position: absolute; top: 44px; left: 0; right: 0;
      background: var(--bg-secondary); border: 1px solid var(--border-secondary);
      border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.3);
      max-height: 400px; overflow-y: auto; z-index: 200;
    }
    .search-result {
      display: flex; align-items: center; gap: 12px;
      padding: 12px 16px; cursor: pointer; transition: background 0.15s;
    }
    .search-result:hover { background: var(--bg-hover); }
    .result-type { font-size: 18px; min-width: 24px; text-align: center; }
    .result-info { flex: 1; min-width: 0; }
    .result-title { font-weight: 500; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .result-snippet { font-size: 12px; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .result-type-label { font-size: 11px; padding: 2px 8px; }

    .topbar-right { display: flex; align-items: center; gap: 16px; }
    .status { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-secondary); }
    .status-dot { width: 8px; height: 8px; background: #10b981; border-radius: 50%; }

    .notification-wrapper { position: relative; }
    .notification-bell { position: relative; cursor: pointer; font-size: 20px; background: none; border: none; color: inherit; padding: 0; }
    .badge {
      position: absolute; top: -4px; right: -4px;
      width: 18px; height: 18px; background: #ef4444; border-radius: 50%;
      font-size: 11px; display: flex; align-items: center; justify-content: center;
      color: white; font-weight: 600;
    }

    .notification-dropdown {
      position: absolute; top: 36px; right: 0; width: 360px;
      background: var(--bg-secondary); border: 1px solid var(--border-secondary);
      border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.3);
      max-height: 420px; overflow-y: auto; z-index: 200;
    }
    .notif-header {
      display: flex; justify-content: space-between; align-items: center;
      padding: 14px 16px; border-bottom: 1px solid var(--border-secondary);
    }
    .notif-title { font-weight: 600; font-size: 14px; }
    .notif-mark-all { font-size: 12px; color: #3b82f6; cursor: pointer; }
    .notif-mark-all:hover { text-decoration: underline; }
    .notif-item {
      display: flex; gap: 10px; padding: 12px 16px;
      cursor: pointer; transition: background 0.15s;
    }
    .notif-item:hover { background: var(--bg-hover); }
    .notif-item.unread { background: rgba(59, 130, 246, 0.05); }
    .notif-dot { width: 8px; height: 8px; border-radius: 50%; margin-top: 5px; background: transparent; flex-shrink: 0; }
    .notif-dot.active { background: #3b82f6; }
    .notif-content { flex: 1; }
    .notif-text { font-size: 13px; font-weight: 500; margin-bottom: 2px; }
    .notif-meta { font-size: 12px; color: var(--text-muted); margin-bottom: 2px; }
    .notif-time { font-size: 11px; color: var(--text-muted); }
    .notif-empty { padding: 24px; text-align: center; color: var(--text-muted); font-size: 13px; }

    .avatar-wrapper { position: relative; }
    .avatar {
      width: 36px; height: 36px;
      background: linear-gradient(135deg, #3b82f6, #8b5cf6);
      border-radius: 50%; display: flex; align-items: center; justify-content: center;
      color: white; font-weight: 600; font-size: 14px; cursor: pointer;
    }
    .profile-dropdown {
      position: absolute; top: 44px; right: 0; width: 260px;
      background: var(--bg-secondary); border: 1px solid var(--border-secondary);
      border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.3);
      z-index: 200; overflow: hidden;
    }
    .profile-info { padding: 16px; }
    .profile-name { font-weight: 600; font-size: 14px; color: var(--text-primary); }
    .profile-email { font-size: 12px; color: var(--text-muted); margin-top: 2px; }
    .profile-divider { height: 1px; background: var(--border-secondary); }
    .profile-action {
      display: flex; align-items: center; gap: 10px; width: 100%;
      padding: 12px 16px; background: none; border: none;
      color: var(--text-secondary); font-size: 14px; cursor: pointer;
      transition: background 0.15s;
    }
    .profile-action:hover { background: var(--bg-hover); color: #ef4444; }
  `],
})
export class TopbarComponent implements OnInit {
  private router = inject(Router);
  private notificationService = inject(NotificationService);
  private searchService = inject(SearchService);
  private destroyRef = inject(DestroyRef);
  private msalService = environment.requireAuth ? inject(MsalService) : null;
  userService = inject(UserService);

  showProfileMenu = signal(false);
  searchQuery = '';
  searchFocused = signal(false);
  searchResults = signal<SearchResult[]>([]);
  unreadCount = signal(0);
  showNotifications = signal(false);
  notifications = signal<NotificationResponse[]>([]);

  ngOnInit() {
    this.notificationService.getUnreadCount().pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (res) => this.unreadCount.set(res.unread_count),
      error: () => this.unreadCount.set(0),
    });
  }

  onSearch() {
    if (!this.searchQuery.trim()) { this.searchResults.set([]); return; }
    this.searchService.search(this.searchQuery).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (res) => this.searchResults.set(res.results),
      error: () => this.searchResults.set([]),
    });
  }

  onSearchBlur() {
    setTimeout(() => this.searchFocused.set(false), 200);
  }

  clearSearch() {
    this.searchQuery = '';
    this.searchResults.set([]);
  }

  openResult(r: SearchResult) {
    this.searchFocused.set(false);
    this.searchResults.set([]);
    this.searchQuery = '';
    if (r.type === 'meeting') this.router.navigate(['/meetings', r.id]);
    else if (r.type === 'document') this.router.navigate(['/documents']);
    else if (r.type === 'action_item') this.router.navigate(['/actions']);
  }

  getTypeIcon(type: string): string {
    if (type === 'meeting') return '\u{1F4C5}';
    if (type === 'document') return '\u{1F4C4}';
    return '\u2705';
  }

  getTypeTag(type: string): string {
    if (type === 'meeting') return 'tag-blue';
    if (type === 'document') return 'tag-green';
    return 'tag-yellow';
  }

  toggleNotifications() {
    const open = !this.showNotifications();
    this.showNotifications.set(open);
    if (open) {
      this.notificationService.list({ limit: 10 }).pipe(
        takeUntilDestroyed(this.destroyRef),
      ).subscribe({
        next: (res) => this.notifications.set(res.items),
        error: () => {},
      });
    }
  }

  onNotifClick(n: NotificationResponse) {
    if (!n.is_read) {
      this.notificationService.markRead(n.id).pipe(
        takeUntilDestroyed(this.destroyRef),
      ).subscribe({
        next: () => {
          this.notifications.update(list =>
            list.map(item => item.id === n.id ? { ...item, is_read: true } : item)
          );
          this.unreadCount.update(c => Math.max(0, c - 1));
        },
      });
    }
    this.showNotifications.set(false);
    if (n.related_meeting_id) {
      this.router.navigate(['/meetings', n.related_meeting_id]);
    } else if (n.related_action_id) {
      this.router.navigate(['/actions']);
    }
  }

  markAllRead() {
    this.notificationService.markAllRead().pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: () => {
        this.notifications.update(list => list.map(n => ({ ...n, is_read: true })));
        this.unreadCount.set(0);
      },
    });
  }

  toggleProfileMenu() {
    this.showProfileMenu.update(v => !v);
  }

  logout() {
    this.showProfileMenu.set(false);
    this.msalService?.logoutRedirect();
  }

  formatRelative = formatRelative;
}

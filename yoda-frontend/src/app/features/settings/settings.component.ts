/**
 * Settings view -- user preferences and account information.
 *
 * Sections: Appearance (dark/light theme toggle persisted to localStorage),
 * Notifications (summary delivery channel, nudge toggles, auto-join toggle),
 * Account (connected M365 account status and YODA role).
 *
 * Theme changes are applied immediately via data-theme attribute on <html>.
 * Notification preferences are local-only (not yet persisted to backend).
 *
 * Data source: UserService (for profile display).
 * Route: /settings
 */
import { Component, inject, signal, ChangeDetectionStrategy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { UserService } from '../../core/services/user.service';

@Component({
  selector: 'app-settings',
  standalone: true,
  imports: [FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page-header">
      <h1>Settings</h1>
      <p>Manage your preferences and notifications</p>
    </div>

    <!-- Theme -->
    <div class="card">
      <div class="card-title" style="margin-bottom:16px">Appearance</div>
      <div class="setting-row">
        <div>
          <div class="setting-label">Theme</div>
          <div class="setting-desc">Choose dark or light mode</div>
        </div>
        <div class="toggle-group">
          <button class="toggle-btn" [class.active]="theme() === 'dark'" (click)="setTheme('dark')">Dark</button>
          <button class="toggle-btn" [class.active]="theme() === 'light'" (click)="setTheme('light')">Light</button>
        </div>
      </div>
    </div>

    <!-- Notifications -->
    <div class="card">
      <div class="card-title" style="margin-bottom:16px">Notifications</div>
      <div class="setting-row">
        <div>
          <div class="setting-label">Summary Delivery</div>
          <div class="setting-desc">How you receive meeting summaries</div>
        </div>
        <select [(ngModel)]="summaryDelivery" class="setting-select">
          <option value="chat">Teams Chat</option>
          <option value="email">Email</option>
          <option value="both">Both</option>
        </select>
      </div>
      <div class="setting-row">
        <div>
          <div class="setting-label">Action Item Nudges</div>
          <div class="setting-desc">Get reminders for overdue items</div>
        </div>
        <label class="switch">
          <input type="checkbox" [(ngModel)]="nudgesEnabled" />
          <span class="slider"></span>
        </label>
      </div>
      <div class="setting-row">
        <div>
          <div class="setting-label">Weekly Digest</div>
          <div class="setting-desc">Receive a weekly summary every Friday</div>
        </div>
        <label class="switch">
          <input type="checkbox" [(ngModel)]="digestEnabled" />
          <span class="slider"></span>
        </label>
      </div>
      <div class="setting-row">
        <div>
          <div class="setting-label">Auto-join Meetings</div>
          <div class="setting-desc">Bot automatically joins your meetings to take notes</div>
        </div>
        <label class="switch">
          <input type="checkbox" [(ngModel)]="autoJoinEnabled" />
          <span class="slider"></span>
        </label>
      </div>
    </div>

    <!-- Account -->
    <div class="card">
      <div class="card-title" style="margin-bottom:16px">Account</div>
      <div class="setting-row">
        <div>
          <div class="setting-label">Connected Account</div>
          <div class="setting-desc">Microsoft 365 &middot; {{ userService.profile().email || 'Not connected' }}</div>
        </div>
        <span class="tag tag-green">Connected</span>
      </div>
      <div class="setting-row">
        <div>
          <div class="setting-label">Role</div>
          <div class="setting-desc">Your access level in YODA</div>
        </div>
        <span class="tag tag-blue">{{ userService.profile().role }}</span>
      </div>
    </div>
  `,
  styles: [`
    .setting-row {
      display: flex; justify-content: space-between; align-items: center;
      padding: 16px; border-bottom: 1px solid var(--border-secondary);
    }
    .setting-row:last-child { border-bottom: none; }
    .setting-label { font-weight: 500; margin-bottom: 2px; }
    .setting-desc { font-size: 13px; color: var(--text-muted); }
    .setting-select {
      background: var(--bg-input); color: var(--text-primary);
      padding: 8px 14px; border-radius: 8px;
      border: 1px solid var(--border-secondary); font-size: 14px;
    }
    .toggle-group { display: flex; gap: 0; border-radius: 8px; overflow: hidden; border: 1px solid var(--border-secondary); }
    .toggle-btn {
      padding: 8px 16px; background: var(--bg-input); color: var(--text-secondary);
      border: none; cursor: pointer; font-size: 13px; font-weight: 500; transition: all 0.2s;
    }
    .toggle-btn.active { background: #3b82f6; color: white; }
    .switch { position: relative; display: inline-block; width: 44px; height: 24px; }
    .switch input { opacity: 0; width: 0; height: 0; }
    .slider {
      position: absolute; cursor: pointer; inset: 0;
      background: var(--border-primary); border-radius: 24px; transition: 0.3s;
    }
    .slider::before {
      content: ''; position: absolute; height: 18px; width: 18px;
      left: 3px; bottom: 3px; background: white; border-radius: 50%;
      transition: 0.3s; box-shadow: 0 2px 4px rgba(0,0,0,0.2);
    }
    .switch input:checked + .slider { background: #3b82f6; }
    .switch input:checked + .slider::before { transform: translateX(20px); }
  `],
})
export class SettingsComponent {
  userService = inject(UserService);
  theme = signal<'dark' | 'light'>('dark');
  summaryDelivery = 'chat';
  nudgesEnabled = true;
  digestEnabled = true;
  autoJoinEnabled = true;

  constructor() {
    const saved = localStorage.getItem('yoda-theme') as 'dark' | 'light' | null;
    if (saved) this.theme.set(saved);
  }

  setTheme(t: 'dark' | 'light') {
    this.theme.set(t);
    document.documentElement.setAttribute('data-theme', t === 'light' ? 'light' : '');
    localStorage.setItem('yoda-theme', t);
  }
}

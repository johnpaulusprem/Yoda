/**
 * Sidebar navigation component -- fixed 260px left panel.
 *
 * Displays the YODA logo, primary navigation links (Dashboard, Ask AI,
 * Meetings, Action Items, Documents, Insights, Weekly Digest), and a
 * Settings link in the footer. Uses RouterLinkActive for active state
 * highlighting. Navigation items are stored as a signal for potential
 * future dynamic configuration.
 */
import { Component, signal, ChangeDetectionStrategy } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';

interface NavItem {
  icon: string;
  label: string;
  route: string;
}

@Component({
  selector: 'app-sidebar',
  standalone: true,
  imports: [RouterLink, RouterLinkActive],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <aside class="sidebar">
      <div class="logo">
        <div class="logo-icon">Y</div>
        <div class="logo-text">
          <h1>YODA</h1>
          <p>AI Companion</p>
        </div>
      </div>

      <nav class="nav" role="navigation" aria-label="Main navigation">
        @for (item of navItems(); track item.route) {
          <a class="nav-item" [routerLink]="item.route" routerLinkActive="active" #rla="routerLinkActive" [attr.aria-current]="rla.isActive ? 'page' : null">
            <span class="nav-icon">{{ item.icon }}</span>
            <span>{{ item.label }}</span>
          </a>
        }
      </nav>

      <div class="sidebar-footer">
        <a class="nav-item" routerLink="/settings" routerLinkActive="active">
          <span class="nav-icon">&#9881;</span>
          <span>Settings</span>
        </a>
      </div>
    </aside>
  `,
  styles: [`
    .sidebar {
      width: 260px;
      height: 100vh;
      display: flex;
      flex-direction: column;
      background: var(--bg-secondary);
      border-right: 1px solid var(--border-primary);
    }
    .logo {
      padding: 20px;
      border-bottom: 1px solid var(--border-primary);
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .logo-icon {
      width: 40px; height: 40px;
      background: linear-gradient(135deg, #3b82f6, #8b5cf6);
      border-radius: 12px;
      display: flex; align-items: center; justify-content: center;
      font-size: 20px; font-weight: 700; color: white;
    }
    .logo-text h1 { font-size: 16px; font-weight: 700; margin: 0; }
    .logo-text p { font-size: 11px; color: var(--text-muted); margin: 0; }
    .nav { flex: 1; padding: 12px; }
    .nav-item {
      display: flex; align-items: center; gap: 12px;
      padding: 12px 16px; border-radius: 12px;
      cursor: pointer; transition: all 0.2s;
      color: var(--text-secondary); text-decoration: none;
      margin-bottom: 4px; font-weight: 500;
    }
    .nav-item:hover { background: var(--bg-hover); color: var(--text-primary); }
    .nav-item.active { background: #3b82f6; color: white; }
    .nav-icon { font-size: 18px; width: 24px; text-align: center; }
    .sidebar-footer {
      padding: 12px;
      border-top: 1px solid var(--border-primary);
    }
  `],
})
export class SidebarComponent {
  navItems = signal<NavItem[]>([
    { icon: '\u{1F4CA}', label: 'Dashboard', route: '/dashboard' },
    { icon: '\u{1F4AC}', label: 'Ask AI', route: '/chat' },
    { icon: '\u{1F4C5}', label: 'Meetings', route: '/meetings' },
    { icon: '\u2705', label: 'Action Items', route: '/actions' },
    { icon: '\u{1F4C4}', label: 'Documents', route: '/documents' },
    { icon: '\u{1F4A1}', label: 'Insights', route: '/insights' },
    { icon: '\u{1F4CB}', label: 'Weekly Digest', route: '/digest' },
  ]);
}

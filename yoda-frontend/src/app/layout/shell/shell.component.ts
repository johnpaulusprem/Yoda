/**
 * Shell layout component -- wraps every authenticated route.
 *
 * Renders a flexbox layout with the sidebar on the left, and a main area
 * containing the topbar and a scrollable content region with <router-outlet>.
 * All feature routes (dashboard, meetings, chat, etc.) render inside this shell.
 *
 * Layout: [Sidebar | [Topbar / Content(<router-outlet>)]]
 */
import { Component, ChangeDetectionStrategy } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { SidebarComponent } from '../sidebar/sidebar.component';
import { TopbarComponent } from '../topbar/topbar.component';

@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [RouterOutlet, SidebarComponent, TopbarComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="app-shell">
      <app-sidebar />
      <div class="main">
        <app-topbar />
        <div class="content">
          <router-outlet />
        </div>
      </div>
    </div>
  `,
  styles: [`
    .app-shell {
      display: flex;
      height: 100vh;
      background: var(--bg-primary);
      color: var(--text-primary);
    }
    .main {
      flex: 1;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    .content {
      flex: 1;
      overflow-y: auto;
      padding: 24px;
    }
  `],
})
export class ShellComponent {}

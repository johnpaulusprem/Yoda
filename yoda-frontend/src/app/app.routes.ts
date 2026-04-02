/**
 * Application routes -- lazy-loaded standalone components.
 *
 * All routes are children of ShellComponent (sidebar + topbar layout).
 * Default path redirects to /dashboard. Features are code-split via
 * dynamic import() for each route. Wildcard route shows the 404 page.
 *
 * Route structure:
 *   /dashboard, /chat, /meetings, /meetings/:id, /meetings/:id/brief,
 *   /actions, /documents, /insights, /digest, /settings, ** (not-found)
 */
import { Routes } from '@angular/router';
import { ShellComponent } from './layout/shell/shell.component';

export const routes: Routes = [
  {
    path: '',
    component: ShellComponent,
    children: [
      { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
      {
        path: 'dashboard',
        loadComponent: () => import('./features/dashboard/dashboard.component').then(m => m.DashboardComponent),
      },
      {
        path: 'chat',
        loadComponent: () => import('./features/chat/chat.component').then(m => m.ChatComponent),
      },
      {
        path: 'meetings',
        loadComponent: () => import('./features/meetings/meetings-list.component').then(m => m.MeetingsListComponent),
      },
      {
        path: 'meetings/:id',
        loadComponent: () => import('./features/meetings/meeting-detail.component').then(m => m.MeetingDetailComponent),
      },
      {
        path: 'meetings/:id/brief',
        loadComponent: () => import('./features/brief/brief.component').then(m => m.BriefComponent),
      },
      {
        path: 'actions',
        loadComponent: () => import('./features/action-items/action-items.component').then(m => m.ActionItemsComponent),
      },
      {
        path: 'documents',
        loadComponent: () => import('./features/documents/documents.component').then(m => m.DocumentsComponent),
      },
      {
        path: 'insights',
        loadComponent: () => import('./features/insights/insights.component').then(m => m.InsightsComponent),
      },
      {
        path: 'digest',
        loadComponent: () => import('./features/digest/digest.component').then(m => m.DigestComponent),
      },
      {
        path: 'settings',
        loadComponent: () => import('./features/settings/settings.component').then(m => m.SettingsComponent),
      },
    ],
  },
  { path: '**', loadComponent: () => import('./features/not-found/not-found.component').then(m => m.NotFoundComponent) },
];

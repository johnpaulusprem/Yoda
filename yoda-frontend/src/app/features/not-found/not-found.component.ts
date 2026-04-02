/**
 * 404 Not Found page -- displayed for any unmatched route.
 *
 * Shows a simple centered message with a "Back to Dashboard" link.
 * Matched by the wildcard route (**) in app.routes.ts.
 * Route: ** (catch-all)
 */
import { Component, ChangeDetectionStrategy } from '@angular/core';
import { RouterLink } from '@angular/router';

@Component({
  selector: 'app-not-found',
  standalone: true,
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div style="text-align:center;padding:80px 20px">
      <div style="font-size:64px;margin-bottom:16px">404</div>
      <h1 style="font-size:24px;font-weight:600;margin-bottom:8px">Page not found</h1>
      <p style="color:var(--text-muted);margin-bottom:24px">The page you're looking for doesn't exist.</p>
      <a routerLink="/dashboard" class="btn btn-primary">Back to Dashboard</a>
    </div>
  `,
})
export class NotFoundComponent {}

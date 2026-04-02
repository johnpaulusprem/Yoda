/**
 * Root application component -- minimal shell that hosts <router-outlet>.
 *
 * All visual layout (sidebar, topbar) is handled by ShellComponent,
 * which is the parent route component. This root component exists solely
 * as the Angular bootstrap entry point with OnPush change detection.
 */
import { Component, ChangeDetectionStrategy } from '@angular/core';
import { RouterOutlet } from '@angular/router';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<router-outlet />`,
})
export class App {}

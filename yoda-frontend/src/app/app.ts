/**
 * Root application component -- minimal shell that hosts <router-outlet>.
 *
 * All visual layout (sidebar, topbar) is handled by ShellComponent,
 * which is the parent route component. This root component exists solely
 * as the Angular bootstrap entry point with OnPush change detection.
 */
import { Component, ChangeDetectionStrategy, OnInit, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { MsalService } from '@azure/msal-angular';
import { environment } from '../environments/environment';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<router-outlet />`,
})
export class App implements OnInit {
  private msalService = environment.requireAuth ? inject(MsalService) : null;

  ngOnInit(): void {
    if (!this.msalService) return;
    this.msalService.instance.initialize().then(() => {
      return this.msalService!.instance.handleRedirectPromise();
    }).then(() => {
      const accounts = this.msalService!.instance.getAllAccounts();
      if (accounts.length > 0) {
        this.msalService!.instance.setActiveAccount(accounts[0]);
      }
    });
  }
}

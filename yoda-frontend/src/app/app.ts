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
import { isAuthRequired } from '../environments/environment';
import { UserService } from './core/services/user.service';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<router-outlet />`,
})
export class App implements OnInit {
  private msalService = inject(MsalService, { optional: true });
  private userService = inject(UserService);

  ngOnInit(): void {
    if (!isAuthRequired() || !this.msalService) return;
    this.msalService.instance.initialize().then(() => {
      return this.msalService!.instance.handleRedirectPromise();
    }).then(() => {
      const accounts = this.msalService!.instance.getAllAccounts();
      if (accounts.length > 0) {
        this.msalService!.instance.setActiveAccount(accounts[0]);
        this.userService.setFromMsal(accounts[0]);
      }
    });
  }
}

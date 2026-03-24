/**
 * User profile service -- holds the current user's display name, initials, email, and role.
 *
 * In dev mode a placeholder profile is used. In production, setFromMsal() is called
 * after MSAL authentication to populate the profile from the Azure AD account.
 * Exposes a writable signal so components can reactively read profile data.
 *
 * Used by: TopbarComponent (avatar), SettingsComponent (account info), DashboardComponent (greeting).
 */
import { Injectable, signal } from '@angular/core';

export interface UserProfile {
  displayName: string;
  initials: string;
  email: string;
  role: string;
}

@Injectable({ providedIn: 'root' })
export class UserService {
  // In dev mode, use placeholder. In prod, MSAL populates this.
  profile = signal<UserProfile>({
    displayName: 'User',
    initials: 'U',
    email: '',
    role: 'CXO.User',
  });

  setFromMsal(account: { name?: string; username?: string }) {
    const name = account.name || 'User';
    const initials = name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2);
    this.profile.set({
      displayName: name,
      initials,
      email: account.username || '',
      role: 'CXO.User',
    });
  }
}

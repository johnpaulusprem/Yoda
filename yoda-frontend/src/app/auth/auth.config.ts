/**
 * MSAL (Microsoft Authentication Library) configuration factories.
 *
 * Configures Azure AD / Entra ID authentication for the YODA frontend:
 * - createMsalInstance: PublicClientApplication with tenant, client ID, and redirect URI.
 * - createMsalGuardConfig: route guard using redirect interaction type.
 * - createMsalInterceptorConfig: auto-attaches Bearer tokens to /api/* requests.
 *
 * All values come from environment.azure.*. Auth is conditionally enabled
 * via environment.requireAuth in app.config.ts.
 */
import { MsalGuardConfiguration, MsalInterceptorConfiguration } from '@azure/msal-angular';
import { BrowserCacheLocation, InteractionType, PublicClientApplication } from '@azure/msal-browser';
import { environment } from '../../environments/environment';

export function createMsalInstance(): PublicClientApplication {
  return new PublicClientApplication({
    auth: {
      clientId: environment.azure.clientId,
      authority: environment.azure.authority,
      redirectUri: environment.azure.redirectUri,
    },
    cache: {
      cacheLocation: BrowserCacheLocation.LocalStorage,
      storeAuthStateInCookie: false,
    },
  });
}

export function createMsalGuardConfig(): MsalGuardConfiguration {
  return {
    interactionType: InteractionType.Redirect,
    authRequest: {
      scopes: environment.azure.scopes,
    },
  };
}

export function createMsalInterceptorConfig(): MsalInterceptorConfiguration {
  const protectedResourceMap = new Map<string, string[]>();
  protectedResourceMap.set('/api/*', environment.azure.scopes);

  return {
    interactionType: InteractionType.Redirect,
    protectedResourceMap,
  };
}

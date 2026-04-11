/**
 * Angular application configuration -- providers for routing, HTTP, and MSAL auth.
 *
 * MSAL providers (MsalService, MsalGuard, MsalInterceptor, MsalBroadcastService)
 * are conditionally included based on isAuthRequired() (see environments). When disabled
 * (local dev), the app runs without Azure AD authentication.
 *
 * Key providers: provideRouter, provideHttpClient (with DI-based interceptors),
 * and the MSAL provider array for production auth.
 */
import { ApplicationConfig, Provider, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter } from '@angular/router';
import { provideHttpClient, withInterceptorsFromDi } from '@angular/common/http';
import { HTTP_INTERCEPTORS } from '@angular/common/http';
import {
  MSAL_GUARD_CONFIG,
  MSAL_INSTANCE,
  MSAL_INTERCEPTOR_CONFIG,
  MsalBroadcastService,
  MsalGuard,
  MsalInterceptor,
  MsalService,
} from '@azure/msal-angular';
import { isAuthRequired } from '../environments/environment';
import { createMsalInstance, createMsalGuardConfig, createMsalInterceptorConfig } from './auth/auth.config';

import { routes } from './app.routes';

const msalProviders: Provider[] = [
  { provide: MSAL_INSTANCE, useFactory: createMsalInstance },
  { provide: MSAL_GUARD_CONFIG, useFactory: createMsalGuardConfig },
  { provide: MSAL_INTERCEPTOR_CONFIG, useFactory: createMsalInterceptorConfig },
  { provide: HTTP_INTERCEPTORS, useClass: MsalInterceptor, multi: true },
  MsalService,
  MsalGuard,
  MsalBroadcastService,
];

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes),
    provideHttpClient(withInterceptorsFromDi()),
    ...(isAuthRequired() ? msalProviders : []),
  ],
};

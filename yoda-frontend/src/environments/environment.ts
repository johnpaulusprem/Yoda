import { parseAuthRequiredFlag } from './require-auth-flag';

export const environment = {
  production: false,
  apiBaseUrl: '/yoda-api',
  /** MSAL + route guards. Must match backend REQUIRE_AUTH for API calls to succeed without a token. */
  requireAuth: true as boolean | string,

  azure: {
    tenantId: '4f889516-c21b-4cca-8d61-c6f0691b29da',
    clientId: 'edc2ec51-1549-446f-bf2d-d49b0130788b',
    authority: 'https://login.microsoftonline.com/4f889516-c21b-4cca-8d61-c6f0691b29da',
    redirectUri: 'http://localhost:4200/yoda/',
    scopes: ['api://edc2ec51-1549-446f-bf2d-d49b0130788b/access_as_user'],
  },
};

export function isAuthRequired(): boolean {
  return parseAuthRequiredFlag(environment.requireAuth);
}

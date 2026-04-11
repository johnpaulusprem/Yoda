import { parseAuthRequiredFlag } from './require-auth-flag';

export const environment = {
  production: true,
  apiBaseUrl: '/yoda-api',
  requireAuth: true as boolean | string,
  azure: {
    tenantId: '__AZURE_TENANT_ID__',
    clientId: '__AZURE_CLIENT_ID__',
    authority: 'https://login.microsoftonline.com/__AZURE_TENANT_ID__',
    redirectUri: '__REDIRECT_URI__',
    scopes: ['api://__AZURE_CLIENT_ID__/access_as_user'],
  },
};

export function isAuthRequired(): boolean {
  return parseAuthRequiredFlag(environment.requireAuth);
}

// NOTE: Azure placeholders may be replaced at build/deploy time (envsubst, etc.).
// Set requireAuth to false (boolean) when the API runs with REQUIRE_AUTH=false.

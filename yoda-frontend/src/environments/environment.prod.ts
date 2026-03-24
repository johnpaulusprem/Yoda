export const environment = {
  production: true,
  apiBaseUrl: '',
  requireAuth: true,
  azure: {
    tenantId: '__AZURE_TENANT_ID__',
    clientId: '__AZURE_CLIENT_ID__',
    authority: 'https://login.microsoftonline.com/__AZURE_TENANT_ID__',
    redirectUri: '__REDIRECT_URI__',
    scopes: ['api://__AZURE_CLIENT_ID__/access_as_user'],
  },
};
// NOTE: Placeholders are replaced at build time via Docker entrypoint envsubst
// or angular.json fileReplacements

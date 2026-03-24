export const environment = {
  production: false,
  apiBaseUrl: '',  // empty — Angular dev proxy forwards /api/* to backend services
  requireAuth: false,

  // Azure Entra ID / MSAL — set these for authenticated dev
  azure: {
    tenantId: 'your-tenant-id',
    clientId: 'your-client-id',
    authority: 'https://login.microsoftonline.com/your-tenant-id',
    redirectUri: 'http://localhost:4200',
    scopes: ['api://your-client-id/access_as_user'],
  },
};

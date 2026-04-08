export const environment = {
  production: false,
  apiBaseUrl: '/yoda-api',
  requireAuth: true,

  azure: {
    tenantId: '4f889516-c21b-4cca-8d61-c6f0691b29da',
    clientId: 'edc2ec51-1549-446f-bf2d-d49b0130788b',
    authority: 'https://login.microsoftonline.com/4f889516-c21b-4cca-8d61-c6f0691b29da',
    redirectUri: 'http://localhost:4200/yoda/',
    scopes: ['api://edc2ec51-1549-446f-bf2d-d49b0130788b/access_as_user'],
  },
};

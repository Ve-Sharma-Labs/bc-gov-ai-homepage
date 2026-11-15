targetScope = 'resourceGroup'

param webAppName string
param tenantId string
param accessClientId string
param operatorObjectId string

resource web 'Microsoft.App/containerApps@2025-01-01' existing = {
  name: webAppName
}

resource auth 'Microsoft.App/containerApps/authConfigs@2025-01-01' = {
  parent: web
  name: 'current'
  properties: {
    platform: { enabled: true }
    globalValidation: {
      unauthenticatedClientAction: 'Return401'
      excludedPaths: ['/favicon.ico']
    }
    httpSettings: { requireHttps: true }
    login: { tokenStore: { enabled: false } }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: accessClientId
          openIdIssuer: 'https://login.microsoftonline.com/${tenantId}/v2.0'
        }
        validation: {
          allowedAudiences: [accessClientId]
          defaultAuthorizationPolicy: {
            allowedApplications: ['04b07795-8ddb-461a-bbee-02f9e1bf7b46']
            allowedPrincipals: { identities: [operatorObjectId] }
          }
        }
      }
    }
  }
}

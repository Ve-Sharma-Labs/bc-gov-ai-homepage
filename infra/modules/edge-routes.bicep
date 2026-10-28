targetScope = 'resourceGroup'

param profileName string
param endpointName string
param webUrl string
param environmentId string
param privateLinkLocation string

resource profile 'Microsoft.Cdn/profiles@2025-06-01' existing = { name: profileName }
resource endpoint 'Microsoft.Cdn/profiles/afdEndpoints@2025-06-01' existing = {
  parent: profile
  name: endpointName
}
resource group 'Microsoft.Cdn/profiles/originGroups@2025-06-01' = {
  parent: profile
  name: 'web'
  properties: {
    loadBalancingSettings: {
      sampleSize: 4
      successfulSamplesRequired: 3
      additionalLatencyInMilliseconds: 0
    }
    healthProbeSettings: {
      probePath: '/'
      probeProtocol: 'Https'
      probeRequestType: 'GET'
      probeIntervalInSeconds: 30
    }
  }
}
resource origin 'Microsoft.Cdn/profiles/originGroups/origins@2025-06-01' = {
  parent: group
  name: 'container-app'
  properties: {
    hostName: replace(webUrl, 'https://', '')
    originHostHeader: replace(webUrl, 'https://', '')
    httpsPort: 443
    enabledState: 'Enabled'
    enforceCertificateNameCheck: true
    priority: 1
    weight: 1000
    sharedPrivateLinkResource: {
      groupId: 'managedEnvironments'
      privateLink: { id: environmentId }
      privateLinkLocation: privateLinkLocation
      requestMessage: 'BC pilot Front Door origin; approve only this reviewed connection.'
    }
  }
}
resource route 'Microsoft.Cdn/profiles/afdEndpoints/routes@2025-06-01' = {
  parent: endpoint
  name: 'application'
  properties: {
    enabledState: 'Enabled'
    supportedProtocols: ['Https']
    forwardingProtocol: 'HttpsOnly'
    httpsRedirect: 'Enabled'
    linkToDefaultDomain: 'Enabled'
    patternsToMatch: ['/*']
    originGroup: { id: group.id }
  }
  dependsOn: [origin]
}

targetScope = 'resourceGroup'

param profileName string
param endpointName string
@allowed(['closed', 'validation'])
param stage string
param policyId string

resource profile 'Microsoft.Cdn/profiles@2025-06-01' existing = {
  name: profileName
}
resource endpoint 'Microsoft.Cdn/profiles/afdEndpoints@2025-06-01' = {
  parent: profile
  name: endpointName
  location: 'global'
  properties: { enabledState: stage == 'closed' ? 'Disabled' : 'Enabled' }
}
resource policy 'Microsoft.Cdn/profiles/securityPolicies@2025-06-01' = {
  parent: profile
  name: '${endpointName}-validation'
  properties: {
    parameters: {
      type: 'WebApplicationFirewall'
      wafPolicy: { id: policyId }
      associations: [{ domains: [{ id: endpoint.id }], patternsToMatch: ['/*'] }]
    }
  }
}

output endpointName string = endpoint.name
output origin string = 'https://${endpoint.properties.hostName}'
output frontDoorId string = profile.properties.frontDoorId

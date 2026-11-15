targetScope = 'resourceGroup'

param name string
param tags object
@allowed(['closed', 'validation', 'public'])
param stage string
param validationCidrs array

resource profile 'Microsoft.Cdn/profiles@2025-06-01' = {
  name: 'afd-${name}'
  location: 'global'
  tags: tags
  sku: { name: 'Premium_AzureFrontDoor' }
  properties: { originResponseTimeoutSeconds: 120 }
}
resource endpoint 'Microsoft.Cdn/profiles/afdEndpoints@2025-06-01' = {
  parent: profile
  name: name
  location: 'global'
  properties: { enabledState: stage == 'closed' ? 'Disabled' : 'Enabled' }
  dependsOn: [waf]
}
module waf './edge-policy.bicep' = {
  name: 'edge-policy'
  params: {
    name: name
    tags: tags
    stage: stage
    validationCidrs: validationCidrs
  }
}
resource policy 'Microsoft.Cdn/profiles/securityPolicies@2025-06-01' = {
  parent: profile
  name: 'public-preview'
  properties: {
    parameters: {
      type: 'WebApplicationFirewall'
      wafPolicy: { id: waf.outputs.policyId }
      associations: [{ domains: [{ id: endpoint.id }], patternsToMatch: ['/*'] }]
    }
  }
}

output profileName string = profile.name
output endpointName string = endpoint.name
output origin string = 'https://${endpoint.properties.hostName}'
output frontDoorId string = profile.properties.frontDoorId

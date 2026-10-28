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
resource waf 'Microsoft.Network/frontdoorWebApplicationFirewallPolicies@2024-02-01' = {
  name: replace('waf${name}', '-', '')
  location: 'global'
  tags: tags
  sku: { name: 'Premium_AzureFrontDoor' }
  properties: {
    policySettings: { enabledState: 'Enabled', mode: 'Prevention' }
    customRules: {
      rules: concat(stage == 'validation' ? [
        {
          name: 'ValidationOnly'
          priority: 1
          ruleType: 'MatchRule'
          action: 'Block'
          enabledState: 'Enabled'
          matchConditions: [
            {
              matchVariable: 'SocketAddr'
              operator: 'IPMatch'
              negateCondition: true
              matchValue: validationCidrs
            }
          ]
        }
      ] : [], [
        {
          name: 'ApiRateLimit'
          priority: 10
          ruleType: 'RateLimitRule'
          rateLimitDurationInMinutes: 1
          rateLimitThreshold: 300
          action: 'Block'
          enabledState: 'Enabled'
          matchConditions: [
            {
              matchVariable: 'RequestUri'
              operator: 'BeginsWith'
              matchValue: ['/api/']
            }
          ]
        }
      ])
    }
    managedRules: {
      managedRuleSets: [
        { ruleSetType: 'Microsoft_DefaultRuleSet', ruleSetVersion: '2.1', ruleSetAction: 'Block' }
        { ruleSetType: 'Microsoft_BotManagerRuleSet', ruleSetVersion: '1.1', ruleSetAction: 'Block' }
      ]
    }
  }
}
resource policy 'Microsoft.Cdn/profiles/securityPolicies@2025-06-01' = {
  parent: profile
  name: 'public-preview'
  properties: {
    parameters: {
      type: 'WebApplicationFirewall'
      wafPolicy: { id: waf.id }
      associations: [{ domains: [{ id: endpoint.id }], patternsToMatch: ['/*'] }]
    }
  }
}

output profileName string = profile.name
output endpointName string = endpoint.name
output origin string = 'https://${endpoint.properties.hostName}'
output frontDoorId string = profile.properties.frontDoorId

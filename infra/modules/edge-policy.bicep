targetScope = 'resourceGroup'

param name string
param tags object
@allowed(['closed', 'validation', 'public'])
param stage string
param validationCidrs array

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
          matchConditions: [{
            matchVariable: 'SocketAddr'
            operator: 'IPMatch'
            negateCondition: true
            matchValue: validationCidrs
          }]
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
          matchConditions: [{
            matchVariable: 'RequestUri'
            operator: 'BeginsWith'
            matchValue: ['/api/']
          }]
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

output policyId string = waf.id

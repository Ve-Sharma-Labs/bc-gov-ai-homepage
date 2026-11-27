targetScope = 'resourceGroup'

param redisName string
param workspaceName string

resource redis 'Microsoft.Cache/redisEnterprise@2026-09-01' existing = {
  name: redisName
}

resource database 'Microsoft.Cache/redisEnterprise/databases@2026-09-01' existing = {
  parent: redis
  name: 'default'
}

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: workspaceName
}

resource diagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: database
  name: 'sk-redis-connection-audit'
  properties: {
    workspaceId: workspace.id
    logAnalyticsDestinationType: 'Dedicated'
    logs: [{
      categoryGroup: 'allLogs'
      enabled: true
    }]
  }
}

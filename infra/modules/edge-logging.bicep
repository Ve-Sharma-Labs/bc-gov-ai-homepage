targetScope = 'resourceGroup'

param profileName string
param workspaceResourceId string

resource profile 'Microsoft.Cdn/profiles@2025-06-01' existing = {
  name: profileName
}

resource accessLogs 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: profile
  name: 'pilot-edge-access'
  properties: {
    workspaceId: workspaceResourceId
    logs: [
      {
        category: 'FrontDoorAccessLog'
        enabled: true
      }
    ]
  }
}

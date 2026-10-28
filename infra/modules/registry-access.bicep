targetScope = 'resourceGroup'

param name string
param principalIds string[]

resource registry 'Microsoft.ContainerRegistry/registries@2025-04-01' existing = {
  name: name
}

resource imagePull 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for principalId in principalIds: {
    name: guid(registry.id, principalId, 'acrpull')
    scope: registry
    properties: {
      principalId: principalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: subscriptionResourceId(
        'Microsoft.Authorization/roleDefinitions',
        '7f951dda-4ed3-4680-a7ca-43fe172d538d'
      )
    }
  }
]

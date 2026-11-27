targetScope = 'resourceGroup'

param apiPrincipalId string

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: 'ai-skassist-rywtikimq4'
}
resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' existing = {
  parent: foundry
  name: 'sk-service-pilot'
}
resource search 'Microsoft.Search/searchServices@2025-05-01' existing = {
  name: 'srch-skassist-rywtikimq4'
}

var foundryUser = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d')
var modelUser = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
var searchReader = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '1407120a-92aa-4202-b7e9-c0e197c71c8f')

resource projectAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: project
  name: guid(project.id, apiPrincipalId, foundryUser)
  properties: {
    principalId: apiPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: foundryUser
  }
}
resource modelAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, apiPrincipalId, modelUser)
  properties: {
    principalId: apiPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: modelUser
  }
}
resource searchAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, apiPrincipalId, searchReader)
  properties: {
    principalId: apiPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: searchReader
  }
}

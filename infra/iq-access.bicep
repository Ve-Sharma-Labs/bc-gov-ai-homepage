targetScope = 'resourceGroup'

param foundryName string
param searchName string
@description('Verified object/principal ID of the existing API managed identity.')
param apiPrincipalId string

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryName
}
resource search 'Microsoft.Search/searchServices@2025-05-01' existing = {
  name: searchName
}

var inferenceRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
var readerRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'acdd72a7-3385-48ef-bd42-f606fba81ae7')

resource searchInference 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, search.id, inferenceRole)
  properties: {
    principalId: search.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: inferenceRole
  }
}
resource apiKnowledgeReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, apiPrincipalId, readerRole)
  properties: {
    principalId: apiPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: readerRole
  }
}

output inferenceAssignmentId string = searchInference.id
output readerAssignmentId string = apiKnowledgeReader.id

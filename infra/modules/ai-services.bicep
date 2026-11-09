targetScope = 'resourceGroup'

param name string
param location string
param tags object
param deployments array
param searchSku string
param apiPrincipalId string
param publisherPrincipalId string
@description('Separate approval to let the Search identity invoke the existing planning deployment. Does not enable retrieval billing or the optional UI.')
param foundryIqInferenceApproved bool = false
@description('Separate approval for the API identity to read Search configuration. Does not grant document writes or administrator access.')
param foundryIqMetadataReadApproved bool = false

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: 'ai-${name}'
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  tags: tags
  properties: {
    customSubDomainName: 'ai-${name}'
    allowProjectManagement: true
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundry
  name: 'bc-service-pilot'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'BC service assistant pilot'
    description: 'Read-only public guidance and official handoffs.'
  }
}

@batchSize(1)
resource models 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = [for model in deployments: {
  parent: foundry
  name: model.deploymentName
  sku: {
    name: model.sku
    capacity: model.capacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: model.modelName
      version: model.modelVersion
    }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
  dependsOn: [project]
}]

resource search 'Microsoft.Search/searchServices@2025-05-01' = {
  name: 'srch-${name}'
  location: location
  tags: tags
  sku: { name: searchSku }
  identity: { type: 'SystemAssigned' }
  properties: {
    disableLocalAuth: true
    publicNetworkAccess: 'enabled'
    replicaCount: 1
    partitionCount: 1
    semanticSearch: 'standard'
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'st${uniqueString(resourceGroup().id, name)}'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
  }
}
resource blobs 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}
resource staged 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobs
  name: 'reviewed-content'
  properties: { publicAccess: 'None' }
}

var foundryUser = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d')
var openAIUser = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
resource projectRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principal in [apiPrincipalId, publisherPrincipalId]: {
  scope: project
  name: guid(project.id, principal, foundryUser)
  properties: {
    principalId: principal
    principalType: 'ServicePrincipal'
    roleDefinitionId: foundryUser
  }
}]
resource modelRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principal in [apiPrincipalId, publisherPrincipalId]: {
  scope: foundry
  name: guid(foundry.id, principal, openAIUser)
  properties: {
    principalId: principal
    principalType: 'ServicePrincipal'
    roleDefinitionId: openAIUser
  }
}]
resource searchReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, apiPrincipalId, 'reader')
  properties: {
    principalId: apiPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '1407120a-92aa-4202-b7e9-c0e197c71c8f')
  }
}
resource searchPlanningInference 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (foundryIqInferenceApproved) {
  scope: foundry
  name: guid(foundry.id, search.id, openAIUser)
  properties: {
    principalId: search.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: openAIUser
  }
}
resource apiKnowledgeReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (foundryIqMetadataReadApproved) {
  scope: search
  name: guid(search.id, apiPrincipalId, subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'acdd72a7-3385-48ef-bd42-f606fba81ae7'))
  properties: {
    principalId: apiPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'acdd72a7-3385-48ef-bd42-f606fba81ae7')
  }
}
resource searchPublisher 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for role in [
  '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
  '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
]: {
  scope: search
  name: guid(search.id, publisherPrincipalId, role)
  properties: {
    principalId: publisherPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role)
  }
}]
resource stagingPublisher 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: staged
  name: guid(staged.id, publisherPrincipalId, 'publisher')
  properties: {
    principalId: publisherPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  }
}

output projectEndpoint string = 'https://${foundry.name}.services.ai.azure.com/api/projects/${project.name}'
output projectId string = project.id
output modelEndpoint string = 'https://${foundry.name}.openai.azure.com'
output searchEndpoint string = 'https://${search.name}.search.windows.net'
output storageEndpoint string = storage.properties.primaryEndpoints.blob
output storageContainer string = staged.name

targetScope = 'resourceGroup'

param name string
param location string
param tags object
param modelDeployments array
param foundryAgentsJson string
param foundryGeneralAgentJson string
param foundryContextualAgentJson string
param foundryConversationAgentJson string
param aiConversationEnabled string
param taskAssistanceEnabled string
param aiConversationPrivacyReviewed string
param syntheticContextEnabled string
param searchIndex string
param searchMetadataEnabled string
param searchMetadataReviewed string
param searchSku string
param redisSku string
param apiApplicationClientId string
param apiImageName string
param webImageName string
param controls object
param embeddingDeployment string
param embeddingDimensions int
param stage string
param validationCidrs array
param networkPrefix string
param appsSubnetPrefix string
param privateSubnetPrefix string
@secure()
param clientHashKey string

resource apiIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: 'id-${name}-api'
  location: location
  tags: tags
}
resource webIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: 'id-${name}-web'
  location: location
  tags: tags
}
resource publisherIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: 'id-${name}-publisher'
  location: location
  tags: tags
}
module network './network.bicep' = {
  name: 'network'
  params: {
    name: name
    location: location
    tags: tags
    addressPrefix: networkPrefix
    appsSubnetPrefix: appsSubnetPrefix
    privateSubnetPrefix: privateSubnetPrefix
  }
}
module ai './ai-services.bicep' = {
  name: 'ai-services'
  params: {
    name: name
    location: location
    tags: tags
    deployments: modelDeployments
    searchSku: searchSku
    apiPrincipalId: apiIdentity.properties.principalId
    publisherPrincipalId: publisherIdentity.properties.principalId
  }
}
module state './shared-controls.bicep' = {
  name: 'shared-controls'
  params: {
    name: name
    location: location
    tags: tags
    sku: redisSku
    apiPrincipalId: apiIdentity.properties.principalId
    networkId: network.outputs.networkId
    subnetId: network.outputs.privateSubnetId
  }
}
module edge './edge-profile.bicep' = {
  name: 'edge-profile'
  params: {
    name: name
    tags: tags
    stage: stage
    validationCidrs: validationCidrs
  }
}
module hosting './hosting.bicep' = {
  name: 'hosting'
  params: {
    name: name
    location: location
    tags: tags
    foundryProjectEndpoint: ai.outputs.projectEndpoint
    foundryAgentsJson: foundryAgentsJson
    foundryGeneralAgentJson: foundryGeneralAgentJson
    foundryContextualAgentJson: foundryContextualAgentJson
    foundryConversationAgentJson: foundryConversationAgentJson
    aiConversationEnabled: aiConversationEnabled
    taskAssistanceEnabled: taskAssistanceEnabled
    aiConversationPrivacyReviewed: aiConversationPrivacyReviewed
    syntheticContextEnabled: syntheticContextEnabled
    searchEndpoint: ai.outputs.searchEndpoint
    searchIndex: searchIndex
    searchMetadataEnabled: searchMetadataEnabled
    searchMetadataReviewed: searchMetadataReviewed
    modelEndpoint: ai.outputs.modelEndpoint
    embeddingDeployment: embeddingDeployment
    embeddingDimensions: embeddingDimensions
    redisEndpoint: state.outputs.endpoint
    apiApplicationClientId: apiApplicationClientId
    apiImageName: apiImageName
    webImageName: webImageName
    apiIdentityName: apiIdentity.name
    apiIdentityId: apiIdentity.id
    apiPrincipalId: apiIdentity.properties.principalId
    apiClientId: apiIdentity.properties.clientId
    webIdentityName: webIdentity.name
    webIdentityId: webIdentity.id
    webPrincipalId: webIdentity.properties.principalId
    webClientId: webIdentity.properties.clientId
    infrastructureSubnetId: network.outputs.appsSubnetId
    publicOrigin: edge.outputs.origin
    frontDoorId: edge.outputs.frontDoorId
    controls: controls
    clientHashKey: clientHashKey
  }
}
module routes './edge-routes.bicep' = {
  name: 'edge-routes'
  params: {
    profileName: edge.outputs.profileName
    endpointName: edge.outputs.endpointName
    webUrl: hosting.outputs.webUrl
    environmentId: hosting.outputs.environmentResourceId
    privateLinkLocation: location
  }
}
module edgeLogs './edge-logging.bicep' = {
  name: 'edge-logging'
  params: {
    profileName: edge.outputs.profileName
    workspaceResourceId: hosting.outputs.logsResourceId
  }
}

output registryEndpoint string = hosting.outputs.registryEndpoint
output registryName string = hosting.outputs.registryName
output environmentResourceId string = hosting.outputs.environmentResourceId
output apiName string = hosting.outputs.apiName
output webName string = hosting.outputs.webName
output foundryEndpoint string = ai.outputs.projectEndpoint
output foundryProjectId string = ai.outputs.projectId
output searchEndpoint string = ai.outputs.searchEndpoint
output storageEndpoint string = ai.outputs.storageEndpoint
output storageContainer string = ai.outputs.storageContainer
output publisherIdentityId string = publisherIdentity.id
output publisherClientId string = publisherIdentity.properties.clientId
output webUrl string = edge.outputs.origin
output frontDoorProfileName string = edge.outputs.profileName
output frontDoorEndpointName string = edge.outputs.endpointName

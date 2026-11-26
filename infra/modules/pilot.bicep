targetScope = 'resourceGroup'

param name string
param location string
param tags object
param deploymentKind string = 'pilot'
param sharedFrontDoorProfileName string = ''
param sharedFrontDoorResourceGroup string = ''
param frontDoorPrivateLinkLocation string = ''
param stagingIdentities object = {}
param releaseCommit string = ''
param releaseId string = ''
param releaseProbeEnabled bool = false
param modelDeployments array
param foundryAgentsJson string
param foundryGeneralAgentJson string
param foundryContextualAgentJson string
param foundryConversationAgentJson string
param researchConfig object = {}
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

var sharedEdge = !empty(sharedFrontDoorProfileName)
var edgeResourceGroup = sharedEdge ? sharedFrontDoorResourceGroup : resourceGroup().name
var existingIdentities = deploymentKind == 'staging' && !empty(stagingIdentities)
var apiPrincipalId = existingIdentities ? stagingIdentities.api.principalId : apiIdentity!.properties.principalId
var apiClientId = existingIdentities ? stagingIdentities.api.clientId : apiIdentity!.properties.clientId
var webPrincipalId = existingIdentities ? stagingIdentities.web.principalId : webIdentity!.properties.principalId
var webClientId = existingIdentities ? stagingIdentities.web.clientId : webIdentity!.properties.clientId
var publisherPrincipalId = existingIdentities ? stagingIdentities.publisher.principalId : publisherIdentity!.properties.principalId
var publisherClientId = existingIdentities ? stagingIdentities.publisher.clientId : publisherIdentity!.properties.clientId

resource apiIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = if (!existingIdentities) {
  name: 'id-${name}-api'
  location: location
  tags: tags
}
resource webIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = if (!existingIdentities) {
  name: 'id-${name}-web'
  location: location
  tags: tags
}
resource publisherIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = if (!existingIdentities) {
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
    apiPrincipalId: apiPrincipalId
    publisherPrincipalId: publisherPrincipalId
    privateStorage: deploymentKind == 'staging'
    foundryIqInferenceApproved: researchConfig.?foundryIqInferenceApproved ?? false
    foundryIqMetadataReadApproved: researchConfig.?foundryIqMetadataReadApproved ?? false
  }
}
module state './shared-controls.bicep' = {
  name: 'shared-controls'
  params: {
    name: name
    location: location
    tags: tags
    sku: redisSku
    apiPrincipalId: apiPrincipalId
    networkId: network.outputs.networkId
    subnetId: network.outputs.privateSubnetId
  }
}
module edge './edge-profile.bicep' = if (!sharedEdge) {
  name: 'edge-profile'
  params: {
    name: name
    tags: tags
    stage: stage
    validationCidrs: validationCidrs
  }
}
module stagingPolicy './edge-policy.bicep' = if (sharedEdge) {
  name: 'staging-edge-policy'
  params: {
    name: name
    tags: tags
    stage: stage
    validationCidrs: validationCidrs
  }
}
module sharedEndpoint './shared-edge-endpoint.bicep' = if (sharedEdge) {
  name: 'staging-endpoint-${name}'
  scope: resourceGroup(edgeResourceGroup)
  params: {
    profileName: sharedFrontDoorProfileName
    endpointName: name
    stage: stage
    policyId: stagingPolicy!.outputs.policyId
  }
}
var publicOrigin = sharedEdge ? sharedEndpoint!.outputs.origin : edge!.outputs.origin
var profileName = sharedEdge ? sharedFrontDoorProfileName : edge!.outputs.profileName
var endpointName = sharedEdge ? sharedEndpoint!.outputs.endpointName : edge!.outputs.endpointName
var frontDoorId = sharedEdge ? sharedEndpoint!.outputs.frontDoorId : edge!.outputs.frontDoorId

module storageNetwork './storage-private-endpoint.bicep' = if (deploymentKind == 'staging') {
  name: 'staging-storage-network'
  params: {
    name: name
    location: location
    tags: tags
    storageName: ai.outputs.storageName
    networkId: network.outputs.networkId
    subnetId: network.outputs.privateSubnetId
  }
}
module hosting './hosting.bicep' = {
  name: 'hosting'
  params: {
    name: name
    location: location
    tags: tags
    releaseCommit: releaseCommit
    releaseId: releaseId
    releaseProbeEnabled: releaseProbeEnabled
    foundryProjectEndpoint: ai.outputs.projectEndpoint
    foundryAgentsJson: foundryAgentsJson
    foundryGeneralAgentJson: foundryGeneralAgentJson
    foundryContextualAgentJson: foundryContextualAgentJson
    foundryConversationAgentJson: foundryConversationAgentJson
    researchConfig: researchConfig
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
    apiIdentityName: existingIdentities ? last(split(stagingIdentities.api.id, '/')) : apiIdentity!.name
    apiIdentityId: existingIdentities ? stagingIdentities.api.id : apiIdentity!.id
    apiPrincipalId: apiPrincipalId
    apiClientId: apiClientId
    webIdentityName: existingIdentities ? last(split(stagingIdentities.web.id, '/')) : webIdentity!.name
    webIdentityId: existingIdentities ? stagingIdentities.web.id : webIdentity!.id
    webPrincipalId: webPrincipalId
    webClientId: webClientId
    infrastructureSubnetId: network.outputs.appsSubnetId
    publicOrigin: publicOrigin
    frontDoorId: frontDoorId
    controls: controls
    clientHashKey: clientHashKey
  }
}
module routes './edge-routes.bicep' = {
  name: sharedEdge ? 'staging-routes-${name}' : 'edge-routes'
  scope: resourceGroup(edgeResourceGroup)
  params: {
    profileName: profileName
    endpointName: endpointName
    originGroupName: sharedEdge ? '${name}-web' : 'web'
    webUrl: hosting.outputs.webUrl
    environmentId: hosting.outputs.environmentResourceId
    privateLinkLocation: empty(frontDoorPrivateLinkLocation) ? location : frontDoorPrivateLinkLocation
  }
}
module edgeLogs './edge-logging.bicep' = if (!sharedEdge) {
  name: 'edge-logging'
  params: {
    profileName: profileName
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
output publisherIdentityId string = existingIdentities ? stagingIdentities.publisher.id : publisherIdentity!.id
output publisherClientId string = publisherClientId
output webUrl string = publicOrigin
output frontDoorProfileName string = profileName
output frontDoorEndpointName string = endpointName
output releaseProbeId string = hosting.outputs.releaseProbeId
output foundryAccountId string = ai.outputs.accountResourceId
output wafPolicyId string = sharedEdge ? stagingPolicy!.outputs.policyId : edge!.outputs.wafPolicyId

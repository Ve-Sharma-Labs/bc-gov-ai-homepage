targetScope = 'resourceGroup'

@description('Optional existing policy-assigned private subnet network security group to preserve on redeployment.')
param privateSubnetNetworkSecurityGroupId string = ''
@description('Optional existing policy-assigned apps subnet network security group to preserve on redeployment.')
param appsSubnetNetworkSecurityGroupId string = ''

@description('Existing Saskatchewan resource group location.')
param location string = resourceGroup().location
@description('Client ID of the dedicated internal API application.')
param apiApplicationClientId string
@description('Full immutable image reference, or empty for closed bootstrap.')
param apiImageName string = ''
@description('Full immutable image reference, or empty for closed bootstrap.')
param webImageName string = ''
@allowed(['closed', 'validation', 'public'])
param stage string = 'closed'
param validationCidrs array = []
param releaseCommit string = ''
param releaseId string = ''
@secure()
param clientHashKey string

var name = 'skassist-rywtikimq4'
var tags = {
  project: 'sk-government-assistant'
  jurisdiction: 'sk'
  classification: 'pilot'
}
var controls = {
  runLimit: 100
  tokenLimit: 800000
  costLimitMicrousd: 5000000
  tokenPriceMicrousd: 6
  apiMaxReplicas: 1
  webMaxReplicas: 1
}

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
module access './modules/sk-existing-ai-access.bicep' = {
  name: 'sk-existing-ai-access'
  params: {
    apiPrincipalId: apiIdentity.properties.principalId
  }
}
module network './modules/network.bicep' = {
  name: 'sk-network'
  params: {
    name: name
    location: location
    tags: tags
    addressPrefix: '10.144.0.0/16'
    appsSubnetPrefix: '10.144.0.0/23'
    privateSubnetPrefix: '10.144.2.0/24'
    appsSubnetNetworkSecurityGroupId: appsSubnetNetworkSecurityGroupId
    privateSubnetNetworkSecurityGroupId: privateSubnetNetworkSecurityGroupId
  }
}
module state './modules/shared-controls.bicep' = {
  name: 'sk-shared-controls'
  params: {
    name: name
    location: 'canadaeast'
    privateEndpointLocation: location
    tags: tags
    sku: 'Balanced_B0'
    apiPrincipalId: apiIdentity.properties.principalId
    networkId: network.outputs.networkId
    subnetId: network.outputs.privateSubnetId
  }
}
module edge './modules/edge-profile.bicep' = {
  name: 'sk-edge-profile'
  params: {
    name: name
    tags: tags
    stage: stage
    validationCidrs: validationCidrs
  }
}
module hosting './modules/hosting.bicep' = {
  name: 'sk-hosting'
  params: {
    name: name
    jurisdiction: 'sk'
    location: location
    tags: tags
    releaseCommit: releaseCommit
    releaseId: releaseId
    foundryProjectEndpoint: 'https://ai-skassist-rywtikimq4.services.ai.azure.com/api/projects/sk-service-pilot'
    foundryAgentsJson: ' []'
    foundryGeneralAgentJson: '{"name":"sk-service-general","version":"4","modelDeployment":"sk-fast"}'
    foundryContextualAgentJson: ''
    foundryConversationAgentJson: ''
    aiConversationEnabled: 'false'
    taskAssistanceEnabled: 'false'
    aiConversationPrivacyReviewed: 'false'
    syntheticContextEnabled: 'false'
    searchEndpoint: 'https://srch-skassist-rywtikimq4.search.windows.net'
    searchIndex: 'sk-pilot-public'
    searchMetadataEnabled: 'false'
    searchMetadataReviewed: '0'
    modelEndpoint: ''
    embeddingDeployment: ''
    embeddingDimensions: 0
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
module routes './modules/edge-routes.bicep' = {
  name: 'sk-edge-routes'
  params: {
    profileName: edge.outputs.profileName
    endpointName: edge.outputs.endpointName
    webUrl: hosting.outputs.webUrl
    environmentId: hosting.outputs.environmentResourceId
    privateLinkLocation: location
  }
}
module edgeLogs './modules/edge-logging.bicep' = {
  name: 'sk-edge-logging'
  params: {
    profileName: edge.outputs.profileName
    workspaceResourceId: hosting.outputs.logsResourceId
  }
}

output webUrl string = edge.outputs.origin
output registryEndpoint string = hosting.outputs.registryEndpoint
output registryName string = hosting.outputs.registryName
output environmentResourceId string = hosting.outputs.environmentResourceId
output apiName string = hosting.outputs.apiName
output webName string = hosting.outputs.webName
output frontDoorProfileName string = edge.outputs.profileName

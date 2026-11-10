targetScope = 'subscription'

@description('User-confirmed environment label. It is not used as an unrestricted resource name.')
@minLength(1)
@maxLength(40)
param environmentName string

@description('User-confirmed Azure location. No region is selected automatically.')
@minLength(1)
param location string

@description('Explicitly selected model names, versions, SKUs and capacity; no moving defaults.')
param modelDeploymentsJson string
@description('Actual registry returned by the approved seven-agent publication step.')
param foundryAgentsJson string = '[]'
@description('Separately published and pinned general agent. Empty only for closed bootstrap.')
param foundryGeneralAgentJson string = ''
@description('Separately published and pinned synthetic contextual-demo agent.')
param foundryContextualAgentJson string = ''
@description('Distinct, published and pinned version-5 conversation agent.')
param foundryConversationAgentJson string = ''
@description('Server-only optional research configuration. Empty keeps both IQ paths disabled; approval IDs must represent completed reviews.')
param researchConfigJson string = '{}'
@allowed(['false', 'true'])
param aiConversationEnabled string = 'false'
@allowed(['false', 'true'])
param taskAssistanceEnabled string = 'false'
@allowed(['false', 'true'])
@description('Requires an actual review of public AI conversation processing, not just deployment approval.')
param aiConversationPrivacyReviewed string = 'false'
@allowed(['false', 'true'])
@description('Enable only for the reviewed, synthetic-only citizen-context demonstration.')
param syntheticContextEnabled string = 'false'
param searchIndex string = 'bc-pilot-public'
@allowed(['false', 'true'])
@description('Enable only after the additive provenance index schema has been verified.')
param searchMetadataEnabled string = 'false'
@allowed(['0', '1'])
@description('Records the explicit schema review required for the metadata-aware index revision.')
param searchMetadataReviewed string = '0'
param searchSku string
param redisSku string
param apiApplicationClientId string
@description('Reviewed full ACR image digest. Empty is allowed only for closed bootstrap.')
param apiImageName string = ''
@description('Reviewed full ACR image digest. Preserve it when changing exposure or configuration.')
param webImageName string = ''
@description('Reviewed daily run/token/cost limits and conservative per-token price.')
param controlsJson string
param embeddingDeployment string = ''
param embeddingDimensionsJson string = '0'
@allowed(['closed', 'validation', 'public'])
param stage string = 'closed'
param validationCidrsJson string = '[]'
param networkPrefix string
param appsSubnetPrefix string
param privateSubnetPrefix string
@secure()
param clientHashKey string = '${newGuid()}${newGuid()}'

var suffix = take(uniqueString(subscription().id, environmentName, location), 10)
var tags = {
  'azd-env-name': environmentName
  project: 'bc-government-assistant'
  classification: 'pilot'
}

resource resourceGroup 'Microsoft.Resources/resourceGroups@2025-04-01' = {
  name: 'rg-bcassist-${suffix}'
  location: location
  tags: tags
}

module pilot './modules/pilot.bicep' = {
  name: 'bc-assistant-pilot'
  scope: resourceGroup
  params: {
    name: 'bcassist-${suffix}'
    location: location
    tags: tags
    modelDeployments: json(modelDeploymentsJson)
    foundryAgentsJson: foundryAgentsJson
    foundryGeneralAgentJson: foundryGeneralAgentJson
    foundryContextualAgentJson: foundryContextualAgentJson
    foundryConversationAgentJson: foundryConversationAgentJson
    researchConfig: json(researchConfigJson)
    aiConversationEnabled: aiConversationEnabled
    taskAssistanceEnabled: taskAssistanceEnabled
    aiConversationPrivacyReviewed: aiConversationPrivacyReviewed
    syntheticContextEnabled: syntheticContextEnabled
    searchIndex: searchIndex
    searchMetadataEnabled: searchMetadataEnabled
    searchMetadataReviewed: searchMetadataReviewed
    searchSku: searchSku
    redisSku: redisSku
    apiApplicationClientId: apiApplicationClientId
    apiImageName: apiImageName
    webImageName: webImageName
    controls: json(controlsJson)
    embeddingDeployment: embeddingDeployment
    embeddingDimensions: int(embeddingDimensionsJson)
    stage: stage
    validationCidrs: json(validationCidrsJson)
    networkPrefix: networkPrefix
    appsSubnetPrefix: appsSubnetPrefix
    privateSubnetPrefix: privateSubnetPrefix
    clientHashKey: clientHashKey
  }
}

output AZURE_RESOURCE_GROUP string = resourceGroup.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = pilot.outputs.registryEndpoint
output AZURE_CONTAINER_REGISTRY_NAME string = pilot.outputs.registryName
output AZURE_CONTAINER_APPS_ENVIRONMENT_ID string = pilot.outputs.environmentResourceId
output AZURE_API_APP_NAME string = pilot.outputs.apiName
output AZURE_WEB_APP_NAME string = pilot.outputs.webName
output FOUNDRY_PROJECT_ENDPOINT string = pilot.outputs.foundryEndpoint
output FOUNDRY_PROJECT_RESOURCE_ID string = pilot.outputs.foundryProjectId
output AZURE_SEARCH_ENDPOINT string = pilot.outputs.searchEndpoint
output AZURE_STORAGE_ACCOUNT_URL string = pilot.outputs.storageEndpoint
output AZURE_STORAGE_CONTAINER string = pilot.outputs.storageContainer
output PUBLISHER_IDENTITY_RESOURCE_ID string = pilot.outputs.publisherIdentityId
output PUBLISHER_IDENTITY_CLIENT_ID string = pilot.outputs.publisherClientId
output WEB_URL string = pilot.outputs.webUrl
output AZURE_FRONT_DOOR_PROFILE_NAME string = pilot.outputs.frontDoorProfileName
output AZURE_FRONT_DOOR_ENDPOINT_NAME string = pilot.outputs.frontDoorEndpointName

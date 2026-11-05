targetScope = 'resourceGroup'

param name string
param location string
param tags object
param foundryProjectEndpoint string
param foundryAgentsJson string
param foundryGeneralAgentJson string
param foundryContextualAgentJson string
param foundryConversationAgentJson string
param aiConversationEnabled string
param taskAssistanceEnabled string
param aiConversationPrivacyReviewed string
param syntheticContextEnabled string
param searchEndpoint string
param searchIndex string
param searchMetadataEnabled string
param searchMetadataReviewed string
param publicOrigin string
param modelEndpoint string
param embeddingDeployment string
param embeddingDimensions int
param redisEndpoint string
param apiApplicationClientId string
param apiImageName string
param webImageName string
param apiIdentityName string
param apiIdentityId string
param apiPrincipalId string
param apiClientId string
param webIdentityName string
param webIdentityId string
param webPrincipalId string
param webClientId string
param infrastructureSubnetId string
param frontDoorId string
param controls object
@secure()
param clientHashKey string

var apiName = 'ca-${name}-api'
var webName = 'ca-${name}-web'

module logs 'br/public:avm/res/operational-insights/workspace:0.16.1' = {
  name: 'logs'
  params: {
    name: 'log-${name}'
    location: location
    tags: tags
    dataRetention: 30
    forceCmkForQuery: false
    enableTelemetry: false
  }
}

module insights 'br/public:avm/res/insights/component:0.8.0' = {
  name: 'insights'
  params: {
    name: 'appi-${name}'
    location: location
    tags: tags
    workspaceResourceId: logs.outputs.resourceId
    disableIpMasking: false
    disableLocalAuth: true
    retentionInDays: 30
    enableTelemetry: false
  }
}

module stack 'br/public:avm/ptn/azd/container-apps-stack:0.4.0' = {
  name: 'container-stack'
  params: {
    containerAppsEnvironmentName: 'cae-${name}'
    containerRegistryName: replace('cr${name}', '-', '')
    logAnalyticsWorkspaceName: logs.outputs.name
    location: location
    tags: tags
    acrSku: 'Basic'
    acrAdminUserEnabled: false
    publicNetworkAccess: 'Disabled'
    infrastructureSubnetResourceId: infrastructureSubnetId
    workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }]
    zoneRedundant: false
    enableTelemetry: false
  }
}

module api 'br/public:avm/ptn/azd/acr-container-app:0.5.0' = {
  name: 'api-app'
  params: {
    name: apiName
    imageName: apiImageName
    location: location
    tags: union(tags, { 'azd-service-name': 'api' })
    containerAppsEnvironmentName: stack.outputs.environmentName
    identityType: 'UserAssigned'
    identityName: apiIdentityName
    userAssignedIdentityResourceId: apiIdentityId
    principalId: apiPrincipalId
    containerRegistryName: stack.outputs.registryName
    external: false
    ingressAllowInsecure: false
    targetPort: 8000
    containerMinReplicas: 1
    containerMaxReplicas: controls.apiMaxReplicas
    containerCpuCoreCount: '0.5'
    containerMemory: '1Gi'
    enableTelemetry: false
    env: [
      { name: 'APP_ENV', value: 'production' }
      { name: 'CONTENT_CATALOG_PATH', value: '/app/data/pilot-catalog.json' }
      { name: 'API_ALLOWED_ORIGINS', value: publicOrigin }
      { name: 'API_ALLOWED_HOSTS', value: 'localhost,127.0.0.1,api,${apiName},${apiName}.internal.${stack.outputs.defaultDomain}' }
      { name: 'FOUNDRY_PROJECT_ENDPOINT', value: foundryProjectEndpoint }
      { name: 'FOUNDRY_AGENTS', value: foundryAgentsJson }
      { name: 'FOUNDRY_GENERAL_AGENT', value: foundryGeneralAgentJson }
      { name: 'FOUNDRY_CONTEXTUAL_AGENT', value: foundryContextualAgentJson }
      { name: 'FOUNDRY_CONVERSATION_AGENT', value: foundryConversationAgentJson }
      { name: 'AI_CONVERSATION_ENABLED', value: aiConversationEnabled }
      { name: 'TASK_ASSISTANCE_ENABLED', value: taskAssistanceEnabled }
      { name: 'AI_CONVERSATION_PRIVACY_REVIEWED', value: aiConversationPrivacyReviewed }
      { name: 'GROUNDED_CONVERSATION_ENABLED', value: 'false' }
      { name: 'LOCAL_EVIDENCE_EVALUATION_ENABLED', value: 'false' }
      { name: 'SYNTHETIC_CONTEXT_ENABLED', value: syntheticContextEnabled }
      { name: 'SYNTHETIC_CONTEXT_SESSION_TTL_SECONDS', value: '1800' }
      { name: 'SYNTHETIC_CONTEXT_CONSENT_TTL_SECONDS', value: '900' }
      { name: 'SYNTHETIC_CONTEXT_AUDIT_MAX_EVENTS', value: '100' }
      { name: 'SYNTHETIC_CONTEXT_AUDIT_MAX_BYTES', value: '65536' }
      { name: 'AZURE_CLIENT_ID', value: apiClientId }
      { name: 'AZURE_SEARCH_ENDPOINT', value: searchEndpoint }
      { name: 'AZURE_SEARCH_INDEX', value: searchIndex }
      { name: 'AZURE_SEARCH_METADATA_ENABLED', value: searchMetadataEnabled }
      { name: 'AZURE_SEARCH_METADATA_REVIEWED', value: searchMetadataReviewed }
      { name: 'AZURE_SEARCH_SEMANTIC_CONFIG', value: 'bc-public-guidance' }
      { name: 'AZURE_SEARCH_VECTOR_ENABLED', value: string(embeddingDimensions > 0) }
      { name: 'AZURE_OPENAI_ENDPOINT', value: modelEndpoint }
      { name: 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT', value: embeddingDeployment }
      { name: 'AZURE_OPENAI_EMBEDDING_DIMENSIONS', value: embeddingDimensions > 0 ? string(embeddingDimensions) : '' }
      { name: 'REDIS_ENDPOINT', value: redisEndpoint }
      { name: 'REDIS_CLIENT_ID', value: apiClientId }
      { name: 'API_CONTROL_NAMESPACE', value: name }
      { name: 'API_AUTH_TENANT_ID', value: tenant().tenantId }
      { name: 'API_AUTH_AUDIENCE', value: apiApplicationClientId }
      { name: 'API_AUTH_CALLERS', value: string([webPrincipalId]) }
      { name: 'API_DAILY_RUN_LIMIT', value: string(controls.runLimit) }
      { name: 'API_DAILY_TOKEN_LIMIT', value: string(controls.tokenLimit) }
      { name: 'API_DAILY_COST_LIMIT_MICROUSD', value: string(controls.costLimitMicrousd) }
      { name: 'API_TOKEN_PRICE_MICROUSD', value: string(controls.tokenPriceMicrousd) }
      { name: 'API_METRICS_ENABLED', value: 'true' }
      { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: insights.outputs.connectionString }
      { name: 'WEBIQ_ENABLED', value: 'false' }
    ]
  }
}

module web 'br/public:avm/ptn/azd/acr-container-app:0.5.0' = {
  name: 'web-app'
  params: {
    name: webName
    imageName: webImageName
    location: location
    tags: union(tags, { 'azd-service-name': 'web' })
    containerAppsEnvironmentName: stack.outputs.environmentName
    identityType: 'UserAssigned'
    identityName: webIdentityName
    userAssignedIdentityResourceId: webIdentityId
    principalId: webPrincipalId
    containerRegistryName: stack.outputs.registryName
    external: true
    ingressAllowInsecure: false
    targetPort: 3000
    containerMinReplicas: 1
    containerMaxReplicas: controls.webMaxReplicas
    containerCpuCoreCount: '0.5'
    containerMemory: '1Gi'
    enableTelemetry: false
    secrets: [{ name: 'client-hash-key', value: clientHashKey }]
    env: [
      { name: 'NODE_ENV', value: 'production' }
      { name: 'NEXT_TELEMETRY_DISABLED', value: '1' }
      { name: 'AI_CONVERSATION_ENABLED', value: aiConversationEnabled }
      { name: 'TASK_ASSISTANCE_ENABLED', value: taskAssistanceEnabled }
      { name: 'GROUNDED_CONVERSATION_ENABLED', value: 'false' }
      { name: 'API_BASE_URL', value: api.outputs.uri }
      { name: 'API_AUTH_SCOPE', value: 'api://${apiApplicationClientId}/.default' }
      { name: 'AZURE_CLIENT_ID', value: webClientId }
      { name: 'FRONT_DOOR_ID', value: frontDoorId }
      { name: 'CLIENT_HASH_KEY', secretRef: 'client-hash-key' }
    ]
  }
}

resource insightsResource 'Microsoft.Insights/components@2020-02-02' existing = {
  name: 'appi-${name}'
}
resource metricAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: insightsResource
  name: guid(insightsResource.id, apiPrincipalId, 'metrics')
  properties: {
    principalId: apiPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '3913510d-42f4-4e42-8a64-420c390055eb')
  }
  dependsOn: [insights]
}

output registryEndpoint string = stack.outputs.registryLoginServer
output registryName string = stack.outputs.registryName
output environmentResourceId string = stack.outputs.environmentResourceId
output apiName string = api.outputs.name
output webName string = web.outputs.name
output apiIdentity string = api.outputs.identityPrincipalId
output webUrl string = web.outputs.uri
output insightsResourceId string = insights.outputs.resourceId
output logsResourceId string = logs.outputs.resourceId

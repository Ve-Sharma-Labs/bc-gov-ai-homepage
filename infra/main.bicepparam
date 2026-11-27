using './main.bicep'

var agents = readEnvironmentVariable('FOUNDRY_AGENTS', '[]')
var stageName = readEnvironmentVariable('AZURE_DEPLOYMENT_STAGE', 'closed')
var validationRanges = readEnvironmentVariable('AZURE_VALIDATION_CIDRS', '[]')
var vectorDimensions = readEnvironmentVariable('AZURE_OPENAI_EMBEDDING_DIMENSIONS', '0')
var azureReleaseCommit = readEnvironmentVariable('AZURE_RELEASE_COMMIT', '')

param environmentName = readEnvironmentVariable('AZURE_ENV_NAME')
param jurisdiction = readEnvironmentVariable('JURISDICTION', 'bc')
param location = readEnvironmentVariable('AZURE_LOCATION')
param deploymentKind = readEnvironmentVariable('AZURE_DEPLOYMENT_KIND', 'pilot')
param sharedFrontDoorProfileName = readEnvironmentVariable('AZURE_SHARED_FRONT_DOOR_PROFILE_NAME', '')
param sharedFrontDoorResourceGroup = readEnvironmentVariable('AZURE_SHARED_FRONT_DOOR_RESOURCE_GROUP', '')
param frontDoorPrivateLinkLocation = readEnvironmentVariable('AZURE_FRONT_DOOR_PRIVATE_LINK_LOCATION', '')
param stagingIdentities = json(readEnvironmentVariable('AZURE_STAGING_IDENTITIES_JSON', '{}'))
param releaseCommit = empty(azureReleaseCommit) ? readEnvironmentVariable('RELEASE_COMMIT', '') : azureReleaseCommit
param releaseId = readEnvironmentVariable('RELEASE_ID', '')
param releaseProbeEnabled = readEnvironmentVariable('AZURE_RELEASE_PROBE_ENABLED', 'false') == 'true'
param modelDeploymentsJson = readEnvironmentVariable('AZURE_MODEL_DEPLOYMENTS')
param foundryAgentsJson = empty(agents) ? '[]' : agents
param foundryGeneralAgentJson = readEnvironmentVariable('FOUNDRY_GENERAL_AGENT', '')
param foundryContextualAgentJson = readEnvironmentVariable('FOUNDRY_CONTEXTUAL_AGENT', '')
param foundryConversationAgentJson = readEnvironmentVariable('FOUNDRY_CONVERSATION_AGENT', '')
param aiConversationEnabled = readEnvironmentVariable('AI_CONVERSATION_ENABLED', 'false')
param taskAssistanceEnabled = readEnvironmentVariable('TASK_ASSISTANCE_ENABLED', 'false')
param aiConversationPrivacyReviewed = readEnvironmentVariable('AI_CONVERSATION_PRIVACY_REVIEWED', 'false')
param syntheticContextEnabled = readEnvironmentVariable('SYNTHETIC_CONTEXT_ENABLED', 'false')
param searchIndex = readEnvironmentVariable('AZURE_SEARCH_INDEX', '${jurisdiction}-pilot-public')
param searchSemanticConfig = readEnvironmentVariable('AZURE_SEARCH_SEMANTIC_CONFIG', '${jurisdiction}-public-guidance')
param searchMetadataEnabled = readEnvironmentVariable('AZURE_SEARCH_METADATA_ENABLED', 'false')
param searchMetadataReviewed = readEnvironmentVariable('AZURE_SEARCH_METADATA_REVIEWED', '0')
param searchSku = readEnvironmentVariable('AZURE_SEARCH_SKU')
param redisSku = readEnvironmentVariable('AZURE_REDIS_SKU')
param apiApplicationClientId = readEnvironmentVariable('AZURE_API_APPLICATION_CLIENT_ID')
param apiImageName = readEnvironmentVariable('AZURE_API_IMAGE_NAME', '')
param webImageName = readEnvironmentVariable('AZURE_WEB_IMAGE_NAME', '')
param controlsJson = readEnvironmentVariable('AZURE_PILOT_CONTROLS')
param stage = empty(stageName) ? 'closed' : stageName
param validationCidrsJson = empty(validationRanges) ? '[]' : validationRanges
param networkPrefix = readEnvironmentVariable('AZURE_NETWORK_PREFIX')
param appsSubnetPrefix = readEnvironmentVariable('AZURE_APPS_SUBNET_PREFIX')
param privateSubnetPrefix = readEnvironmentVariable('AZURE_PRIVATE_SUBNET_PREFIX')
param embeddingDeployment = readEnvironmentVariable('AZURE_OPENAI_EMBEDDING_DEPLOYMENT', '')
param embeddingDimensionsJson = empty(vectorDimensions) ? '0' : vectorDimensions

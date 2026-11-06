using './main.bicep'

var agents = readEnvironmentVariable('FOUNDRY_AGENTS', '[]')
var stageName = readEnvironmentVariable('AZURE_DEPLOYMENT_STAGE', 'closed')
var validationRanges = readEnvironmentVariable('AZURE_VALIDATION_CIDRS', '[]')
var vectorDimensions = readEnvironmentVariable('AZURE_OPENAI_EMBEDDING_DIMENSIONS', '0')

param environmentName = readEnvironmentVariable('AZURE_ENV_NAME')
param location = readEnvironmentVariable('AZURE_LOCATION')
param modelDeploymentsJson = readEnvironmentVariable('AZURE_MODEL_DEPLOYMENTS')
param foundryAgentsJson = empty(agents) ? '[]' : agents
param foundryGeneralAgentJson = readEnvironmentVariable('FOUNDRY_GENERAL_AGENT', '')
param foundryContextualAgentJson = readEnvironmentVariable('FOUNDRY_CONTEXTUAL_AGENT', '')
param foundryConversationAgentJson = readEnvironmentVariable('FOUNDRY_CONVERSATION_AGENT', '')
param aiConversationEnabled = readEnvironmentVariable('AI_CONVERSATION_ENABLED', 'false')
param taskAssistanceEnabled = readEnvironmentVariable('TASK_ASSISTANCE_ENABLED', 'false')
param aiConversationPrivacyReviewed = readEnvironmentVariable('AI_CONVERSATION_PRIVACY_REVIEWED', 'false')
param syntheticContextEnabled = readEnvironmentVariable('SYNTHETIC_CONTEXT_ENABLED', 'false')
param searchIndex = readEnvironmentVariable('AZURE_SEARCH_INDEX', 'bc-pilot-public')
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

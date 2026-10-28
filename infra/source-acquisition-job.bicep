targetScope = 'resourceGroup'

@description('Existing replacement acquisition job name.')
@minLength(3)
@maxLength(32)
param acquisitionJobName string
param location string
param environmentName string
param registryName string
param acquisitionIdentityName string
param storageAccountName string
@description('Reviewed Linux amd64 acquisition image pinned by registry digest.')
param imageName string
param tags object = {}
param candidateContainerName string = 'bc-ingestion-candidates'
param runPrefix string
param acquisitionEnabled bool
param rightsContainerName string = 'bc-ingestion-rights'
param rightsBlob string
param rightsSha256 string = ''
@minValue(1)
param requestBudget int = 50000
@minValue(1)
param byteBudget int = 10000000000
@minValue(1)
param maxCandidates int = 100000

resource containerEnvironment 'Microsoft.App/managedEnvironments@2025-01-01' existing = {
  name: environmentName
}
resource registry 'Microsoft.ContainerRegistry/registries@2025-04-01' existing = {
  name: registryName
}
resource acquisitionIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = {
  name: acquisitionIdentityName
}
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

var accountUrl = 'https://${storage.name}.blob.${environment().suffixes.storage}'
var commonArgs = [
  'programme'
  '--catalog'
  '/app/data/pilot-catalog.json'
  '--programme'
  '/app/data/source-programme.json'
  '--programme-store'
  'azure-blob'
  '--blob-account-url'
  accountUrl
  '--candidate-container'
  candidateContainerName
  '--run-prefix'
  runPrefix
  '--credential'
  'managed-identity'
]
var runArgs = acquisitionEnabled ? [
  '--acquire'
  '--resume'
  '--rights-container'
  rightsContainerName
  '--rights-blob'
  rightsBlob
  '--rights-sha256'
  rightsSha256
  '--batch-requests'
  '25'
  '--run-seconds'
  '120'
] : [
  '--initialize'
  '--request-budget'
  string(requestBudget)
  '--byte-budget'
  string(byteBudget)
  '--max-candidates'
  string(maxCandidates)
  '--max-retries'
  '2'
]

resource acquisitionJob 'Microsoft.App/jobs@2025-01-01' = {
  name: acquisitionJobName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned, UserAssigned'
    userAssignedIdentities: { '${acquisitionIdentity.id}': {} }
  }
  properties: {
    environmentId: containerEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 300
      replicaRetryLimit: 0
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      registries: [{ server: registry.properties.loginServer, identity: 'system' }]
    }
    template: {
      containers: [
        {
          name: 'acquisition'
          image: imageName
          command: ['python', '-m', 'bc_ingestion']
          args: concat(commonArgs, runArgs)
          env: [{ name: 'AZURE_CLIENT_ID', value: acquisitionIdentity.properties.clientId }]
          resources: { cpu: json('0.5'), memory: '1Gi' }
        }
      ]
    }
  }
}

output jobName string = acquisitionJob.name
output jobArguments array = concat(commonArgs, runArgs)
output acquisitionIdentityClientId string = acquisitionIdentity.properties.clientId

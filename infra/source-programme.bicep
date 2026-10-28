targetScope = 'resourceGroup'

@description('Existing pilot prefix, without creating a replacement environment.')
@minLength(3)
@maxLength(20)
param name string
param location string
param storageAccountName string
param environmentName string
param virtualNetworkName string
param registryName string
param publisherIdentityName string
@description('Reviewed Linux amd64 image pinned by registry digest.')
param imageName string
@description('Existing publisher validation image pinned independently so acquisition-only deployments do not alter it.')
param publicationImageName string = imageName
@description('Manual acquisition job name. Override only to replace a failed job resource without deleting it.')
@minLength(3)
@maxLength(32)
param acquisitionJobName string = 'job-${name}-ingest'
param tags object = {}
param privateSubnetName string = 'private-endpoints'
param candidateContainerName string = 'bc-ingestion-candidates'
param rightsContainerName string = 'bc-ingestion-rights'
param runPrefix string = 'bc-full-v1'
@description('False provisions a manual initialization job. Actual acquisition needs reviewed rights.')
param acquisitionEnabled bool = false
param rightsBlob string = 'reviews/bc-full-v1.json'
param rightsSha256 string = ''
@minValue(1)
param requestBudget int = 50000
@minValue(1)
param byteBudget int = 10000000000
@minValue(1)
param maxCandidates int = 100000

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' existing = {
  parent: storage
  name: 'default'
}
resource candidates 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: candidateContainerName
  properties: { publicAccess: 'None' }
}
resource rights 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: rightsContainerName
  properties: { publicAccess: 'None' }
}
resource network 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: virtualNetworkName
}
resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  parent: network
  name: privateSubnetName
}
resource containerEnvironment 'Microsoft.App/managedEnvironments@2025-01-01' existing = {
  name: environmentName
}
resource registry 'Microsoft.ContainerRegistry/registries@2025-04-01' existing = {
  name: registryName
}
resource publisher 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = {
  name: publisherIdentityName
}
resource acquisitionIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: 'id-${name}-acquisition'
  location: location
  tags: tags
}

resource endpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: 'pe-blob-${name}'
  location: location
  tags: tags
  properties: {
    subnet: { id: subnet.id }
    privateLinkServiceConnections: [
      {
        name: 'blob'
        properties: {
          privateLinkServiceId: storage.id
          groupIds: ['blob']
        }
      }
    ]
  }
}
resource zone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.blob.${environment().suffixes.storage}'
  location: 'global'
  tags: tags
}
resource link 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: zone
  name: 'link-${name}-blob'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: network.id }
  }
}
resource zoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: endpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [{ name: 'blob', properties: { privateDnsZoneId: zone.id } }]
  }
}

var blobContributor = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
var blobReader = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1')
var acrPull = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')

resource candidateAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for role in ['acquisition', 'publication']: {
  scope: candidates
  name: guid(candidates.id, role == 'acquisition' ? acquisitionIdentity.id : publisher.id, blobContributor)
  properties: {
    principalId: role == 'acquisition' ? acquisitionIdentity.properties.principalId : publisher.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: blobContributor
  }
}]
resource rightsReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: rights
  name: guid(rights.id, acquisitionIdentity.id, blobReader)
  properties: {
    principalId: acquisitionIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: blobReader
  }
}
resource rightsPublisher 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: rights
  name: guid(rights.id, publisher.id, blobContributor)
  properties: {
    principalId: publisher.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: blobContributor
  }
}
resource imagePull 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for role in ['acquisition', 'publication']: {
  scope: registry
  name: guid(registry.id, role == 'acquisition' ? acquisitionIdentity.id : publisher.id, 'acrpull')
  properties: {
    principalId: role == 'acquisition' ? acquisitionIdentity.properties.principalId : publisher.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: acrPull
  }
}]

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
  dependsOn: [candidateAccess, rightsReader, imagePull, zoneGroup, link]
}

resource acquisitionSystemImagePull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, acquisitionJobName, 'acrpull-system')
  properties: {
    principalId: acquisitionJob.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: acrPull
  }
}

resource publicationJob 'Microsoft.App/jobs@2025-01-01' = {
  name: 'job-${name}-publish'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${publisher.id}': {} }
  }
  properties: {
    environmentId: containerEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 300
      replicaRetryLimit: 0
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      registries: [{ server: registry.properties.loginServer, identity: publisher.id }]
    }
    template: {
      containers: [
        {
          name: 'publication'
          image: publicationImageName
          command: ['python', '-m', 'bc_ingestion']
          args: ['validate', '--catalog', '/app/data/pilot-catalog.json']
          env: [{ name: 'AZURE_CLIENT_ID', value: publisher.properties.clientId }]
          resources: { cpu: json('0.5'), memory: '1Gi' }
        }
      ]
    }
  }
  dependsOn: [candidateAccess, rightsPublisher, imagePull, zoneGroup, link]
}

output acquisitionJobName string = acquisitionJob.name
output publicationJobName string = publicationJob.name
output acquisitionIdentityClientId string = acquisitionIdentity.properties.clientId
output acquisitionIdentityPrincipalId string = acquisitionIdentity.properties.principalId
output acquisitionSystemIdentityPrincipalId string = acquisitionJob.identity.principalId
output storageUrl string = accountUrl
output candidateContainer string = candidates.name
output rightsContainer string = rights.name
output jobArguments array = concat(commonArgs, runArgs)

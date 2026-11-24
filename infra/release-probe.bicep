targetScope = 'resourceGroup'

@description('Reviewed name for the idle release-readiness job. No app resources are redeployed.')
param name string
param location string
param environmentId string
param webIdentityId string
param webClientId string
param registryHost string
param webImage string
param apiUrl string
param apiAuthScope string
param publicOrigin string
param tags object = {}

resource probe 'Microsoft.App/jobs@2025-01-01' = {
  name: name
  location: location
  tags: union(tags, { project: 'bc-government-assistant', purpose: 'pyrit-private-readiness' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${webIdentityId}': {} }
  }
  properties: {
    environmentId: environmentId
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 120
      replicaRetryLimit: 0
      manualTriggerConfig: { replicaCompletionCount: 1, parallelism: 1 }
      registries: [{ server: registryHost, identity: webIdentityId }]
    }
    template: {
      containers: [{
        name: 'probe'
        image: webImage
        command: ['node', '--input-type=module', '-e', loadTextContent('../scripts/private-release-probe.mjs')]
        env: [
          { name: 'API_BASE_URL', value: apiUrl }
          { name: 'API_AUTH_SCOPE', value: apiAuthScope }
          { name: 'AZURE_CLIENT_ID', value: webClientId }
          { name: 'PUBLIC_ORIGIN', value: publicOrigin }
          { name: 'RELEASE_COMMIT', value: '' }
          { name: 'RELEASE_ID', value: '' }
        ]
        resources: { cpu: json('0.25'), memory: '0.5Gi' }
      }]
    }
  }
}

output probeJobId string = probe.id

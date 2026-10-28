targetScope = 'resourceGroup'

param name string
param location string
param tags object
param sku string
param apiPrincipalId string
param networkId string
param subnetId string

resource cache 'Microsoft.Cache/redisEnterprise@2026-09-01' = {
  name: 'redis-${name}'
  location: location
  tags: tags
  sku: { name: sku }
  properties: {
    highAvailability: 'Enabled'
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Disabled'
  }
}
resource database 'Microsoft.Cache/redisEnterprise/databases@2026-09-01' = {
  parent: cache
  name: 'default'
  properties: {
    clientProtocol: 'Encrypted'
    clusteringPolicy: 'EnterpriseCluster'
    evictionPolicy: 'NoEviction'
    accessKeysAuthentication: 'Disabled'
    persistence: { aofEnabled: false, rdbEnabled: false }
    port: 10000
  }
}
resource access 'Microsoft.Cache/redisEnterprise/databases/accessPolicyAssignments@2026-09-01' = {
  parent: database
  name: 'api'
  properties: {
    accessPolicyName: 'default'
    user: { objectId: apiPrincipalId }
  }
}
resource privateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: 'pe-${cache.name}'
  location: location
  tags: tags
  properties: {
    subnet: { id: subnetId }
    privateLinkServiceConnections: [
      {
        name: 'redis'
        properties: {
          privateLinkServiceId: cache.id
          groupIds: ['redisEnterprise']
        }
      }
    ]
  }
}
resource zone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.redis.azure.net'
  location: 'global'
}
resource link 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: zone
  name: name
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: networkId }
  }
}
resource dns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: privateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [{ name: 'redis', properties: { privateDnsZoneId: zone.id } }]
  }
}

output endpoint string = 'rediss://${cache.properties.hostName}:10000'

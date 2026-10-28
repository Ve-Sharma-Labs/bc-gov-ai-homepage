targetScope = 'resourceGroup'

param name string
param location string
param tags object
param addressPrefix string
param appsSubnetPrefix string
param privateSubnetPrefix string

resource network 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: 'vnet-${name}'
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: [addressPrefix] }
    subnets: [
      {
        name: 'apps'
        properties: {
          addressPrefix: appsSubnetPrefix
          delegations: [
            {
              name: 'container-apps'
              properties: { serviceName: 'Microsoft.App/environments' }
            }
          ]
        }
      }
      {
        name: 'private-endpoints'
        properties: {
          addressPrefix: privateSubnetPrefix
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
    ]
  }
}

output networkId string = network.id
output appsSubnetId string = '${network.id}/subnets/apps'
output privateSubnetId string = '${network.id}/subnets/private-endpoints'

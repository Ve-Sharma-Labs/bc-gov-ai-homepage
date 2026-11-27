targetScope = 'resourceGroup'

@description('Location of the existing Saskatchewan virtual network.')
param location string = resourceGroup().location

var tags = {
  project: 'sk-government-assistant'
  jurisdiction: 'sk'
  classification: 'pilot'
}

resource search 'Microsoft.Search/searchServices@2024-06-01-preview' existing = {
  name: 'srch-skassist-rywtikimq4'
}
resource network 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: 'vnet-skassist-rywtikimq4'
}
resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  parent: network
  name: 'private-endpoints'
}
resource endpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: 'pe-srch-skassist-rywtikimq4'
  location: location
  tags: tags
  properties: {
    subnet: { id: subnet.id }
    privateLinkServiceConnections: [{
      name: 'search'
      properties: {
        privateLinkServiceId: search.id
        groupIds: ['searchService']
      }
    }]
  }
}
resource zone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.search.windows.net'
  location: 'global'
}
resource link 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: zone
  name: 'skassist-rywtikimq4'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: network.id }
  }
}
resource dns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: endpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [{ name: 'search', properties: { privateDnsZoneId: zone.id } }]
  }
}

targetScope = 'resourceGroup'

param name string
param location string
param tags object

var roles = ['api', 'web', 'publisher']
resource identities 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = [for role in roles: {
  name: 'id-${name}-${role}'
  location: location
  tags: tags
}]

output identities array = [for (role, index) in roles: {
  role: role
  id: identities[index].id
  principalId: identities[index].properties.principalId
  clientId: identities[index].properties.clientId
}]

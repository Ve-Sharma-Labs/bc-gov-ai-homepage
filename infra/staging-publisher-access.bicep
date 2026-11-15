targetScope = 'resourceGroup'

param searchServiceName string
@description('Verified object ID of the accountable human publisher; this grants only document access on the staging Search service.')
param publisherPrincipalId string

resource search 'Microsoft.Search/searchServices@2025-05-01' existing = {
  name: searchServiceName
}
var role = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '8ebe5a00-799e-43f5-93ac-243d3dce84a7')
resource access 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, publisherPrincipalId, role)
  properties: {
    principalId: publisherPrincipalId
    principalType: 'User'
    roleDefinitionId: role
  }
}

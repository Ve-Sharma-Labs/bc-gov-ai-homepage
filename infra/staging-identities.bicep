targetScope = 'subscription'

@minLength(1)
@maxLength(40)
param environmentName string
param location string

var suffix = take(uniqueString(subscription().id, environmentName, location), 10)
var name = 'bcassist-${suffix}'
var tags = {
  'azd-env-name': environmentName
  project: 'bc-government-assistant'
  classification: 'staging'
}

resource group 'Microsoft.Resources/resourceGroups@2025-04-01' = {
  name: 'rg-${name}'
  location: location
  tags: tags
}

module identities './modules/staging-identities.bicep' = {
  name: 'staging-identities'
  scope: group
  params: {
    name: name
    location: location
    tags: tags
  }
}

output resourceGroupName string = group.name
output identities array = identities.outputs.identities

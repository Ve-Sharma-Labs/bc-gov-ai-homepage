targetScope = 'resourceGroup'

@description('Validation-only snapshots of existing applications. Actual rollout PATCHes only properties.template.')
@secure()
param snapshot object

resource apps 'Microsoft.App/containerApps@2025-01-01' = [for app in snapshot.applications: {
  name: app.name
  location: app.location
  tags: app.tags
  identity: app.identity
  properties: {
    environmentId: app.properties.environmentId
    workloadProfileName: app.properties.workloadProfileName
    configuration: app.properties.configuration
    template: app.properties.template
  }
}]

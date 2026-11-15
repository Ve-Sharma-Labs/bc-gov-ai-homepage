targetScope = 'resourceGroup'

@description('Validation-only GET snapshots without resolved secret values. Actual rollout PATCHes only properties.template.')
param snapshot object

resource apps 'Microsoft.App/containerApps@2025-01-01' = [for app in snapshot.applications: {
  name: app.name
  location: app.location
  tags: app.tags
  identity: app.identity
  properties: {
    environmentId: app.properties.environmentId
    workloadProfileName: app.properties.workloadProfileName
    // GET redacts secret values. Validate references here; only the template PATCH is deployed.
    configuration: toObject(
      filter(items(app.properties.configuration), property => property.key != 'secrets'),
      property => property.key,
      property => property.value
    )
    template: app.properties.template
  }
}]

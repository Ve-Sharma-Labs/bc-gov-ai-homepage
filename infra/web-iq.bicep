targetScope = 'resourceGroup'

@description('Explicitly approved, globally unique Web IQ metering-account name.')
@minLength(3)
@maxLength(64)
param accountName string

resource account 'Microsoft.WebIQ/accounts@2026-06-01-preview' = {
  name: accountName
  location: 'global'
  kind: 'WebIQ.Grounding'
  sku: {
    name: 'G3'
  }
  tags: {
    project: 'bc-government-assistant'
    classification: 'pilot'
  }
  properties: {
    // This setting is not Zero Query Logging or an AppID access grant.
    statisticsEnabled: false
  }
}

output resourceId string = account.id

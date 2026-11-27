targetScope = 'resourceGroup'

param workspaceName string
param applicationInsightsName string
@minLength(1)
param actionGroupId string
param location string = resourceGroup().location
param requirePartialLossMetrics bool = true

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: workspaceName
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: applicationInsightsName
}

resource sourceHealthAlert 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = {
  name: 'sk-source-health'
  location: location
  kind: 'LogAlert'
  properties: {
    displayName: 'Saskatchewan source health'
    description: 'Source evidence is expiring within 72 hours, unhealthy, or source telemetry is missing.'
    enabled: true
    severity: 2
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    autoMitigate: true
    skipQueryValidation: false
    scopes: [
      workspace.id
    ]
    actions: {
      actionGroups: [
        actionGroupId
      ]
    }
    criteria: {
      allOf: [
        {
          query: replace(replace('''
AppMetrics
| where TimeGenerated > ago(15m)
| where _ResourceId =~ 'APP_INSIGHTS_RESOURCE_ID'
| where AppRoleName == 'skassist-rywtikimq4.bc-service-assistant'
| where Name in ('bc.sources.checks', 'bc.sources.usable_documents', 'bc.sources.expired_documents', 'bc.sources.missing_sources', 'bc.sources.hours_to_expiry')
| summarize checks=countif(Name == 'bc.sources.checks'), badChecks=countif(Name == 'bc.sources.checks' and tostring(Properties.status) != 'ready'), documents=countif(Name == 'bc.sources.usable_documents'), usableMin=minif(Min, Name == 'bc.sources.usable_documents'), expiredReports=countif(Name == 'bc.sources.expired_documents'), expiredMax=maxif(Max, Name == 'bc.sources.expired_documents'), missingReports=countif(Name == 'bc.sources.missing_sources'), missingMax=maxif(Max, Name == 'bc.sources.missing_sources'), expiries=countif(Name == 'bc.sources.hours_to_expiry'), expiryMin=minif(Min, Name == 'bc.sources.hours_to_expiry')
| where checks == 0 or badChecks > 0 or documents == 0 or usableMin <= 0 or (REQUIRE_PARTIAL_LOSS_METRICS and (expiredReports == 0 or missingReports == 0)) or expiredMax > 0 or missingMax > 0 or expiries == 0 or expiryMin <= 72
''', 'APP_INSIGHTS_RESOURCE_ID', toLower(applicationInsights.id)), 'REQUIRE_PARTIAL_LOSS_METRICS', string(requirePartialLossMetrics))
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
  }
}

targetScope = 'resourceGroup'

param location string = 'swedencentral'
param accountName string = 'ai-opinion-${uniqueString(resourceGroup().id)}'
param projectName string = 'opinion-voice'
param modelName string = 'gpt-5.1'
param modelVersion string = '2025-11-13'
param deploymentName string = 'gpt-5.1'
@allowed([
  'Standard'
  'DataZoneStandard'
])
param deploymentSku string = 'Standard'
@minValue(1)
param capacity int = 100
param operatorObjectId string

var tags = {
  application: 'opinion-voice-poc'
  environment: 'demo'
}

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  tags: tags
  properties: {
    allowProjectManagement: true
    customSubDomainName: accountName
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  // Both child operations update the account; parallel creation can return RequestConflict.
  dependsOn: [deployment]
  name: projectName
  location: location
  identity: { type: 'SystemAssigned' }
  tags: tags
  properties: {
    displayName: 'Opinion Voice PoC'
    description: 'Synthetic German opinion-forming voice demo'
  }
}

resource deployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: deploymentName
  sku: { name: deploymentSku, capacity: capacity }
  properties: {
    model: { format: 'OpenAI', name: modelName, version: modelVersion }
    versionUpgradeOption: 'OnceCurrentVersionExpired'
  }
}

var aiUserRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d')
var speechUserRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'a97b65f3-24c7-4388-baec-2e87135dc908')

resource operatorAi 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(account.id, operatorObjectId, aiUserRole)
  scope: account
  properties: {
    principalId: operatorObjectId
    principalType: 'User'
    roleDefinitionId: aiUserRole
  }
}

resource operatorSpeech 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(account.id, operatorObjectId, speechUserRole)
  scope: account
  properties: {
    principalId: operatorObjectId
    principalType: 'User'
    roleDefinitionId: speechUserRole
  }
}

output projectEndpoint string = 'https://${account.name}.services.ai.azure.com/api/projects/${project.name}'
output voiceEndpoint string = 'https://${account.name}.services.ai.azure.com'
output modelDeployment string = deployment.name
output accountId string = account.id
output projectId string = project.id

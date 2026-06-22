@description('Location for all resources.')
param location string = resourceGroup().location

@description('Base name used to derive resource names.')
param appName string = 'afsandbox'

@description('Container image reference, e.g. <acr>.azurecr.io/agent-sandbox:latest. Pushed before deploying.')
param containerImage string

@description('Name of the Azure Container Registry that holds the image.')
param acrName string

@description('Existing Azure OpenAI account name (assumed in this resource group).')
param aoaiName string

@description('Azure OpenAI chat model deployment name.')
param aoaiDeployment string

@description('Azure OpenAI API version.')
param aoaiApiVersion string = '2024-10-21'

@description('Name of the ACA sandbox group used for per-session isolation (provision with scripts/setup_sandbox.py).')
param sandboxGroupName string

@description('Region used when talking to the ACA Sandbox endpoint.')
param sandboxRegion string = location

var logAnalyticsName = '${appName}-logs'
var environmentName = '${appName}-env'
var containerAppName = '${appName}-app'

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' existing = {
  name: acrName
}

resource aoai 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: aoaiName
}

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: containerAppName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
      }
      registries: [
        {
          server: acr.properties.loginServer
          identity: 'system'
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'agent'
          image: containerImage
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          env: [
            { name: 'AZURE_OPENAI_ENDPOINT', value: 'https://${aoaiName}.openai.azure.com/' }
            { name: 'AZURE_OPENAI_DEPLOYMENT', value: aoaiDeployment }
            { name: 'AZURE_OPENAI_API_VERSION', value: aoaiApiVersion }
            { name: 'AZURE_SUBSCRIPTION_ID', value: subscription().subscriptionId }
            { name: 'AZURE_RESOURCE_GROUP', value: resourceGroup().name }
            { name: 'AZURE_SANDBOX_GROUP', value: sandboxGroupName }
            { name: 'AZURE_REGION', value: sandboxRegion }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
}

// AcrPull so the app's managed identity can pull the image.
var acrPullRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, containerApp.id, 'acrpull')
  scope: acr
  properties: {
    roleDefinitionId: acrPullRoleId
    principalId: containerApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Cognitive Services OpenAI User so the app can call the model with managed identity.
var aoaiUserRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
resource aoaiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aoai.id, containerApp.id, 'aoai-user')
  scope: aoai
  properties: {
    roleDefinitionId: aoaiUserRoleId
    principalId: containerApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

@description('Container App URL.')
output appUrl string = 'https://${containerApp.properties.configuration.ingress.fqdn}'

@description('Managed identity principal id. Grant it Container Apps SandboxGroup Data Owner with scripts/setup_sandbox.py.')
output principalId string = containerApp.identity.principalId

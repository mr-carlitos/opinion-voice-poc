#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
subscription="${AZURE_SUBSCRIPTION_ID:-87d501de-bf17-4c3e-b4d8-42a5607d7b7c}"
region="${AZURE_LOCATION:-swedencentral}"
group="${AZURE_RESOURCE_GROUP:-rg-opinion-voice-poc}"
model="gpt-4.1-mini"
version="2025-04-14"
sku="GlobalStandard"
capacity=20

az account show --query '{subscription:name,tenant:tenantId,user:user.name}' -o json
az cognitiveservices model list --location "$region" --subscription "$subscription" \
  --query "[?model.name=='$model' && model.version=='$version'].model.skus[].name" -o tsv
available=$(az cognitiveservices usage list --location "$region" --subscription "$subscription" \
  --query "[?name.value=='OpenAI.$sku.$model'].[limit,currentValue] | [0]" -o tsv)
read -r limit used <<< "$(printf '%s' "$available" | tr '\n' ' ')"
if [[ -z "${limit:-}" || -z "${used:-}" ]] || (( limit - used < capacity )); then
  printf 'Insufficient or unknown quota. No resources created.\n' >&2
  exit 1
fi
if [[ "${1:-}" != "--apply" ]]; then
  printf 'Preflight complete. Run with --apply to create the approved resources.\n'
  exit 0
fi
operator=$(az ad signed-in-user show --query id -o tsv)
az group create --subscription "$subscription" --name "$group" --location "$region" \
  --tags application=opinion-voice-poc environment=demo --output none
az deployment group create --subscription "$subscription" --resource-group "$group" \
  --name opinion-voice-poc --template-file infra/main.bicep \
  --parameters location="$region" operatorObjectId="$operator" modelName="$model" \
    modelVersion="$version" deploymentSku="$sku" capacity="$capacity" \
  --query properties.outputs -o json
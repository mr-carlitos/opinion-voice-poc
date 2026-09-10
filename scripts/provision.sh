#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
subscription="${AZURE_SUBSCRIPTION_ID:-87d501de-bf17-4c3e-b4d8-42a5607d7b7c}"
region="${AZURE_LOCATION:-swedencentral}"
group="${AZURE_RESOURCE_GROUP:-rg-opinion-voice-poc}"
model="${FOUNDRY_MODEL_NAME:-gpt-5.1}"
version="${FOUNDRY_MODEL_VERSION:-2025-11-13}"
deployment="${FOUNDRY_MODEL_DEPLOYMENT_NAME:-gpt-5.1}"
sku="${FOUNDRY_DEPLOYMENT_SKU:-Standard}"
capacity="${FOUNDRY_DEPLOYMENT_CAPACITY:-100}"

if (( $# > 1 )) || [[ "${1:-}" != "" && "${1:-}" != "--apply" ]]; then
  printf 'Usage: bash scripts/provision.sh [--apply]\n' >&2
  exit 1
fi
if [[ "$sku" != "Standard" && "$sku" != "DataZoneStandard" ]]; then
  printf 'Only Standard or DataZoneStandard deployments are approved; no global fallback.\n' >&2
  exit 1
fi
if [[ ! "$capacity" =~ ^[1-9][0-9]*$ ]] || [[ ! "$model" =~ ^[A-Za-z0-9_.-]+$ ]] \
  || [[ ! "$version" =~ ^[A-Za-z0-9_.-]+$ ]] || [[ ! "$deployment" =~ ^[A-Za-z0-9_.-]+$ ]]; then
  printf 'Invalid model, version, deployment name or capacity.\n' >&2
  exit 1
fi
az account show --subscription "$subscription" \
  --query '{subscription:name,tenant:tenantId,user:user.name}' -o json
az account get-access-token --subscription "$subscription" --output none
usage_name=$(az cognitiveservices model list --location "$region" --subscription "$subscription" \
  --query "[?kind=='AIServices' && model.name=='$model' && model.version=='$version'].model.skus[] | [?name=='$sku' && !ends_with(usageName, '-finetune')].usageName" -o tsv | sort -u)
if [[ ! "$usage_name" =~ ^[A-Za-z0-9_.-]+$ ]]; then
  printf 'Model/SKU quota key is missing or ambiguous. No resources created.\n' >&2
  exit 1
fi
available=$(az cognitiveservices usage list --location "$region" --subscription "$subscription" \
  --query "[?name.value=='$usage_name'].{limit:limit,used:currentValue}" -o json)
printf '%s' "$available" | python3 -c '
import json, math, sys
rows = json.load(sys.stdin)
capacity = int(sys.argv[1])
if len(rows) != 1:
    sys.exit("Quota is missing or ambiguous. No resources created.")
limit, used = rows[0].get("limit"), rows[0].get("used")
if not all(type(n) in (int, float) and math.isfinite(n) and n >= 0 for n in (limit, used)):
    sys.exit("Invalid quota values. No resources created.")
if limit - used < capacity:
    sys.exit(f"Insufficient quota: available {limit - used:g}, required {capacity}. No resources created.")
print(f"Quota {sys.argv[2]}: available {limit - used:g}, requested {capacity}.")
' "$capacity" "$usage_name"
if [[ "${1:-}" != "--apply" ]]; then
  printf 'Preflight complete. Run with --apply to create the approved resources.\n'
  exit 0
fi
operator=$(az ad signed-in-user show --query id -o tsv)
az group create --subscription "$subscription" --name "$group" --location "$region" \
  --tags application=opinion-voice-poc environment=demo --output none
az deployment group validate --subscription "$subscription" --resource-group "$group" \
  --template-file infra/main.bicep \
  --parameters location="$region" operatorObjectId="$operator" modelName="$model" \
    modelVersion="$version" deploymentName="$deployment" deploymentSku="$sku" \
    capacity="$capacity" --output none
az deployment group create --subscription "$subscription" --resource-group "$group" \
  --name opinion-voice-poc --template-file infra/main.bicep \
  --parameters location="$region" operatorObjectId="$operator" modelName="$model" \
    modelVersion="$version" deploymentName="$deployment" deploymentSku="$sku" capacity="$capacity" \
  --query properties.outputs -o json
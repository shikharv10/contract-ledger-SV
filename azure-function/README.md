# Azure Function for SCITT Blob Storage Backend

This Azure Function provides an HTTP endpoint for submitting contracts to blob storage with atomic sequence number assignment.

## Features

- **Atomic sequence numbering**: Uses Azure Blob Lease for distributed locking
- **Concurrent-safe**: Multiple simultaneous submissions get unique sequence numbers
- **Auto-retry**: Built-in retry logic with exponential backoff
- **Container auto-creation**: Automatically creates the blob container if needed

## Architecture

```
Client (Python CLI)
    ↓
    POST /api/submit (contract.cose)
    ↓
Azure Function
    ↓
    1. Acquire lease on _sequence_counter.txt
    2. Read current counter (e.g., 14)
    3. Increment to 15
    4. Write back 15
    5. Release lease
    6. Upload contract as 2.15.cose
    ↓
    Return {"entryId": "2.15"}
```

## Prerequisites

- Azure subscription
- Azure CLI installed (`az` command)
- Azure Functions Core Tools (`func` command)

## Deployment Steps

### 1. Create Azure Resources

```bash
# Variables
RESOURCE_GROUP="scitt-blob-rg"
LOCATION="eastus"
STORAGE_ACCOUNT="scittblobstorage"  # Must be globally unique
FUNCTION_APP="scitt-blob-function"  # Must be globally unique

# Login to Azure
az login

# Create resource group
az group create --name $RESOURCE_GROUP --location $LOCATION

# Create storage account
az storage account create \
    --name $STORAGE_ACCOUNT \
    --resource-group $RESOURCE_GROUP \
    --location $LOCATION \
    --sku Standard_LRS

# Create function app (Linux, Python 3.11)
az functionapp create \
    --name $FUNCTION_APP \
    --resource-group $RESOURCE_GROUP \
    --storage-account $STORAGE_ACCOUNT \
    --runtime python \
    --runtime-version 3.11 \
    --functions-version 4 \
    --os-type Linux \
    --consumption-plan-location $LOCATION
```

### 2. Configure Environment Variables

```bash
# Get storage connection string
CONNECTION_STRING=$(az storage account show-connection-string \
    --name $STORAGE_ACCOUNT \
    --resource-group $RESOURCE_GROUP \
    --query connectionString \
    --output tsv)

# Set environment variables in function app
az functionapp config appsettings set \
    --name $FUNCTION_APP \
    --resource-group $RESOURCE_GROUP \
    --settings \
        "AZURE_STORAGE_CONNECTION_STRING=$CONNECTION_STRING" \
        "BLOB_CONTAINER_NAME=contracts"
```

### 3. Deploy Function Code

```bash
# Navigate to the azure-function directory
cd azure-function

# Deploy the function
func azure functionapp publish $FUNCTION_APP
```

### 4. Verify Deployment

```bash
# Get function app URL
FUNCTION_URL=$(az functionapp show \
    --name $FUNCTION_APP \
    --resource-group $RESOURCE_GROUP \
    --query defaultHostName \
    --output tsv)

echo "Function URL: https://$FUNCTION_URL"

# Test health endpoint
curl https://$FUNCTION_URL/api/health
```

## Environment Variables for Python CLI

After deploying the Azure Function, configure your Python CLI:

```bash
export PYSCITT_BACKEND=blob
export PYSCITT_BLOB_SERVICE_URL=https://<your-function-app>.azurewebsites.net
export PYSCITT_BLOB_ACCOUNT=<your-storage-account>
export PYSCITT_BLOB_KEY=<your-storage-account-key>
export PYSCITT_BLOB_CONTAINER=contracts
```

To get the storage account key:

```bash
az storage account keys list \
    --account-name $STORAGE_ACCOUNT \
    --resource-group $RESOURCE_GROUP \
    --query '[0].value' \
    --output tsv
```

## API Endpoints

### POST /api/submit

Submit a contract and get a sequence number.

**Request:**
```
POST /api/submit
Content-Type: application/cose
Body: [COSE contract binary data]
```

**Response:**
```json
{
  "entryId": "2.15",
  "sequenceNumber": 15,
  "timestamp": 1730304000
}
```

### GET /api/health

Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "container": "contracts"
}
```

## Testing

### Test 1: Submit a Contract

```bash
# Using the Python CLI
export PYSCITT_BACKEND=blob
export PYSCITT_BLOB_SERVICE_URL=https://scitt-blob-function.azurewebsites.net

scitt submit-contract contract.cose --receipt receipt.json
# Output: Submitted contract.cose to blob storage as contract 2.1
```

### Test 2: Concurrent Submissions

```bash
# Submit 5 contracts simultaneously to test atomic counter
for i in {1..5}; do
    (scitt submit-contract contract$i.cose && echo "Success: $i") &
done
wait

# Verify all got unique sequence numbers (no duplicates)
```

### Test 3: Retrieve Contract

```bash
scitt retrieve-contracts ./output --contract-id 2.1
# Should download 2.1.cose and 2.1.json
```

## Monitoring

View logs in Azure Portal:
1. Go to your Function App
2. Click "Functions" → "submit"
3. Click "Monitor"
4. View invocation logs

Or use Azure CLI:

```bash
func azure functionapp logstream $FUNCTION_APP
```

## Blob Storage Structure

After submissions, your blob storage will look like:

```
Container: contracts/
├── _sequence_counter.txt    # Contains: "3" (next available sequence)
├── 2.1.cose                 # First contract
├── 2.2.cose                 # Second contract (co-signed)
├── 2.3.cose                 # Third contract
└── ...
```

## Cost Estimate

- **Azure Functions**: ~$0.00 (generous free tier)
- **Blob Storage**: ~$0.01/month (first 5GB free)
- **Total**: **~$0.01/month** (vs $1000-2000/month for CCF)

## Troubleshooting

### "Failed to acquire sequence counter lock"

- **Cause**: Another request is holding the lease
- **Solution**: Automatic retry (up to 3 attempts). If persistent, check for hung leases.

### "Container not found"

- **Cause**: Container doesn't exist and auto-creation failed
- **Solution**: Manually create container:
  ```bash
  az storage container create \
      --name contracts \
      --account-name $STORAGE_ACCOUNT
  ```

### "AZURE_STORAGE_CONNECTION_STRING not set"

- **Cause**: Environment variable not configured in function app
- **Solution**: See step 2 in deployment instructions

## Security Notes

- **For training/demos only**: This is NOT production-ready
- **No authentication**: Endpoint is publicly accessible
- **No receipts**: No cryptographic guarantees like CCF
- **No verification**: Trust the blob storage, not cryptography

For production, use CCF with proper authentication and cryptographic receipts.

## Clean Up

To delete all resources:

```bash
az group delete --name $RESOURCE_GROUP --yes --no-wait
```

# Azure Blob Storage Backend Testing Guide

## Overview
This guide provides step-by-step instructions for testing the Azure Blob Storage backend for the SCITT contract ledger. Follow this guide with Claude.ai assistance to verify the implementation.

**Prerequisites:**
- VM with Linux (Ubuntu/Debian recommended)
- Azure Storage Account created
- Azure Function deployment capability
- Python 3.8+

---

## Testing Phases

### Phase 1: Environment Setup
### Phase 2: Azure Function Deployment
### Phase 3: Basic Submission Testing
### Phase 4: TDP Workflow Testing
### Phase 5: Co-Signing (TDC) Testing
### Phase 6: Integration Verification

---

## Phase 1: Environment Setup

### Step 1.1: Clone Repository

```bash
# On your VM
cd ~
git clone https://github.com/shikharv10/contract-ledger-SV.git
cd contract-ledger-SV
git checkout claude/add-azure-blob-storage-backend-011CUdYGpUNqRCuUUM8FQHwu
```

**Expected:** Repository cloned, branch checked out successfully.

**Ask Claude.ai:** "I've cloned the repository. What should I check to verify it's the right branch?"

### Step 1.2: Install Python Dependencies

```bash
cd pyscitt
pip install -e .
pip install httpx loguru azure-storage-blob azure-functions
```

**Expected:** All packages install without errors.

**Verification:**
```bash
scitt --help
```

**Expected Output:** Help text showing available commands.

**If errors:** Ask Claude.ai "I got this error during pip install: [paste error]. How do I fix it?"

### Step 1.3: Gather Azure Storage Credentials

**You need:**
1. Storage Account Name
2. Storage Account Key
3. Container Name (default: `contracts`)

**Find these:**
```bash
# In Azure Portal or CLI
az storage account show --name <your-storage-account> --query name
az storage account keys list --account-name <your-storage-account> --query [0].value
```

**Store these values** - you'll use them throughout testing.

**Ask Claude.ai:** "I have my Azure Storage credentials. What environment variables should I set?"

### Step 1.4: Set Environment Variables

```bash
# Add to ~/.bashrc or run in terminal
export PYSCITT_BACKEND=blob
export PYSCITT_BLOB_ACCOUNT=<your-storage-account-name>
export PYSCITT_BLOB_KEY=<your-storage-account-key>
export PYSCITT_BLOB_CONTAINER=contracts

# Reload
source ~/.bashrc
```

**Verification:**
```bash
echo $PYSCITT_BACKEND
echo $PYSCITT_BLOB_ACCOUNT
```

**Expected:** Values are set correctly.

---

## Phase 2: Azure Function Deployment

### Step 2.1: Install Azure Functions Core Tools

```bash
# For Ubuntu/Debian
curl https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > microsoft.gpg
sudo mv microsoft.gpg /etc/apt/trusted.gpg.d/microsoft.gpg
sudo sh -c 'echo "deb [arch=amd64] https://packages.microsoft.com/repos/microsoft-ubuntu-$(lsb_release -cs)-prod $(lsb_release -cs) main" > /etc/apt/sources.list.d/dotnetdev.list'
sudo apt-get update
sudo apt-get install azure-functions-core-tools-4
```

**Verification:**
```bash
func --version
```

**Expected:** Version 4.x.x displayed.

**Ask Claude.ai:** "I'm having trouble installing Azure Functions Core Tools on [your OS]. What's the right command?"

### Step 2.2: Configure Azure Function

```bash
cd ~/contract-ledger-SV/azure-function

# Create local.settings.json
cat > local.settings.json <<EOF
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "AZURE_STORAGE_CONNECTION_STRING": "DefaultEndpointsProtocol=https;AccountName=<your-account-name>;AccountKey=<your-account-key>;EndpointSuffix=core.windows.net",
    "BLOB_CONTAINER_NAME": "contracts"
  }
}
EOF
```

**Replace:**
- `<your-account-name>` with your storage account name
- `<your-account-key>` with your storage account key

**Ask Claude.ai:** "How do I construct the Azure Storage connection string from my account name and key?"

### Step 2.3: Test Function Locally

```bash
cd ~/contract-ledger-SV/azure-function
func start
```

**Expected Output:**
```
Functions:
        get_parameters: [GET] http://localhost:7071/api/parameters
        health_check: [GET] http://localhost:7071/api/health
        submit_contract: [POST] http://localhost:7071/api/submit
```

**Test health endpoint:**
```bash
# In another terminal
curl http://localhost:7071/api/health
```

**Expected Response:**
```json
{
  "status": "healthy",
  "container": "contracts"
}
```

**If errors:** Ask Claude.ai "The Azure Function failed to start with this error: [paste error]. What's wrong?"

### Step 2.4: Test Parameters Endpoint

```bash
curl http://localhost:7071/api/parameters
```

**Expected Response:**
```json
{
  "serviceId": "mock-blob-storage-service",
  "treeAlgorithm": "CCF",
  "signatureAlgorithm": "ES256",
  "serviceCertificate": "MIIDbTCCA..."
}
```

**Verification:** Response has all 4 fields with correct camelCase names.

**Ask Claude.ai:** "The parameters endpoint returned this: [paste output]. Is this correct?"

### Step 2.5: Deploy to Azure (Optional)

If you want to deploy to Azure Functions instead of running locally:

```bash
# Login to Azure
az login

# Create Function App
az functionapp create \
  --resource-group <your-rg> \
  --consumption-plan-location <region> \
  --runtime python \
  --runtime-version 3.9 \
  --functions-version 4 \
  --name <unique-function-name> \
  --storage-account <your-storage-account>

# Deploy
cd ~/contract-ledger-SV/azure-function
func azure functionapp publish <unique-function-name>
```

**Set environment variable:**
```bash
export PYSCITT_BLOB_SERVICE_URL=https://<your-function-name>.azurewebsites.net
export CONTRACT_URL=https://<your-function-name>.azurewebsites.net/api
```

**Ask Claude.ai:** "I want to deploy to Azure Functions instead of running locally. What's the full deployment process?"

---

## Phase 3: Basic Submission Testing

### Step 3.1: Set Contract URL

```bash
# If running locally
export CONTRACT_URL=http://localhost:7071/api
export PYSCITT_BLOB_SERVICE_URL=http://localhost:7071

# If deployed to Azure
export CONTRACT_URL=https://<your-function>.azurewebsites.net/api
export PYSCITT_BLOB_SERVICE_URL=https://<your-function>.azurewebsites.net
```

### Step 3.2: Create Test DID

```bash
cd ~/contract-ledger-SV/demo/contract
mkdir -p tmp/test-user

# Generate key
openssl ecparam -name prime256v1 -genkey -noout -out tmp/test-user/key.pem

# Create DID document
cat > tmp/test-user/did.json <<EOF
{
  "id": "did:web:test.example.com",
  "verificationMethod": [{
    "id": "did:web:test.example.com#key-1",
    "type": "JsonWebKey2020",
    "controller": "did:web:test.example.com",
    "publicKeyJwk": {}
  }]
}
EOF
```

**Ask Claude.ai:** "I need to create a test DID and key pair. Can you provide the exact commands?"

### Step 3.3: Create Test Contract

```bash
cd ~/contract-ledger-SV/demo/contract

cat > tmp/test-contract.json <<EOF
{
  "subject": "Test Contract",
  "data": "This is a test contract for blob storage backend",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
```

**Verification:**
```bash
cat tmp/test-contract.json
```

**Expected:** Valid JSON displayed.

### Step 3.4: Sign Contract

```bash
cd ~/contract-ledger-SV

scitt sign-contract \
    --contract demo/contract/tmp/test-contract.json \
    --content-type "application/json" \
    --did-doc demo/contract/tmp/test-user/did.json \
    --key demo/contract/tmp/test-user/key.pem \
    --feed "test-feed" \
    --out demo/contract/tmp/test-contract.cose

echo "Exit code: $?"
```

**Expected Output:**
- File created: `demo/contract/tmp/test-contract.cose`
- Exit code: 0

**Verification:**
```bash
ls -lh demo/contract/tmp/test-contract.cose
file demo/contract/tmp/test-contract.cose
```

**Expected:** Binary file, size > 0 bytes.

**If errors:** Ask Claude.ai "Contract signing failed with: [paste error]. What's wrong with my command?"

### Step 3.5: Submit Contract to Blob Storage

```bash
scitt submit-contract demo/contract/tmp/test-contract.cose \
    --receipt demo/contract/tmp/test-receipt.cbor

echo "Exit code: $?"
```

**Expected Output:**
```
Submitted demo/contract/tmp/test-contract.cose to blob storage as contract 2.1
Created mock receipt at demo/contract/tmp/test-receipt.cbor
NOTE: This is a mock receipt for testing workflow only. Cryptographic verification will fail (expected).
```

**CRITICAL CHECKS:**
1. Contract ID is displayed (e.g., `2.1`)
2. Receipt file is created
3. Warning about mock receipt is shown
4. Exit code is 0

**Ask Claude.ai:** "My submission output shows: [paste output]. What contract ID did I get?"

### Step 3.6: Verify Blob Storage

```bash
# List blobs in container
az storage blob list \
    --account-name $PYSCITT_BLOB_ACCOUNT \
    --account-key $PYSCITT_BLOB_KEY \
    --container-name contracts \
    --output table
```

**Expected Output:**
```
Name                Blob Type    Length
------------------  -----------  --------
2.1.cose           BlockBlob    1234
_sequence_counter.txt  BlockBlob    1
```

**CRITICAL:** Both `2.1.cose` and `_sequence_counter.txt` exist.

**Ask Claude.ai:** "The blob list shows: [paste output]. Is this correct for the first submission?"

### Step 3.7: Check Sequence Counter

```bash
az storage blob download \
    --account-name $PYSCITT_BLOB_ACCOUNT \
    --account-key $PYSCITT_BLOB_KEY \
    --container-name contracts \
    --name _sequence_counter.txt \
    --file /tmp/counter.txt

cat /tmp/counter.txt
```

**Expected Output:** `1`

**Ask Claude.ai:** "The counter file contains: [value]. What should it be after 1 submission?"

### Step 3.8: Submit Second Contract

```bash
# Create another test contract
cat > demo/contract/tmp/test-contract-2.json <<EOF
{
  "subject": "Second Test Contract",
  "data": "Testing sequence increment"
}
EOF

# Sign it
scitt sign-contract \
    --contract demo/contract/tmp/test-contract-2.json \
    --content-type "application/json" \
    --did-doc demo/contract/tmp/test-user/did.json \
    --key demo/contract/tmp/test-user/key.pem \
    --feed "test-feed" \
    --out demo/contract/tmp/test-contract-2.cose

# Submit it
scitt submit-contract demo/contract/tmp/test-contract-2.cose \
    --receipt demo/contract/tmp/test-receipt-2.cbor
```

**Expected Output:**
```
Submitted ... as contract 2.2
```

**CRITICAL:** Contract ID should be `2.2` (incremented from `2.1`).

**Verify blobs:**
```bash
az storage blob list \
    --account-name $PYSCITT_BLOB_ACCOUNT \
    --account-key $PYSCITT_BLOB_KEY \
    --container-name contracts \
    --output table
```

**Expected:** Now shows `2.1.cose` AND `2.2.cose`.

**Ask Claude.ai:** "After second submission, I got contract ID: [ID]. Should this be 2.2?"

---

## Phase 4: TDP Workflow Testing

### Step 4.1: Setup TDP Environment

```bash
cd ~/contract-ledger-SV/demo/contract

export TDP_USERNAME=tdp-test
mkdir -p tmp/$TDP_USERNAME
```

### Step 4.2: Download Service Parameters

```bash
mkdir -p tmp/trust_store

curl -f $CONTRACT_URL/parameters > tmp/trust_store/blob-service.json

echo "Exit code: $?"
cat tmp/trust_store/blob-service.json
```

**Expected Output:**
- Exit code: 0
- JSON with `serviceId`, `treeAlgorithm`, `signatureAlgorithm`, `serviceCertificate`

**Ask Claude.ai:** "The trust store file contains: [paste content]. Is this the correct format?"

### Step 4.3: Create TDP DID

```bash
cd ~/contract-ledger-SV/demo/contract

# Generate TDP key
openssl ecparam -name prime256v1 -genkey -noout -out tmp/$TDP_USERNAME/key.pem

# Create TDP DID
cat > tmp/$TDP_USERNAME/did.json <<EOF
{
  "id": "did:web:tdp.example.com",
  "verificationMethod": [{
    "id": "did:web:tdp.example.com#key-1",
    "type": "JsonWebKey2020",
    "controller": "did:web:tdp.example.com",
    "publicKeyJwk": {}
  }]
}
EOF
```

### Step 4.4: Create Contract with Participant Info

```bash
cd ~/contract-ledger-SV

# Create contract
cat > demo/contract/tmp/contracts/tdp-contract.json <<EOF
{
  "subject": "TDP Contract",
  "model": "COVID-19 Prediction Model v1.0",
  "accuracy": 0.95,
  "training_data": "Synthetic patient records"
}
EOF

# Sign with participant info for TDC
scitt sign-contract \
    --contract demo/contract/tmp/contracts/tdp-contract.json \
    --content-type "application/json" \
    --did-doc demo/contract/tmp/$TDP_USERNAME/did.json \
    --key demo/contract/tmp/$TDP_USERNAME/key.pem \
    --feed "covid-modeling" \
    --participant-info "did:web:tdc.example.com" \
    --out demo/contract/tmp/$TDP_USERNAME/contract.cose

echo "TDP signing exit code: $?"
```

**Expected:** Exit code 0, contract.cose created.

**Ask Claude.ai:** "I'm signing a contract with participant info. What does the --participant-info flag do?"

### Step 4.5: Submit TDP Contract

```bash
scitt submit-contract demo/contract/tmp/$TDP_USERNAME/contract.cose \
    --receipt demo/contract/tmp/$TDP_USERNAME/contract.receipt.cbor \
    --url $CONTRACT_URL

# Save the contract ID for later
TDP_CONTRACT_ID=$(grep -oP 'contract \K[0-9.]+' <<< "$(scitt submit-contract demo/contract/tmp/$TDP_USERNAME/contract.cose 2>&1)")
echo "TDP Contract ID: $TDP_CONTRACT_ID"
echo $TDP_CONTRACT_ID > demo/contract/tmp/tdp_contract_id.txt
```

**Expected Output:**
```
Submitted ... as contract 2.3
TDP Contract ID: 2.3
```

**CRITICAL:** Note the contract ID (e.g., `2.3`). You'll need it for TDC testing.

**Ask Claude.ai:** "TDP submission gave me contract ID: [ID]. How do I extract just the sequence number?"

### Step 4.6: Verify TDP Contract in Blob Storage

```bash
# Check blob exists
az storage blob exists \
    --account-name $PYSCITT_BLOB_ACCOUNT \
    --account-key $PYSCITT_BLOB_KEY \
    --container-name contracts \
    --name $TDP_CONTRACT_ID.cose

# Download and verify
az storage blob download \
    --account-name $PYSCITT_BLOB_ACCOUNT \
    --account-key $PYSCITT_BLOB_KEY \
    --container-name contracts \
    --name $TDP_CONTRACT_ID.cose \
    --file demo/contract/tmp/downloaded-tdp.cose

ls -lh demo/contract/tmp/downloaded-tdp.cose
```

**Expected:** File exists, size > 0.

**Compare:**
```bash
diff demo/contract/tmp/$TDP_USERNAME/contract.cose demo/contract/tmp/downloaded-tdp.cose
echo "Diff exit code: $?"
```

**Expected:** Exit code 0 (files are identical).

**Ask Claude.ai:** "The diff shows: [output]. Are the uploaded and downloaded contracts identical?"

### Step 4.7: Verify Receipt Structure

```bash
# View receipt (will fail verification but should parse)
python3 <<EOF
from pyscitt.receipt import Receipt

with open('demo/contract/tmp/$TDP_USERNAME/contract.receipt.cbor', 'rb') as f:
    receipt_bytes = f.read()
    print(f"Receipt size: {len(receipt_bytes)} bytes")

    receipt = Receipt.decode(receipt_bytes)
    print(f"Receipt tree algorithm: {receipt.phdr.get('tree_alg')}")
    print(f"Receipt service ID: {receipt.phdr.get('service_id')}")
    print("Receipt parsed successfully!")
EOF
```

**Expected Output:**
```
Receipt size: XXX bytes
Receipt tree algorithm: CCF
Receipt service ID: mock-blob-storage-service
Receipt parsed successfully!
```

**Ask Claude.ai:** "Receipt parsing gave this output: [paste output]. Is the receipt structure correct?"

---

## Phase 5: Co-Signing (TDC) Testing

### Step 5.1: Setup TDC Environment

```bash
export TDC_USERNAME=tdc-test
mkdir -p demo/contract/tmp/$TDC_USERNAME

# Create TDC key
openssl ecparam -name prime256v1 -genkey -noout -out demo/contract/tmp/$TDC_USERNAME/key.pem

# Create TDC DID
cat > demo/contract/tmp/$TDC_USERNAME/did.json <<EOF
{
  "id": "did:web:tdc.example.com",
  "verificationMethod": [{
    "id": "did:web:tdc.example.com#key-1",
    "type": "JsonWebKey2020",
    "controller": "did:web:tdc.example.com",
    "publicKeyJwk": {}
  }]
}
EOF
```

### Step 5.2: Retrieve TDP Contract

```bash
# Get the TDP contract ID
TDP_CONTRACT_ID=$(cat demo/contract/tmp/tdp_contract_id.txt)
echo "Retrieving TDP contract: $TDP_CONTRACT_ID"

# Download from blob storage
az storage blob download \
    --account-name $PYSCITT_BLOB_ACCOUNT \
    --account-key $PYSCITT_BLOB_KEY \
    --container-name contracts \
    --name $TDP_CONTRACT_ID.cose \
    --file demo/contract/tmp/contracts/$TDP_CONTRACT_ID.cose

ls -lh demo/contract/tmp/contracts/$TDP_CONTRACT_ID.cose
```

**Expected:** File downloaded successfully.

**Ask Claude.ai:** "How do I verify that I downloaded the correct TDP contract?"

### Step 5.3: TDC Adds Signature

```bash
cd ~/contract-ledger-SV

scitt sign-contract \
    --contract demo/contract/tmp/contracts/$TDP_CONTRACT_ID.cose \
    --content-type "application/cose" \
    --did-doc demo/contract/tmp/$TDC_USERNAME/did.json \
    --key demo/contract/tmp/$TDC_USERNAME/key.pem \
    --out demo/contract/tmp/$TDC_USERNAME/contract.cose \
    --add-signature

echo "TDC signing exit code: $?"
```

**Expected:** Exit code 0, contract.cose created with 2 signatures.

**CRITICAL:** The `--add-signature` flag adds TDC's signature to TDP's contract.

**Verify signature count:**
```bash
python3 <<EOF
from pyscitt.crypto import parse_cose_sign

# TDP version (1 signature)
with open('demo/contract/tmp/contracts/$TDP_CONTRACT_ID.cose', 'rb') as f:
    tdp_msg = parse_cose_sign(f.read())
    print(f"TDP contract signatures: {len(tdp_msg.signers)}")

# TDC version (2 signatures)
with open('demo/contract/tmp/$TDC_USERNAME/contract.cose', 'rb') as f:
    tdc_msg = parse_cose_sign(f.read())
    print(f"Co-signed contract signatures: {len(tdc_msg.signers)}")
EOF
```

**Expected Output:**
```
TDP contract signatures: 1
Co-signed contract signatures: 2
```

**Ask Claude.ai:** "Signature count shows: [output]. Is this correct for co-signing?"

### Step 5.4: Submit Co-Signed Contract

```bash
scitt submit-contract demo/contract/tmp/$TDC_USERNAME/contract.cose \
    --receipt demo/contract/tmp/$TDC_USERNAME/contract.receipt.cbor \
    --url $CONTRACT_URL

# Extract the new contract ID
TDC_CONTRACT_ID=$(grep -oP 'contract \K[0-9.]+' <<< "$(scitt submit-contract demo/contract/tmp/$TDC_USERNAME/contract.cose 2>&1)")
echo "TDC Contract ID: $TDC_CONTRACT_ID"
```

**Expected Output:**
```
Submitted ... as contract 2.4
TDC Contract ID: 2.4
```

**CRITICAL VERIFICATION:**
- New contract ID should be DIFFERENT from TDP's ID
- If TDP was `2.3`, TDC should be `2.4`
- This proves co-signed contract gets new ID

**Ask Claude.ai:** "TDP had contract ID [TDP_ID] and TDC got [TDC_ID]. Is this correct?"

### Step 5.5: Verify Both Contracts Exist

```bash
echo "TDP Contract ID: $TDP_CONTRACT_ID"
echo "TDC Contract ID: $TDC_CONTRACT_ID"

# List blobs
az storage blob list \
    --account-name $PYSCITT_BLOB_ACCOUNT \
    --account-key $PYSCITT_BLOB_KEY \
    --container-name contracts \
    --prefix "2." \
    --output table

# Verify both exist
az storage blob exists \
    --account-name $PYSCITT_BLOB_ACCOUNT \
    --account-key $PYSCITT_BLOB_KEY \
    --container-name contracts \
    --name $TDP_CONTRACT_ID.cose

az storage blob exists \
    --account-name $PYSCITT_BLOB_ACCOUNT \
    --account-key $PYSCITT_BLOB_KEY \
    --container-name contracts \
    --name $TDC_CONTRACT_ID.cose
```

**Expected:** Both commands return "exists": true.

**CRITICAL:** Both `2.3.cose` (TDP) and `2.4.cose` (TDC) must exist.

**Ask Claude.ai:** "Blob list shows: [paste output]. Are both TDP and TDC contracts preserved?"

### Step 5.6: Compare Contract Sizes

```bash
# Download both
az storage blob download \
    --account-name $PYSCITT_BLOB_ACCOUNT \
    --account-key $PYSCITT_BLOB_KEY \
    --container-name contracts \
    --name $TDP_CONTRACT_ID.cose \
    --file demo/contract/tmp/tdp-final.cose

az storage blob download \
    --account-name $PYSCITT_BLOB_ACCOUNT \
    --account-key $PYSCITT_BLOB_KEY \
    --container-name contracts \
    --name $TDC_CONTRACT_ID.cose \
    --file demo/contract/tmp/tdc-final.cose

# Compare sizes
ls -lh demo/contract/tmp/tdp-final.cose demo/contract/tmp/tdc-final.cose
```

**Expected:** TDC contract should be LARGER (has 2 signatures vs 1).

**Ask Claude.ai:** "File sizes are TDP: [size], TDC: [size]. Why is TDC larger?"

---

## Phase 6: Integration Verification

### Step 6.1: Test Range Retrieval

```bash
# Retrieve contracts from 2.1 to 2.4
cd ~/contract-ledger-SV

# This will use blob storage backend
scitt retrieve-contracts demo/contract/tmp/retrieved \
    --from 1 \
    --to 4

ls -lh demo/contract/tmp/retrieved/
```

**Expected Output:**
```
2.1.cose
2.2.cose
2.3.cose
2.4.cose
```

**Ask Claude.ai:** "Retrieved contracts directory contains: [paste ls output]. Is this correct?"

### Step 6.2: Verify Contract Contents

```bash
# Parse each contract
for i in 1 2 3 4; do
    echo "=== Contract 2.$i ==="
    python3 <<EOF
from pyscitt.crypto import parse_cose_sign

with open('demo/contract/tmp/retrieved/2.$i.cose', 'rb') as f:
    msg = parse_cose_sign(f.read())
    print(f"Signatures: {len(msg.signers)}")
    print(f"Content-Type: {msg.phdr.get(3)}")
EOF
done
```

**Expected Output:**
- Contracts 2.1, 2.2, 2.3: 1 signature each
- Contract 2.4: 2 signatures (co-signed)

**Ask Claude.ai:** "Contract analysis shows: [paste output]. Which one is the co-signed contract?"

### Step 6.3: Test Sequence Counter

```bash
# Check final counter value
az storage blob download \
    --account-name $PYSCITT_BLOB_ACCOUNT \
    --account-key $PYSCITT_BLOB_KEY \
    --container-name contracts \
    --name _sequence_counter.txt \
    --file /tmp/final-counter.txt

cat /tmp/final-counter.txt
```

**Expected:** Value should match the highest sequence number (e.g., `4` if you submitted 4 contracts).

**Ask Claude.ai:** "Counter value is [value]. I submitted [N] contracts. Is this correct?"

### Step 6.4: Test Concurrent Submissions (Optional)

```bash
# Create 3 test contracts
for i in 5 6 7; do
    cat > demo/contract/tmp/test-$i.json <<EOF
{"test": "contract-$i"}
EOF

    scitt sign-contract \
        --contract demo/contract/tmp/test-$i.json \
        --content-type "application/json" \
        --did-doc demo/contract/tmp/test-user/did.json \
        --key demo/contract/tmp/test-user/key.pem \
        --feed "test" \
        --out demo/contract/tmp/test-$i.cose
done

# Submit concurrently (background jobs)
scitt submit-contract demo/contract/tmp/test-5.cose &
scitt submit-contract demo/contract/tmp/test-6.cose &
scitt submit-contract demo/contract/tmp/test-7.cose &
wait

echo "All submissions completed"
```

**Expected:** Each gets unique ID (2.5, 2.6, 2.7) with no collisions.

**Verify:**
```bash
az storage blob list \
    --account-name $PYSCITT_BLOB_ACCOUNT \
    --account-key $PYSCITT_BLOB_KEY \
    --container-name contracts \
    --query "[?starts_with(name, '2.')].name" \
    --output table
```

**Expected:** All 7 contracts exist (2.1 through 2.7).

**Ask Claude.ai:** "Concurrent submissions created IDs: [list]. Are there any duplicates?"

### Step 6.5: Verify No Data Loss

```bash
# Count blobs
BLOB_COUNT=$(az storage blob list \
    --account-name $PYSCITT_BLOB_ACCOUNT \
    --account-key $PYSCITT_BLOB_KEY \
    --container-name contracts \
    --query "length([?starts_with(name, '2.')])" \
    --output tsv)

echo "Total contract blobs: $BLOB_COUNT"

# Check counter
COUNTER=$(cat /tmp/final-counter.txt)
echo "Counter value: $COUNTER"

# Should match
if [ "$BLOB_COUNT" -eq "$COUNTER" ]; then
    echo "✅ PASS: Blob count matches counter"
else
    echo "❌ FAIL: Mismatch - $BLOB_COUNT blobs but counter is $COUNTER"
fi
```

**Expected:** PASS - No data loss.

**Ask Claude.ai:** "Blob count is [count], counter is [value]. Should these match?"

---

## Success Criteria Checklist

After completing all phases, verify these criteria:

### Environment Setup
- [ ] Python dependencies installed
- [ ] Azure Function runs locally or deployed
- [ ] Environment variables set correctly
- [ ] Health endpoint returns 200

### Service Parameters
- [ ] GET /api/parameters returns JSON
- [ ] JSON has all 4 required fields (serviceId, treeAlgorithm, signatureAlgorithm, serviceCertificate)
- [ ] Field names are camelCase
- [ ] Trust store file created successfully

### Contract Submission
- [ ] Contract signing works (creates .cose file)
- [ ] Contract submission returns entryId
- [ ] Receipt file is created (CBOR format)
- [ ] Blob is stored in Azure Storage
- [ ] Sequence counter increments correctly

### Identifier Uniqueness
- [ ] Each submission gets unique ID
- [ ] IDs follow format "2.{N}"
- [ ] Sequential numbering (2.1, 2.2, 2.3...)
- [ ] No ID collisions under concurrent load

### Co-Signing Workflow
- [ ] TDP submits contract → gets ID (e.g., 2.3)
- [ ] TDC retrieves TDP's contract successfully
- [ ] TDC adds signature (2 total signatures)
- [ ] TDC submits → gets NEW ID (e.g., 2.4)
- [ ] Both contracts exist in storage (2.3 and 2.4)
- [ ] TDP version has 1 signature
- [ ] TDC version has 2 signatures

### Data Integrity
- [ ] Uploaded and downloaded contracts are identical
- [ ] Blob count matches sequence counter
- [ ] Range retrieval works (--from/--to)
- [ ] No data loss after multiple submissions

---

## Common Issues and Solutions

### Issue 1: Azure Function Won't Start

**Symptom:**
```
Error: Unable to start Azure Functions host
```

**Ask Claude.ai:** "Azure Function fails to start with: [paste error]. What's the cause?"

**Common Causes:**
- Missing `AZURE_STORAGE_CONNECTION_STRING` in `local.settings.json`
- Wrong Python version (need 3.8-3.11)
- Port 7071 already in use

**Solutions:**
- Verify connection string format
- Check Python version: `python3 --version`
- Kill process on port 7071: `sudo lsof -ti:7071 | xargs kill -9`

### Issue 2: Submission Returns 500 Error

**Symptom:**
```
Failed to submit contract: HTTP 500
```

**Ask Claude.ai:** "Submission failed with 500 error. Azure Function logs show: [paste logs]. What's wrong?"

**Common Causes:**
- Storage account credentials incorrect
- Container doesn't exist
- Network connectivity issue

**Solutions:**
- Verify credentials: `az storage account show --name $PYSCITT_BLOB_ACCOUNT`
- Create container: `az storage container create --name contracts --account-name $PYSCITT_BLOB_ACCOUNT`
- Test connectivity: `curl $CONTRACT_URL/health`

### Issue 3: Receipt Parsing Fails

**Symptom:**
```
ValueError: unable to decode receipt
```

**Ask Claude.ai:** "Receipt parsing failed: [paste error]. Is my receipt file corrupted?"

**Common Causes:**
- Receipt file is empty
- Wrong file format (JSON instead of CBOR)

**Solutions:**
- Check file size: `ls -lh receipt.cbor` (should be > 0)
- Verify binary format: `file receipt.cbor` (should say "data")

### Issue 4: Concurrent Submissions Get Same ID

**Symptom:**
Two contracts have same ID (2.5).

**Ask Claude.ai:** "Two concurrent submissions got the same ID: [ID]. Why did atomic locking fail?"

**Common Causes:**
- Lease timeout (submission took > 15 seconds)
- Blob service throttling

**Solutions:**
- Check Azure Function logs for lease errors
- Retry submissions
- Increase lease duration in code if needed

### Issue 5: Trust Store Not Working

**Symptom:**
```
FileNotFoundError: trust_store/blob-service.json
```

**Ask Claude.ai:** "Trust store file not found. Where should it be located?"

**Common Causes:**
- Didn't download service parameters
- Wrong directory path

**Solutions:**
- Create directory: `mkdir -p tmp/trust_store`
- Download parameters: `curl $CONTRACT_URL/parameters > tmp/trust_store/blob-service.json`
- Verify file exists: `cat tmp/trust_store/blob-service.json`

---

## Debugging Commands

### View Azure Function Logs
```bash
# If running locally
# Logs appear in terminal where func start is running

# If deployed to Azure
az functionapp log tail --name <function-name> --resource-group <rg>
```

### Inspect Blob Storage
```bash
# List all blobs
az storage blob list \
    --account-name $PYSCITT_BLOB_ACCOUNT \
    --account-key $PYSCITT_BLOB_KEY \
    --container-name contracts \
    --output table

# Download specific blob
az storage blob download \
    --account-name $PYSCITT_BLOB_ACCOUNT \
    --account-key $PYSCITT_BLOB_KEY \
    --container-name contracts \
    --name 2.1.cose \
    --file /tmp/contract.cose

# View blob properties
az storage blob show \
    --account-name $PYSCITT_BLOB_ACCOUNT \
    --account-key $PYSCITT_BLOB_KEY \
    --container-name contracts \
    --name 2.1.cose
```

### Parse COSE Files
```bash
python3 <<EOF
from pyscitt.crypto import parse_cose_sign
import json

with open('/tmp/contract.cose', 'rb') as f:
    msg = parse_cose_sign(f.read())
    print(f"Signers: {len(msg.signers)}")
    print(f"Protected headers: {dict(msg.phdr)}")
    print(f"Payload preview: {msg.payload[:100]}")
EOF
```

### Check Environment Variables
```bash
env | grep PYSCITT
env | grep CONTRACT_URL
```

---

## Questions to Ask Claude.ai During Testing

Use these prompts when you need help:

1. **Environment Setup:**
   - "How do I install Python dependencies for the SCITT CLI?"
   - "What's the correct format for Azure Storage connection string?"
   - "How do I verify my Azure Function is running correctly?"

2. **During Submission Testing:**
   - "The submission returned contract ID [ID]. Is this format correct?"
   - "How do I check if the blob was actually uploaded to storage?"
   - "The receipt file is [size] bytes. Is this normal?"

3. **During Co-Signing:**
   - "How do I verify that the co-signed contract has 2 signatures?"
   - "Why did TDC get a different contract ID than TDP?"
   - "Should both TDP and TDC contracts exist in storage?"

4. **Debugging:**
   - "I got this error: [paste error]. What's the likely cause?"
   - "The Azure Function logs show: [paste logs]. What's failing?"
   - "Blob list shows: [paste output]. Is anything missing?"

5. **Verification:**
   - "How do I verify that atomic locking prevented ID collisions?"
   - "What should the sequence counter value be after [N] submissions?"
   - "Is the receipt structure correct based on this output: [paste]?"

---

## Advanced Testing (Optional)

### Test 1: Service Parameter Certificate Matching

Verify that the certificate in service parameters matches the receipt:

```bash
# Extract certificate from service parameters
python3 <<EOF
import json
import base64

with open('demo/contract/tmp/trust_store/blob-service.json') as f:
    params = json.load(f)
    cert_der = base64.b64decode(params['serviceCertificate'])
    print(f"Service cert size: {len(cert_der)} bytes")

# Extract certificate from receipt
from pyscitt.receipt import Receipt
with open('demo/contract/tmp/test-receipt.cbor', 'rb') as f:
    receipt = Receipt.decode(f.read())
    receipt_cert = receipt.contents.node_certificate
    print(f"Receipt cert size: {len(receipt_cert)} bytes")

# Compare
if cert_der == receipt_cert:
    print("✅ Certificates match!")
else:
    print("❌ Certificates don't match")
EOF
```

**Expected:** Certificates match.

### Test 2: Blob Lease Timeout Handling

Test what happens when submission takes longer than lease duration:

```bash
# Modify function_app.py temporarily to add sleep
# Then submit and observe behavior

# Or test by submitting very large contract
dd if=/dev/urandom of=demo/contract/tmp/large.json bs=1M count=10
scitt sign-contract --contract demo/contract/tmp/large.json ... --out large.cose
scitt submit-contract large.cose
```

**Ask Claude.ai:** "How should the system handle lease timeout during submission?"

### Test 3: Storage Account Failover

Test resilience to storage service issues:

```bash
# Submit contract
scitt submit-contract contract.cose &
PID=$!

# Immediately revoke storage account key (in Azure Portal or CLI)
# Observer what happens

wait $PID
echo "Exit code: $?"
```

**Expected:** Graceful error message, no data corruption.

---

## Reporting Results

After completing all tests, create a summary:

```bash
cat > ~/test-results.txt <<EOF
BLOB STORAGE BACKEND TEST RESULTS
=================================

Date: $(date)
Tester: [Your Name]

Environment:
- VM OS: $(uname -a)
- Python Version: $(python3 --version)
- Azure Function: [Local / Deployed]
- Storage Account: $PYSCITT_BLOB_ACCOUNT

Test Phase Results:
1. Environment Setup: [PASS/FAIL]
2. Azure Function Deployment: [PASS/FAIL]
3. Basic Submission: [PASS/FAIL]
4. TDP Workflow: [PASS/FAIL]
5. Co-Signing (TDC): [PASS/FAIL]
6. Integration Verification: [PASS/FAIL]

Contracts Submitted: [N]
Contract ID Range: 2.1 to 2.[N]
Sequence Counter Final Value: [N]
Total Blobs in Storage: [count]

Issues Encountered:
- [List any issues]

Notes:
- [Any additional observations]

EOF

cat ~/test-results.txt
```

**Share this summary** with Claude.ai for final review.

---

## Next Steps After Testing

Once all tests pass:

1. **Document findings:** Note any issues or suggestions
2. **Performance testing:** Test with 100+ concurrent submissions
3. **Cost analysis:** Review Azure Storage costs
4. **Production planning:** Decide on CCF vs Blob for different environments
5. **Integration:** Integrate with depa-training workflows

**Ask Claude.ai:** "All tests passed! What should I consider before using this in production?"

---

## Getting Help

If you encounter issues not covered here:

1. **Check logs:** Azure Function logs usually have detailed error messages
2. **Verify environment:** Ensure all environment variables are set
3. **Test endpoints:** Use curl to test each endpoint independently
4. **Ask Claude.ai:** Provide specific error messages and context

**Template for asking help:**
```
I'm testing the blob storage backend and encountered an issue:

Test Phase: [which phase]
Command run: [exact command]
Error message: [paste full error]
Environment: [OS, Python version]
Previous steps: [what worked before this]

What could be wrong?
```

---

## Summary

This testing guide covers:
- ✅ Complete environment setup
- ✅ Azure Function deployment (local and cloud)
- ✅ Basic contract submission
- ✅ TDP workflow (single signature)
- ✅ TDC co-signing workflow (multiple signatures)
- ✅ Integration testing (retrieval, verification)
- ✅ Troubleshooting common issues

**Estimated Time:** 2-3 hours for complete testing.

**Success Indicator:** All contracts submitted, unique IDs assigned, both TDP and TDC contracts preserved in storage, no data loss.

Good luck with testing! 🚀

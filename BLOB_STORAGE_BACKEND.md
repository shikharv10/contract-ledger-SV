# Azure Blob Storage Backend for SCITT Contract Ledger

This document describes the Azure Blob Storage backend implementation for the SCITT contract ledger, which provides a low-cost alternative to CCF for training and demonstration purposes.

## Overview

The SCITT contract ledger now supports two backends:

| Backend | Use Case | Cost | Sequence Numbering | Receipts |
|---------|----------|------|-------------------|----------|
| **CCF** | Production | $1000-2000/month | Blockchain consensus | Cryptographic |
| **Blob** | Training/Demo | ~$0.01/month | Atomic counter (blob lease) | Synthetic (JSON) |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Python CLI (pyscitt)                    │
│  ┌────────────────────┐        ┌──────────────────────┐    │
│  │ submit_contract.py │        │ retrieve_contracts.py│    │
│  └────────┬───────────┘        └──────────┬───────────┘    │
│           │                               │                 │
└───────────┼───────────────────────────────┼─────────────────┘
            │                               │
            │ PYSCITT_BACKEND=blob          │
            │                               │
    ┌───────▼───────────────────────────────▼───────┐
    │         Environment Variable Router           │
    │  if blob: use Azure Function + Blob Storage   │
    │  if ccf:  use CCF Client                      │
    └───────┬───────────────────────────┬───────────┘
            │                           │
┌───────────▼──────────┐    ┌───────────▼──────────┐
│   Azure Function     │    │   Blob Storage       │
│   /api/submit        │    │   (retrieve direct)  │
│                      │    │                      │
│  1. Acquire lease    │    │   2.1.cose          │
│  2. Increment counter│    │   2.2.cose          │
│  3. Upload contract  │    │   2.3.cose          │
│  4. Return entryId   │    │   _sequence_counter │
└──────────────────────┘    └─────────────────────┘
```

## Implementation Details

### Sequence Number Management

**Challenge**: Multiple concurrent submissions must each get unique sequence numbers (2.1, 2.2, 2.3...) without conflicts.

**Solution**: Azure Blob Lease (distributed lock)

1. Counter stored in `_sequence_counter.txt` blob
2. Azure Function acquires 15-second lease before read-modify-write
3. Only one function instance can hold the lease at a time
4. Automatic retry with exponential backoff on conflicts
5. Lease auto-releases after 15 seconds if process crashes

**Flow:**
```python
# Azure Function atomic counter logic
lease = blob_client.acquire_lease(15)  # Distributed lock
try:
    current = int(blob_client.download_blob(lease=lease).readall())
    next_seq = current + 1
    blob_client.upload_blob(str(next_seq), lease=lease)
    return next_seq
finally:
    lease.release()
```

### Contract Workflow

#### 1. TDP Signs and Submits
```bash
# TDP creates and signs contract
scitt sign-contract --contract contract.json --key tdp_key.pem --out tdp_contract.cose

# Submit to blob storage
export PYSCITT_BACKEND=blob
export PYSCITT_BLOB_SERVICE_URL=https://myfunction.azurewebsites.net
scitt submit-contract tdp_contract.cose
# Output: Submitted tdp_contract.cose to blob storage as contract 2.1
```

Result: `2.1.cose` stored in blob storage

#### 2. TDC Retrieves, Co-signs, and Submits
```bash
# TDC retrieves TDP's contract
export PYSCITT_BACKEND=blob
export PYSCITT_BLOB_ACCOUNT=mystorageaccount
export PYSCITT_BLOB_KEY=<key>
scitt retrieve-contracts ./tmp --contract-id 2.1

# TDC co-signs (adds their signature)
scitt sign-contract --contract tmp/2.1.cose --key tdc_key.pem --out tdc_contract.cose --add-signature

# TDC submits co-signed contract
scitt submit-contract tdc_contract.cose
# Output: Submitted tdc_contract.cose to blob storage as contract 2.2
```

Result: `2.2.cose` stored in blob storage (fully co-signed contract)

#### 3. User Deploys with CCR
```bash
# User notes sequence number 2.2 and uses it during deployment
deploy_ccr.sh --contract-id 2.2

# CCR validates by retrieving 2.2.cose from blob storage
```

## Files Modified

### 1. `pyscitt/setup.py`
Added dependencies:
- `azure-storage-blob>=12.0.0`
- `loguru>=0.7.0`

### 2. `pyscitt/pyscitt/cli/submit_signed_contract.py`
**Changes:**
- Added `submit_to_blob_storage()` function
  - POSTs contract to Azure Function endpoint
  - Receives `entryId` (sequence number) in response
  - Creates synthetic JSON receipt if `--receipt` provided
- Modified `cmd()` to route based on `PYSCITT_BACKEND` env var

**New function signature:**
```python
def submit_to_blob_storage(path: Path, receipt_path: Optional[Path] = None) -> str:
    """Submit contract to Azure Function endpoint, get sequence number back."""
```

### 3. `pyscitt/pyscitt/cli/retrieve_signed_contracts.py`
**Changes:**
- Added `retrieve_from_blob_storage()` function
  - Downloads directly from blob storage using Azure SDK
  - Supports `--contract-id` (single) or `--from/--to` (range)
  - Extracts JSON payload to `.json` file
  - Logs info about skipped verification (no cryptographic receipts)
- Added `--contract-id` CLI argument
- Modified `cmd()` to route based on `PYSCITT_BACKEND` env var

**New function signature:**
```python
def retrieve_from_blob_storage(
    base_path: Path,
    contract_id: Optional[str] = None,
    from_seqno: Optional[int] = None,
    to_seqno: Optional[int] = None,
    service_trust_store_path: Optional[Path] = None
):
    """Retrieve contracts from blob storage."""
```

### 4. `azure-function/` (New Directory)
Complete Azure Function implementation:
- `function_app.py` - HTTP endpoint with atomic counter logic
- `requirements.txt` - Python dependencies
- `host.json` - Function app configuration
- `README.md` - Deployment instructions
- `.funcignore` - Files to exclude during deployment

## Environment Variables

### Blob Storage Mode
```bash
# Required
export PYSCITT_BACKEND=blob
export PYSCITT_BLOB_SERVICE_URL=https://myfunction.azurewebsites.net

# For retrieval
export PYSCITT_BLOB_ACCOUNT=mystorageaccount
export PYSCITT_BLOB_KEY=<storage-account-key>

# Optional (defaults to "contracts")
export PYSCITT_BLOB_CONTAINER=contracts
```

### CCF Mode (Default)
```bash
# Default mode (or explicitly set)
export PYSCITT_BACKEND=ccf
export CONTRACT_URL=https://contract-service:8000
```

## Usage Examples

### Submit Contract (Blob Mode)
```bash
export PYSCITT_BACKEND=blob
export PYSCITT_BLOB_SERVICE_URL=https://scitt-blob-function.azurewebsites.net

scitt submit-contract contract.cose --receipt receipt.json
```

**Output:**
```
Submitted contract.cose to blob storage as contract 2.15
Created synthetic receipt at receipt.json
```

### Retrieve Single Contract
```bash
export PYSCITT_BACKEND=blob
export PYSCITT_BLOB_ACCOUNT=scittblobstorage
export PYSCITT_BLOB_KEY=<key>

scitt retrieve-contracts ./output --contract-id 2.15
```

**Output:**
```
Retrieved contract 2.15
Retrieved 1 contract(s) to ./output
```

**Files created:**
- `output/2.15.cose` - Contract file
- `output/2.15.json` - Extracted JSON payload

### Retrieve Range of Contracts
```bash
scitt retrieve-contracts ./output --from 10 --to 15
```

**Output:**
```
Retrieved contract 2.10
Retrieved contract 2.11
Retrieved contract 2.13
Retrieved contract 2.15
Retrieved 4 contract(s) to ./output
```

Note: Contracts 2.12 and 2.14 were skipped (not found in storage)

### Submit Contract (CCF Mode - No Changes)
```bash
export PYSCITT_BACKEND=ccf
export CONTRACT_URL=https://127.0.0.1:8000

scitt submit-contract contract.cose --url $CONTRACT_URL --receipt receipt.cbor
```

## Blob Storage Structure

```
Container: contracts/
├── _sequence_counter.txt         # "17" (next available sequence)
├── 2.1.cose                      # TDP's signed contract
├── 2.2.cose                      # TDC's co-signed contract
├── 2.3.cose
├── 2.15.cose
├── 2.16.cose
└── 2.17.cose
```

## Deployment

See `azure-function/README.md` for complete deployment instructions.

**Quick start:**
```bash
# 1. Deploy Azure Function
cd azure-function
func azure functionapp publish scitt-blob-function

# 2. Configure Python CLI
export PYSCITT_BACKEND=blob
export PYSCITT_BLOB_SERVICE_URL=https://scitt-blob-function.azurewebsites.net
export PYSCITT_BLOB_ACCOUNT=scittblobstorage
export PYSCITT_BLOB_KEY=$(az storage account keys list --account-name scittblobstorage --query '[0].value' -o tsv)

# 3. Use the CLI
scitt submit-contract contract.cose
```

## Testing

### Test 1: Basic Submission
```bash
scitt submit-contract contract.cose --receipt receipt.json
# Expected: Contract gets sequence number 2.1
```

### Test 2: TDP → TDC Workflow
```bash
# TDP submits
scitt submit-contract tdp_contract.cose
# Output: contract 2.1

# TDC retrieves
scitt retrieve-contracts ./tmp --contract-id 2.1

# TDC co-signs and submits
scitt sign-contract --contract tmp/2.1.cose --key tdc_key.pem --out tdc_contract.cose --add-signature
scitt submit-contract tdc_contract.cose
# Output: contract 2.2
```

### Test 3: Concurrent Submissions (Race Condition Test)
```bash
# Submit 10 contracts simultaneously
for i in {1..10}; do
    (scitt submit-contract contract$i.cose && echo "Success: $i") &
done
wait

# Verify: All contracts should have unique sequence numbers (no duplicates)
```

### Test 4: CCF Mode (Regression Test)
```bash
export PYSCITT_BACKEND=ccf
export CONTRACT_URL=https://127.0.0.1:8000

scitt submit-contract contract.cose --url $CONTRACT_URL
# Should work exactly as before (no changes to CCF mode)
```

## Error Handling

### Missing Environment Variables
```bash
$ scitt submit-contract contract.cose
ValueError: Missing PYSCITT_BLOB_SERVICE_URL environment variable.
Set it to your Azure Function endpoint (e.g., https://myfunction.azurewebsites.net)
```

### Unknown Backend
```bash
$ export PYSCITT_BACKEND=invalid
$ scitt submit-contract contract.cose
ValueError: Unknown backend: 'invalid'. Set PYSCITT_BACKEND to 'ccf' or 'blob'
```

### Contract Not Found
```bash
$ scitt retrieve-contracts ./output --contract-id 2.999
Contract 2.999 not found or download failed: The specified blob does not exist
No contracts found matching the criteria
```

## Limitations

⚠️ **This is for TRAINING/DEMOS ONLY, not production use:**

- **No cryptographic receipts**: Receipts are synthetic JSON, not cryptographic proofs
- **No authentication**: Azure Function endpoint is publicly accessible
- **No verification**: Trust the blob storage, not cryptography
- **No consensus**: Single point of failure (blob storage)
- **No audit trail**: Contracts can be deleted from blob storage

For production, use CCF with proper authentication and cryptographic guarantees.

## Cost Comparison

| Component | CCF (Production) | Blob Storage (Demo) |
|-----------|------------------|---------------------|
| Compute | $1000-2000/month | $0.00 (free tier) |
| Storage | Included | $0.01/month |
| Network | Included | $0.00 (minimal) |
| **Total** | **$1000-2000/month** | **~$0.01/month** |

## Troubleshooting

### Lease Timeout Errors
**Symptom:** "Failed to acquire sequence counter lock"

**Cause:** High concurrent load or hung lease

**Solution:** Automatic retry (up to 3 attempts). Wait 30 seconds for lease to expire.

### Slow Submissions
**Symptom:** Submissions take 5-10 seconds

**Cause:** Azure Function cold start

**Solution:** Use Premium plan or pre-warm the function

### Missing Blobs in Range
**Symptom:** Some contracts skipped during range retrieval

**Cause:** Gaps in sequence numbers (expected behavior)

**Solution:** Normal behavior - contracts may be deleted or never created

## Security Considerations

### Public Endpoint
The Azure Function endpoint is publicly accessible. For production:
- Add API key authentication
- Use Azure AD authentication
- Implement rate limiting

### Blob Access
Storage account key provides full access. For production:
- Use SAS tokens with limited permissions
- Enable Azure AD authentication
- Implement IP restrictions

### Contract Validation
Blob mode doesn't validate contracts. For production:
- Add contract schema validation
- Verify signatures before storage
- Implement access control

## Future Enhancements

Potential improvements (not implemented):

1. **Authentication**: Add API key or Azure AD auth to function
2. **Receipts**: Generate CBOR receipts (without cryptographic proofs)
3. **Validation**: Validate COSE structure before storage
4. **Metrics**: Add Application Insights telemetry
5. **Caching**: Cache frequently accessed contracts
6. **Replication**: Geo-replicate blob storage for HA

## Support

For issues or questions:
- **Azure Function**: See `azure-function/README.md`
- **Python CLI**: Check environment variables and logs
- **General**: Review this document and test examples

## Summary

The blob storage backend provides a **low-cost alternative** to CCF for **training and demonstration** purposes, with:

✅ Atomic sequence number assignment via blob leases
✅ Full TDP → TDC → User workflow support
✅ Concurrent submission safety
✅ Simple HTTP API (Azure Function)
✅ ~$0.01/month cost vs $1000-2000/month for CCF

⚠️ **Not for production use** - lacks cryptographic guarantees and authentication

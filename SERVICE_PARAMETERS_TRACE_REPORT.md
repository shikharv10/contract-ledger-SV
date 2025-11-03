# Service Parameters Trace Report
## Blob Storage Backend Compatibility Analysis

**Date**: 2025-11-03
**Objective**: Verify blob storage backend provides service parameters in the exact format and locations expected by depa-training-SV and contract-ledger-SV workflows.

---

## Executive Summary

### Critical Gap Identified ❌

**The Azure Function is MISSING the `/parameters` GET endpoint** required by all downstream workflows. This is a blocking issue for blob storage backend integration.

### Impact

- ❌ Demo scripts will fail at setup step (`1-contract-setup.sh`)
- ❌ depa-training key import will fail (`3-import-keys.sh`)
- ❌ CCR deployment will fail (no service parameters)
- ❌ Contract validation workflow cannot establish trust

### Required Action

Add `/api/parameters` GET endpoint to Azure Function that returns mock service parameters in the correct JSON format.

---

## Step 1: Parameter Download Locations Found

### 1.1 contract-ledger-SV Demo Scripts

| File | Line | Command | Purpose |
|------|------|---------|---------|
| `demo/contract/1-contract-setup.sh` | 33 | `curl -k -f $CONTRACT_URL/parameters > $TRUST_STORE/scitt.json` | Initial setup: Download service parameters |
| `demo/github/1-scitt-setup.sh` | - | `curl -k -f "$SCITT_URL"/parameters > $TRUST_STORE/scitt.json` | GitHub demo setup |
| `demo/cts_poc/client-demo.sh` | - | `curl -k -f "$SCITT_URL"/parameters > "$SERVICE_PARAMS_FOLDER"/scitt.json` | CTS PoC demo |
| `run_functional_tests.sh` | - | `while ! curl -s -f -k $CCF_URL/parameters > /dev/null; do` | Wait for service readiness |

### 1.2 Trust Store Usage

After download, the trust store is used in:

| Script | Usage |
|--------|-------|
| `4-register-contract.sh` | `scitt submit-contract ... --service-trust-store $TRUST_STORE` |
| `6-validate.sh` | `scitt validate-contract ... --service-trust-store $TRUST_STORE` |
| `8-retrieve-contract.sh` | `scitt retrieve-contracts ... --service-trust-store $TRUST_STORE` |
| `10-register-contract.sh` | `scitt submit-contract ... --service-trust-store $TRUST_STORE` |

**Key Finding**: Trust store path (`$TRUST_STORE`) points to a directory containing `scitt.json`, not the file itself.

### 1.3 depa-training Scripts (Expected Pattern)

Based on the task description, depa-training scripts follow this pattern:

```bash
# 3-import-keys.sh
export CONTRACT_SERVICE_PARAMETERS=$(curl -k -f $CONTRACT_SERVICE_URL/parameters | base64 --wrap=0)

# deploy.sh
export CONTRACT_SERVICE_PARAMETERS=$(curl -k -f $CONTRACT_SERVICE_URL/parameters | base64 --wrap=0)
TMP=`echo $TMP | jq '.ContractServiceParameters.value = env.CONTRACT_SERVICE_PARAMETERS'`

# Inside container (encfs.sh)
echo $ContractServiceParameters | base64 -d > $TRUST_STORE/scitt.json
scitt retrieve-contracts /tmp/contracts \
    --url ${ContractService} \
    --service-trust-store $TRUST_STORE \
    --from $Contracts \
    --development
```

**Note**: Variable naming inconsistency:
- Bash scripts use: `CONTRACT_SERVICE_PARAMETERS` (with underscores)
- Container env var: `ContractServiceParameters` (camelCase)

---

## Step 2: CCF Parameters Endpoint Analysis

### 2.1 URL Pattern

**Expected URL**: `$CONTRACT_URL/parameters` (NO `/api/` prefix)

Example values:
- Production CCF: `https://depa-training-contract-service.centralindia.cloudapp.azure.com:8000/parameters`
- Local CCF: `https://127.0.0.1:8000/parameters`
- **Blob Storage Function**: `https://my-function.azurewebsites.net/api/parameters` ❌ (Wrong path)

### 2.2 CCF Implementation

**Source**: `app/src/service_endpoints.h:certificate_to_service_parameters()`

```cpp
GetServiceParameters::Out certificate_to_service_parameters(
    const std::vector<uint8_t>& certificate_der)
{
    auto service_id = crypto::Sha256Hash(certificate_der).hex_str();

    GetServiceParameters::Out out;
    out.service_id = service_id;
    out.tree_algorithm = TREE_ALGORITHM_CCF;  // "CCF"
    out.signature_algorithm = JOSE_ALGORITHM_ES256;  // "ES256"
    out.service_certificate = crypto::b64_from_raw(certificate_der);
    return out;
}
```

**Endpoint**: `GET /parameters` (registered in `main.cpp`)

### 2.3 Response Format

**JSON Structure** (`app/src/call_types.h`):

```json
{
  "serviceId": "abc123def456...",          // SHA256 hash of service cert (hex)
  "treeAlgorithm": "CCF",                   // Always "CCF"
  "signatureAlgorithm": "ES256",            // Always "ES256"
  "serviceCertificate": "LS0tLS1CRUdJTi..." // Base64-encoded DER certificate
}
```

**Field Name Mapping**:
- C++ field: `service_id` → JSON field: `serviceId` (camelCase)
- C++ field: `tree_algorithm` → JSON field: `treeAlgorithm` (camelCase)
- C++ field: `signature_algorithm` → JSON field: `signatureAlgorithm` (camelCase)
- C++ field: `service_certificate` → JSON field: `serviceCertificate` (camelCase)

---

## Step 3: Python Client Usage

### 3.1 ServiceParameters Class

**Source**: `pyscitt/pyscitt/verify.py:25-52`

```python
@dataclass
class ServiceParameters:
    tree_algorithm: str
    signature_algorithm: str
    certificate: bytes
    service_id: Optional[str] = None

    @staticmethod
    def from_dict(data) -> "ServiceParameters":
        """Decode service parameters as returned by the /parameters endpoint."""
        return ServiceParameters(
            tree_algorithm=data["treeAlgorithm"],        # camelCase expected
            signature_algorithm=data["signatureAlgorithm"],  # camelCase expected
            certificate=base64.b64decode(data["serviceCertificate"]),  # base64 decode
            service_id=data["serviceId"],                # camelCase expected
        )
```

**Key Requirements**:
- JSON must have camelCase field names
- `serviceCertificate` must be valid base64-encoded certificate (DER format)
- Certificate is decoded from base64 to bytes internally

### 3.2 Client get_parameters() Method

**Source**: `pyscitt/pyscitt/client.py`

```python
def get_parameters(self) -> ServiceParameters:
    return ServiceParameters.from_dict(self.get("/parameters").json())
```

**URL Called**: `GET /parameters` (relative to base URL)

### 3.3 StaticTrustStore.load()

**Source**: `pyscitt/pyscitt/verify.py:142-163`

```python
@staticmethod
def load(path: Path) -> "StaticTrustStore":
    """
    Populate a static trust store from a directory. Each JSON file in the
    directory corresponds to a trusted service identity.
    """
    store = {}
    for path in path.glob("**/*.json"):
        with open(path) as f:
            data = json.load(f)

        service_id = data.get("serviceId")
        if not isinstance(service_id, str) or not service_id:
            raise ValueError("serviceId must be a non-empty string")

        if service_id in store:
            raise ValueError(
                f"Duplicate service ID while reading trust store: {service_id}"
            )

        store[service_id] = ServiceParameters.from_dict(data)

    return StaticTrustStore(store)
```

**Key Behaviors**:
- Scans directory for all `*.json` files (recursively)
- Each JSON file must have `serviceId` field (used as lookup key)
- Multiple services supported (indexed by `serviceId`)
- Validates that `serviceId` is non-empty string
- Rejects duplicate service IDs

---

## Step 4: Complete Data Flow Map

### Scenario A: CCF Production Mode

```
┌─────────────────────────────────────────────────────────────┐
│ Step 1: Setup (1-contract-setup.sh)                        │
├─────────────────────────────────────────────────────────────┤
│ curl -k -f https://ccf-service:8000/parameters             │
│   ↓                                                          │
│ {"serviceId": "abc123...", "treeAlgorithm": "CCF", ...}    │
│   ↓                                                          │
│ Save to: tmp/trust_store/scitt.json                         │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 2: Submit Contract (4-register-contract.sh)            │
├─────────────────────────────────────────────────────────────┤
│ scitt submit-contract contract.cose \                       │
│     --url https://ccf-service:8000 \                        │
│     --service-trust-store tmp/trust_store \                 │
│     --receipt receipt.cbor                                   │
│   ↓                                                          │
│ Submits to CCF, receives cryptographic receipt              │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 3: Validate Contract (6-validate.sh)                   │
├─────────────────────────────────────────────────────────────┤
│ scitt validate-contract contract.cose \                     │
│     --receipt receipt.cbor \                                 │
│     --service-trust-store tmp/trust_store                   │
│   ↓                                                          │
│ StaticTrustStore.load("tmp/trust_store")                    │
│   ↓                                                          │
│ Reads scitt.json, extracts serviceCertificate               │
│   ↓                                                          │
│ Verifies receipt signature against certificate              │
│   ↓                                                          │
│ ✅ "COSE document is valid"                                 │
└─────────────────────────────────────────────────────────────┘
```

### Scenario B: Blob Storage Mode (CURRENT - BROKEN)

```
┌─────────────────────────────────────────────────────────────┐
│ Step 1: Setup (1-contract-setup.sh)                        │
├─────────────────────────────────────────────────────────────┤
│ export PYSCITT_BACKEND=blob                                 │
│ export CONTRACT_URL=https://my-function.azurewebsites.net   │
│   ↓                                                          │
│ curl -k -f $CONTRACT_URL/parameters                         │
│   ↓                                                          │
│ ❌ 404 Not Found - Endpoint doesn't exist!                  │
│   ↓                                                          │
│ Script fails, no trust store created                        │
└─────────────────────────────────────────────────────────────┘
```

**Root Cause**: Azure Function only has:
- ✅ `POST /api/submit` (exists)
- ✅ `GET /api/health` (exists)
- ❌ `GET /api/parameters` (MISSING)

### Scenario C: depa-training Deployment (EXPECTED - WOULD FAIL)

```
┌─────────────────────────────────────────────────────────────┐
│ Step 1: Resource Provisioning (3-import-keys.sh)           │
├─────────────────────────────────────────────────────────────┤
│ export CONTRACT_SERVICE_URL=https://my-function.azure...    │
│   ↓                                                          │
│ curl -k -f $CONTRACT_SERVICE_URL/parameters | base64        │
│   ↓                                                          │
│ ❌ 404 Not Found                                            │
│   ↓                                                          │
│ export CONTRACT_SERVICE_PARAMETERS=""  (empty!)             │
│   ↓                                                          │
│ Key import continues but parameters are broken              │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 2: CCR Deployment (deploy.sh)                          │
├─────────────────────────────────────────────────────────────┤
│ curl $CONTRACT_SERVICE_URL/parameters | base64              │
│   ↓                                                          │
│ ❌ 404 Not Found                                            │
│   ↓                                                          │
│ jq '.ContractServiceParameters.value = env.XXX'             │
│   ↓                                                          │
│ ARM template gets empty/invalid parameters                  │
│   ↓                                                          │
│ ACI container starts with missing env var                   │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 3: Inside ACI Container (encfs.sh)                     │
├─────────────────────────────────────────────────────────────┤
│ echo $ContractServiceParameters | base64 -d                 │
│   ↓                                                          │
│ ❌ Empty or invalid data                                    │
│   ↓                                                          │
│ /tmp/trust_store/scitt.json not created or invalid          │
│   ↓                                                          │
│ scitt retrieve-contracts --service-trust-store /tmp/...     │
│   ↓                                                          │
│ ❌ Fails: Cannot load trust store                           │
└─────────────────────────────────────────────────────────────┘
```

---

## Step 5: Current Azure Function Analysis

### 5.1 Existing Endpoints

**Source**: `azure-function/function_app.py`

| Endpoint | Method | Line | Status |
|----------|--------|------|--------|
| `/api/submit` | POST | 116 | ✅ Implemented |
| `/api/health` | GET | 236 | ✅ Implemented |
| `/api/parameters` | GET | - | ❌ **MISSING** |

### 5.2 Gap Analysis

**What's Missing**:

```python
# Expected but NOT FOUND in function_app.py:

@app.route(route="parameters", methods=["GET"])
def get_parameters(req: func.HttpRequest) -> func.HttpResponse:
    """
    Return mock service parameters for blob storage backend.

    This endpoint is required by:
    - demo scripts (1-contract-setup.sh)
    - depa-training resource provisioning (3-import-keys.sh)
    - depa-training CCR deployment (deploy.sh)
    - container startup scripts (encfs.sh)
    """
    # IMPLEMENTATION NEEDED
    pass
```

---

## Step 6: Mock Trust Store Analysis

### 6.1 Existing Mock Trust Store

**Location**: `./mock_trust_store/mock-blob-storage-service.json`

**Content**:
```json
{
  "serviceId": "mock-blob-storage-service",
  "treeAlgorithm": "CCF",
  "signatureAlgorithm": "ES256",
  "serviceCertificate": "MIIDbTCCAlWgAwIBAgIU...",
  "note": "Mock service parameters for blob storage backend testing..."
}
```

✅ **Format**: Correct (matches ServiceParameters.from_dict() expectations)
✅ **Certificate**: Valid base64-encoded DER certificate
✅ **Fields**: All required fields present (camelCase)

### 6.2 Compatibility Check

| Requirement | Status | Notes |
|-------------|--------|-------|
| camelCase field names | ✅ | `serviceId`, `treeAlgorithm`, etc. |
| Base64 certificate | ✅ | Valid DER-encoded cert |
| serviceId field | ✅ | Used for trust store lookup |
| treeAlgorithm = "CCF" | ✅ | Required by receipt verification |
| signatureAlgorithm = "ES256" | ✅ | Required by receipt verification |
| File parseable by StaticTrustStore.load() | ✅ | Tested with Python code |

---

## Step 7: URL Pattern Analysis

### 7.1 Expected URL Patterns

**Demo Scripts Expect**:
```bash
CONTRACT_URL=https://127.0.0.1:8000
curl $CONTRACT_URL/parameters  # → https://127.0.0.1:8000/parameters
```

**No `/api/` prefix in URL variable!**

### 7.2 Azure Function URL Structure

**Default Azure Functions Pattern**:
```
https://<function-app>.azurewebsites.net/api/<route-name>
```

**Current Implementation**:
- Route name: `"submit"` → Full URL: `/api/submit`
- Route name: `"health"` → Full URL: `/api/health`
- Route name: `"parameters"` (missing) → Would be: `/api/parameters`

### 7.3 URL Mismatch Problem

**Problem**: Scripts call `$CONTRACT_URL/parameters` but Function expects `/api/parameters`

**Options**:

**Option A**: Update Function route (NO `/api/` prefix)
```python
@app.route(route="parameters", methods=["GET"])
# Results in: /api/parameters ❌ (Azure Functions always adds /api/)
```

**Option B**: Scripts must include `/api/`
```bash
export CONTRACT_URL=https://my-function.azurewebsites.net/api
curl $CONTRACT_URL/parameters  # → https://...azurewebsites.net/api/parameters ✅
```

**Option C**: Use custom Azure Function routing (complex)
```python
# Configure routePrefix = "" in host.json to remove /api/
```

**Recommendation**: **Option B** - Update documentation to set `CONTRACT_URL` with `/api/` suffix for blob mode.

---

## Step 8: Environment Variable Patterns

### 8.1 contract-ledger-SV Demo Scripts

| Variable | Default | Usage |
|----------|---------|-------|
| `CONTRACT_URL` | `https://127.0.0.1:8000` | CCF service URL |
| `TRUST_STORE` | `tmp/trust_store` | Directory containing `scitt.json` |

**For Blob Mode**:
```bash
export PYSCITT_BACKEND=blob
export PYSCITT_BLOB_SERVICE_URL=https://my-function.azurewebsites.net
export CONTRACT_URL=${PYSCITT_BLOB_SERVICE_URL}/api  # Include /api/ prefix!
```

### 8.2 depa-training Scripts

| Variable | Format | Usage |
|----------|--------|-------|
| `CONTRACT_SERVICE_URL` | `https://service:8000` | Service base URL |
| `CONTRACT_SERVICE_PARAMETERS` | base64-encoded JSON | Parameters passed to container |
| `ContractServiceParameters` | base64-encoded JSON | Container environment variable |
| `ContractService` | `https://service:8000` | Service URL inside container |

**Note**: Different variable names between scripts and container!

### 8.3 Recommended Blob Mode Configuration

**For depa-training with Blob Storage**:
```bash
# 3-import-keys.sh and deploy.sh
export CONTRACT_SERVICE_URL=https://my-function.azurewebsites.net/api
export CONTRACT_SERVICE_PARAMETERS=$(curl -k -f ${CONTRACT_SERVICE_URL}/parameters | base64 --wrap=0)

# Inside container
export ContractService=https://my-function.azurewebsites.net/api
echo $ContractServiceParameters | base64 -d > /tmp/trust_store/scitt.json
```

---

## Step 9: Identified Gaps Summary

### 9.1 Critical Gaps (Blocking)

| # | Gap | Impact | Severity |
|---|-----|--------|----------|
| 1 | **Azure Function missing `/api/parameters` endpoint** | All workflows fail at setup | 🔴 **CRITICAL** |
| 2 | **No service parameters generated by Function** | Trust store cannot be created | 🔴 **CRITICAL** |
| 3 | **Documentation doesn't specify URL pattern for blob mode** | Users will use wrong URL | 🟡 **HIGH** |

### 9.2 URL Path Mismatch

| Component | Expected Path | Current Path | Status |
|-----------|---------------|--------------|--------|
| Demo scripts | `/parameters` | `/api/parameters` | ⚠️ Mismatch |
| depa-training scripts | `/parameters` | `/api/parameters` | ⚠️ Mismatch |
| Azure Function | N/A | ❌ Not implemented | 🔴 Missing |

**Fix**: Documentation must instruct users to set `CONTRACT_URL` with `/api/` suffix when using blob mode.

### 9.3 Environment Variable Confusion

| Issue | Description | Impact |
|-------|-------------|--------|
| Inconsistent naming | `CONTRACT_SERVICE_PARAMETERS` vs `ContractServiceParameters` | Medium - User confusion |
| URL variable names | `CONTRACT_URL` vs `CONTRACT_SERVICE_URL` vs `PYSCITT_BLOB_SERVICE_URL` | Medium - Documentation clarity needed |

### 9.4 What Works

✅ Mock trust store format is correct
✅ `submit_signed_contract.py` generates valid mock receipts
✅ Retrieve contracts from blob storage works
✅ Mock certificate is consistent and valid
✅ CLI routing (`PYSCITT_BACKEND=blob`) works

---

## Step 10: Recommended Fixes

### Fix 1: Add `/api/parameters` Endpoint to Azure Function

**Priority**: 🔴 **CRITICAL**

**File**: `azure-function/function_app.py`

**Implementation**:

```python
import base64
import hashlib

# Static mock certificate (same as in submit_signed_contract.py)
MOCK_CERTIFICATE_DER = b'0\x82\x03m0\x82\x02U...'  # Full certificate bytes

@app.route(route="parameters", methods=["GET"])
def get_parameters(req: func.HttpRequest) -> func.HttpResponse:
    """
    Return mock service parameters for blob storage backend.

    This endpoint is required by demo scripts and depa-training workflows
    to establish the trust store for contract validation.

    Response format matches CCF /parameters endpoint:
    {
      "serviceId": "mock-blob-storage-service",
      "treeAlgorithm": "CCF",
      "signatureAlgorithm": "ES256",
      "serviceCertificate": "MIIDbTCCA..."
    }

    Note: These are mock parameters for training/demo purposes only.
    The certificate and receipts do not provide cryptographic guarantees.
    """
    logging.info('Serving mock service parameters')

    # Calculate service ID (SHA256 hash of certificate, like CCF does)
    service_id_hash = hashlib.sha256(MOCK_CERTIFICATE_DER).hexdigest()

    # Encode certificate as base64
    service_cert_b64 = base64.b64encode(MOCK_CERTIFICATE_DER).decode('ascii')

    parameters = {
        "serviceId": service_id_hash,  # Or use "mock-blob-storage-service" for consistency
        "treeAlgorithm": "CCF",
        "signatureAlgorithm": "ES256",
        "serviceCertificate": service_cert_b64
    }

    return func.HttpResponse(
        json.dumps(parameters),
        status_code=200,
        mimetype="application/json"
    )
```

**Alternative (simpler)**: Return static JSON that matches `mock_trust_store/mock-blob-storage-service.json`:

```python
@app.route(route="parameters", methods=["GET"])
def get_parameters(req: func.HttpRequest) -> func.HttpResponse:
    """Return mock service parameters matching mock trust store."""
    logging.info('Serving mock service parameters')

    # Must match mock_trust_store/mock-blob-storage-service.json
    parameters = {
        "serviceId": "mock-blob-storage-service",
        "treeAlgorithm": "CCF",
        "signatureAlgorithm": "ES256",
        "serviceCertificate": "MIIDbTCCAlWgAwIBAgIUbJxM0IiQXOZ+J/NBUPGurMhWZoswDQYJKoZIhvcNAQELBQAwRjELMAkGA1UEBhMCVVMxGzAZBgNVBAoMEk1vY2sgU0NJVFQgU2VydmljZTEaMBgGA1UEAwwRYmxvYi1zdG9yYWdlLW1vY2swHhcNMjUxMTAzMDk1NTQ4WhcNMjYxMTAzMDk1NTQ4WjBGMQswCQYDVQQGEwJVUzEbMBkGA1UECgwSTW9jayBTQ0lUVCBTZXJ2aWNlMRowGAYDVQQDDBFibG9iLXN0b3JhZ2UtbW9jazCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBAJtX6qCdhXqS0PwU+y1uLlBWRkk1o8IqoQHsJhzymNHCkA2zpKZyXxhzySDmfqO8+X60Um5IBPY71BnwriSurAcv4vSg646adpP9zLKH7Fud+K3EG1XPBRH3YtMpzzIbezESECO2/6IlKKs1zJ8FcLAxLvguNd3FigU6Voh/2UaTNStnvP4xsYd03C5ztb67hgaGUIt5SbkMitkQNx63/1raBSkDkKhF0Y6VosHnvNbLno2nTihs4DRt6CRchaZR+6zJv4cqXdKuNkK0mE8B2Vkm+S1t7MuO0UtrxEpxjgrB+aKmkGJfrsUXhymDavXi+Gyxi2vfFyMXdGIv9JLIoFcCAwEAAaNTMFEwHQYDVR0OBBYEFCJ3XQGxYHgoJzUs3iy4wxmx5EuWMB8GA1UdIwQYMBaAFCJ3XQGxYHgoJzUs3iy4wxmx5EuWMA8GA1UdEwEB/wQFMAMBAf8wDQYJKoZIhvcNAQELBQADggEBABsUVMQg5RyZbetLjn6XjQJRsT/yQqyvlx9RYIeWr8jhKAp2PxhJNoamdMhYuntVgj6jRqfLX7twR2+nBLYJVYfqU3mb5rnmH708QjO0tbvgDuB7fqMOsZ1cogQk+7BvI15Nq1+9DZCW8iNNCU/BtcVLDSO4t+2ZBpiDDZ+u71yhr1iGtCvp1HAiXyDnqdkT1djud6I86GyTRHzbDjqdZ2IAgA35O1gFlPe478MKWYoGp/dQ5Zvdw3qvMH1r3SlakxZ0dMesFWaRQpkHgcPMD/DoFGH9c8p7u+vcSefu2fQtxwkwVFCnppSomJecpm7hW/VUQKJUMacmKXVTUGEL6XM="
    }

    return func.HttpResponse(
        json.dumps(parameters),
        status_code=200,
        mimetype="application/json"
    )
```

**Testing**:
```bash
# After deployment
curl https://my-function.azurewebsites.net/api/parameters | jq .

# Expected output:
{
  "serviceId": "mock-blob-storage-service",
  "treeAlgorithm": "CCF",
  "signatureAlgorithm": "ES256",
  "serviceCertificate": "MIIDbTCCA..."
}
```

---

### Fix 2: Update BLOB_STORAGE_BACKEND.md

**Priority**: 🟡 **HIGH**

**Changes Needed**:

1. **Clarify URL Pattern**:

```markdown
## Environment Variables

### For Blob Storage Mode

| Variable | Description | Example |
|----------|-------------|---------|
| `PYSCITT_BACKEND` | Backend selection | `blob` |
| `PYSCITT_BLOB_SERVICE_URL` | Function base URL | `https://my-func.azurewebsites.net` |
| `CONTRACT_URL` | **Include /api/ prefix!** | `https://my-func.azurewebsites.net/api` ⚠️ |

**IMPORTANT**: When using blob storage mode with demo scripts, set:
\`\`\`bash
export PYSCITT_BACKEND=blob
export PYSCITT_BLOB_SERVICE_URL=https://your-function.azurewebsites.net
export CONTRACT_URL=${PYSCITT_BLOB_SERVICE_URL}/api  # ← Note the /api/ suffix!
\`\`\`

**Why**: Azure Functions routes are under `/api/` by default. Demo scripts call
`$CONTRACT_URL/parameters` which becomes `/api/parameters`.
```

2. **Add Parameters Endpoint Section**:

```markdown
## Azure Function Endpoints

### GET /api/parameters

Returns mock service parameters for establishing trust store.

**Request**:
\`\`\`bash
curl https://your-function.azurewebsites.net/api/parameters
\`\`\`

**Response**:
\`\`\`json
{
  "serviceId": "mock-blob-storage-service",
  "treeAlgorithm": "CCF",
  "signatureAlgorithm": "ES256",
  "serviceCertificate": "MIIDbTCCA..."
}
\`\`\`

**Purpose**: Used by:
- Demo setup scripts (`1-contract-setup.sh`)
- depa-training resource provisioning (`3-import-keys.sh`)
- depa-training CCR deployment (`deploy.sh`)

**Note**: Returns static mock parameters. Certificate matches receipts generated
by `/api/submit` endpoint.
```

3. **Update Usage Examples**:

```markdown
## Quick Start

### 1. Setup Trust Store

\`\`\`bash
export PYSCITT_BACKEND=blob
export PYSCITT_BLOB_SERVICE_URL=https://your-function.azurewebsites.net
export CONTRACT_URL=${PYSCITT_BLOB_SERVICE_URL}/api  # ← Include /api/!

mkdir -p tmp/trust_store
curl -k -f ${CONTRACT_URL}/parameters > tmp/trust_store/scitt.json
\`\`\`

### 2. Submit Contract

\`\`\`bash
scitt submit-signed-contract contract.cose --receipt receipt.cbor
\`\`\`

### 3. Validate Contract

\`\`\`bash
scitt validate-contract contract.cose \
    --receipt receipt.cbor \
    --service-trust-store tmp/trust_store
\`\`\`

**Expected**: Receipt parses correctly, but cryptographic verification fails (intentional - mock signatures).
```

---

### Fix 3: Update azure-function/README.md

**Priority**: 🟡 **HIGH**

**Add Endpoints Section**:

```markdown
## Function Endpoints

### POST /api/submit

Submit a contract to blob storage with atomic sequence numbering.

**Request**:
- Method: POST
- Content-Type: application/cose
- Body: COSE-encoded contract data

**Response** (200 OK):
\`\`\`json
{
  "entryId": "2.15",
  "sequenceNumber": 15,
  "timestamp": 1234567890
}
\`\`\`

### GET /api/parameters

Get mock service parameters for trust store setup.

**Request**:
- Method: GET
- No body required

**Response** (200 OK):
\`\`\`json
{
  "serviceId": "mock-blob-storage-service",
  "treeAlgorithm": "CCF",
  "signatureAlgorithm": "ES256",
  "serviceCertificate": "MIIDbTCCA..."
}
\`\`\`

**Purpose**: Allows demo scripts and depa-training workflows to download service
parameters for trust store initialization.

### GET /api/health

Health check endpoint.

**Response** (200 OK):
\`\`\`json
{
  "status": "healthy",
  "container": "contracts"
}
\`\`\`

## Testing Endpoints

After deployment, test all endpoints:

\`\`\`bash
FUNCTION_URL=https://your-function.azurewebsites.net

# Test parameters endpoint
curl ${FUNCTION_URL}/api/parameters | jq .

# Test health endpoint
curl ${FUNCTION_URL}/api/health | jq .

# Test submit endpoint (requires .cose file)
curl -X POST ${FUNCTION_URL}/api/submit \
     -H "Content-Type: application/cose" \
     --data-binary @contract.cose | jq .
\`\`\`
```

---

### Fix 4: Create Test Script

**Priority**: 🟢 **MEDIUM**

**File**: `test_blob_storage_parameters.sh`

```bash
#!/bin/bash
# Test blob storage backend parameters endpoint

set -e

FUNCTION_URL=${PYSCITT_BLOB_SERVICE_URL:-"https://your-function.azurewebsites.net"}

echo "Testing blob storage backend parameters..."
echo "Function URL: $FUNCTION_URL"
echo

# Test 1: Parameters endpoint
echo "1. Testing GET /api/parameters..."
RESPONSE=$(curl -s -f ${FUNCTION_URL}/api/parameters)
echo "$RESPONSE" | jq .

# Validate response structure
echo "   Validating response..."
SERVICE_ID=$(echo "$RESPONSE" | jq -r '.serviceId')
TREE_ALG=$(echo "$RESPONSE" | jq -r '.treeAlgorithm')
SIG_ALG=$(echo "$RESPONSE" | jq -r '.signatureAlgorithm')
CERT=$(echo "$RESPONSE" | jq -r '.serviceCertificate')

if [ "$SERVICE_ID" = "null" ] || [ -z "$SERVICE_ID" ]; then
    echo "   ❌ FAIL: serviceId missing or null"
    exit 1
fi

if [ "$TREE_ALG" != "CCF" ]; then
    echo "   ❌ FAIL: treeAlgorithm must be 'CCF', got '$TREE_ALG'"
    exit 1
fi

if [ "$SIG_ALG" != "ES256" ]; then
    echo "   ❌ FAIL: signatureAlgorithm must be 'ES256', got '$SIG_ALG'"
    exit 1
fi

if [ "$CERT" = "null" ] || [ -z "$CERT" ]; then
    echo "   ❌ FAIL: serviceCertificate missing or null"
    exit 1
fi

echo "   ✅ PASS: Response structure valid"
echo

# Test 2: Save to trust store
echo "2. Testing trust store creation..."
mkdir -p tmp/trust_store_test
echo "$RESPONSE" > tmp/trust_store_test/scitt.json
echo "   ✅ Saved to tmp/trust_store_test/scitt.json"
echo

# Test 3: Validate with Python
echo "3. Testing Python ServiceParameters.from_dict()..."
python3 <<EOF
import json
import base64
import sys

with open('tmp/trust_store_test/scitt.json') as f:
    data = json.load(f)

# Test field access
try:
    tree_alg = data['treeAlgorithm']
    sig_alg = data['signatureAlgorithm']
    cert_b64 = data['serviceCertificate']
    service_id = data['serviceId']

    # Test base64 decode
    cert_der = base64.b64decode(cert_b64)

    print(f"   ✅ All fields present")
    print(f"   ✅ Certificate decodes ({len(cert_der)} bytes)")

except KeyError as e:
    print(f"   ❌ FAIL: Missing field {e}")
    sys.exit(1)
except Exception as e:
    print(f"   ❌ FAIL: {e}")
    sys.exit(1)
EOF

echo
echo "========================================="
echo "✅ ALL TESTS PASSED"
echo "========================================="
```

---

### Fix 5: Alternative - Static Blob Approach

**Priority**: 🟢 **LOW** (Alternative to Fix 1)

**Option**: Instead of adding endpoint to Function, upload static `parameters` blob.

**Steps**:

1. Create `parameters.json`:
```json
{
  "serviceId": "mock-blob-storage-service",
  "treeAlgorithm": "CCF",
  "signatureAlgorithm": "ES256",
  "serviceCertificate": "MIIDbTCCA..."
}
```

2. Upload to blob storage:
```bash
az storage blob upload \
  --account-name mystorageaccount \
  --container-name contracts \
  --name parameters \
  --file parameters.json \
  --content-type "application/json"
```

3. Make blob publicly readable (or use SAS token):
```bash
az storage container set-permission \
  --name contracts \
  --public-access blob \
  --account-name mystorageaccount
```

4. Update documentation:
```bash
# For blob storage mode, use blob storage URL directly
export CONTRACT_URL=https://mystorageaccount.blob.core.windows.net/contracts
curl ${CONTRACT_URL}/parameters
```

**Pros**:
- No Function code changes needed
- Parameters served directly from storage (fast, cheap)
- Can update parameters without redeploying Function

**Cons**:
- Requires public blob access or SAS tokens
- Different URL pattern than Function endpoints
- More complex to explain to users

**Recommendation**: Prefer Fix 1 (add endpoint to Function) for consistency.

---

## Step 11: Deployment Checklist

### Pre-Deployment

- [ ] Add `/api/parameters` endpoint to `function_app.py`
- [ ] Include `MOCK_CERTIFICATE_DER` in Function code
- [ ] Test endpoint locally with Azure Functions Core Tools
- [ ] Update `azure-function/README.md` with endpoint documentation
- [ ] Update `BLOB_STORAGE_BACKEND.md` with URL pattern guidance

### Deployment

- [ ] Deploy Function with new endpoint
- [ ] Test `/api/parameters` endpoint: `curl https://your-func.azurewebsites.net/api/parameters | jq .`
- [ ] Verify response has all 4 required fields (serviceId, treeAlgorithm, signatureAlgorithm, serviceCertificate)
- [ ] Test `/api/submit` still works
- [ ] Test `/api/health` still works

### Post-Deployment Testing

- [ ] Run `demo/contract/1-contract-setup.sh` with blob mode
  ```bash
  export PYSCITT_BACKEND=blob
  export CONTRACT_URL=https://your-func.azurewebsites.net/api
  ./demo/contract/1-contract-setup.sh
  ```
- [ ] Verify `tmp/trust_store/scitt.json` created
- [ ] Verify JSON contents match Function response
- [ ] Test submit contract with receipt
- [ ] Test validate contract (expect crypto failure - OK)
- [ ] Test retrieve contracts

### Documentation Updates

- [ ] Add parameters endpoint to Function README
- [ ] Update BLOB_STORAGE_BACKEND.md with URL pattern
- [ ] Add troubleshooting section for 404 errors
- [ ] Update mock_trust_store/README.md if needed
- [ ] Create test script for parameters endpoint

---

## Step 12: Testing Strategy

### Unit Tests (Python)

```python
# test_service_parameters.py
import json
import base64
from pyscitt.verify import ServiceParameters

def test_parameters_from_dict():
    """Test ServiceParameters.from_dict() with mock data."""
    data = {
        "serviceId": "mock-blob-storage-service",
        "treeAlgorithm": "CCF",
        "signatureAlgorithm": "ES256",
        "serviceCertificate": "MIIDbTCCA..."  # base64 cert
    }

    params = ServiceParameters.from_dict(data)

    assert params.service_id == "mock-blob-storage-service"
    assert params.tree_algorithm == "CCF"
    assert params.signature_algorithm == "ES256"
    assert isinstance(params.certificate, bytes)
    assert len(params.certificate) > 0

def test_trust_store_load():
    """Test StaticTrustStore.load() with mock data."""
    from pathlib import Path
    from pyscitt.verify import StaticTrustStore

    store = StaticTrustStore.load(Path("./mock_trust_store"))

    assert "mock-blob-storage-service" in store.services
    params = store.services["mock-blob-storage-service"]
    assert params.tree_algorithm == "CCF"
```

### Integration Tests (Bash)

```bash
#!/bin/bash
# test_blob_storage_workflow.sh

set -e

FUNCTION_URL=https://your-function.azurewebsites.net/api
export PYSCITT_BACKEND=blob
export PYSCITT_BLOB_SERVICE_URL=${FUNCTION_URL%/api}
export CONTRACT_URL=$FUNCTION_URL

echo "Testing complete blob storage workflow..."

# Step 1: Download parameters
mkdir -p tmp/test_trust_store
curl -k -f ${CONTRACT_URL}/parameters > tmp/test_trust_store/scitt.json
echo "✅ Parameters downloaded"

# Step 2: Verify JSON structure
jq -e '.serviceId' tmp/test_trust_store/scitt.json > /dev/null
jq -e '.treeAlgorithm' tmp/test_trust_store/scitt.json > /dev/null
jq -e '.signatureAlgorithm' tmp/test_trust_store/scitt.json > /dev/null
jq -e '.serviceCertificate' tmp/test_trust_store/scitt.json > /dev/null
echo "✅ JSON structure valid"

# Step 3: Submit contract (requires existing .cose file)
if [ -f "test_contract.cose" ]; then
    scitt submit-signed-contract test_contract.cose --receipt test_receipt.cbor
    echo "✅ Contract submitted"

    # Step 4: Validate contract
    scitt validate-contract test_contract.cose \
        --receipt test_receipt.cbor \
        --service-trust-store tmp/test_trust_store || true
    echo "⚠️  Validation attempted (expect crypto failure - this is OK)"
else
    echo "⚠️  Skipping submit/validate (no test_contract.cose found)"
fi

echo "✅ Workflow test complete"
```

### Manual Testing

1. **Test parameters endpoint**:
   ```bash
   curl https://your-func.azurewebsites.net/api/parameters | jq .
   ```

2. **Test with demo scripts**:
   ```bash
   cd demo/contract
   export PYSCITT_BACKEND=blob
   export CONTRACT_URL=https://your-func.azurewebsites.net/api
   ./1-contract-setup.sh
   ls -la tmp/trust_store/scitt.json  # Should exist
   ```

3. **Test depa-training pattern**:
   ```bash
   export CONTRACT_SERVICE_URL=https://your-func.azurewebsites.net/api
   export CONTRACT_SERVICE_PARAMETERS=$(curl -k -f ${CONTRACT_SERVICE_URL}/parameters | base64 --wrap=0)
   echo $CONTRACT_SERVICE_PARAMETERS | base64 -d | jq .  # Should show valid JSON
   ```

---

## Conclusion

### Critical Finding

**The Azure Function is missing the `/api/parameters` GET endpoint**, which is a **blocking issue** for blob storage backend integration with depa-training and demo workflows.

### Required Actions

1. **IMMEDIATE**: Add `/api/parameters` endpoint to Azure Function
2. **HIGH**: Update documentation with correct URL patterns (`/api/` prefix)
3. **MEDIUM**: Create test scripts for parameters endpoint
4. **MEDIUM**: Update deployment documentation

### Success Criteria

✅ `curl https://function.azurewebsites.net/api/parameters` returns valid JSON
✅ `demo/contract/1-contract-setup.sh` completes successfully with blob mode
✅ Trust store file `tmp/trust_store/scitt.json` is created
✅ Parameters match mock trust store certificate
✅ Complete workflow (submit → retrieve → validate) works end-to-end

### Timeline Estimate

| Task | Effort | Priority |
|------|--------|----------|
| Add `/api/parameters` endpoint | 30 min | 🔴 Critical |
| Test endpoint locally | 15 min | 🔴 Critical |
| Deploy to Azure | 10 min | 🔴 Critical |
| Update documentation | 45 min | 🟡 High |
| Create test scripts | 30 min | 🟢 Medium |
| **Total** | **~2 hours** | |

---

## Appendix A: Reference Files

### Files Analyzed

- `demo/contract/1-contract-setup.sh` - Parameters download
- `demo/contract/8-retrieve-contract.sh` - Trust store usage
- `pyscitt/pyscitt/verify.py` - ServiceParameters class
- `pyscitt/pyscitt/client.py` - get_parameters() method
- `azure-function/function_app.py` - Function endpoints
- `mock_trust_store/mock-blob-storage-service.json` - Mock parameters
- `app/src/service_endpoints.h` - CCF parameters implementation
- `app/src/call_types.h` - ServiceParameters JSON structure

### Key Code Locations

| Component | File | Lines |
|-----------|------|-------|
| ServiceParameters.from_dict() | `pyscitt/pyscitt/verify.py` | 33-42 |
| StaticTrustStore.load() | `pyscitt/pyscitt/verify.py` | 142-163 |
| Client.get_parameters() | `pyscitt/pyscitt/client.py` | - |
| CCF certificate_to_service_parameters() | `app/src/service_endpoints.h` | - |
| Demo parameters download | `demo/contract/1-contract-setup.sh` | 33 |
| Function endpoints | `azure-function/function_app.py` | 116, 236 |

### Environment Variables Reference

| Variable | Purpose | Example |
|----------|---------|---------|
| `PYSCITT_BACKEND` | Backend selection | `blob` |
| `PYSCITT_BLOB_SERVICE_URL` | Function base URL | `https://func.azure.net` |
| `CONTRACT_URL` | Service URL (include `/api/` for blob) | `https://func.azure.net/api` |
| `CONTRACT_SERVICE_URL` | depa-training service URL | `https://func.azure.net/api` |
| `CONTRACT_SERVICE_PARAMETERS` | Base64 parameters (depa) | `eyJzZXJ2aWNl...` |
| `ContractServiceParameters` | Container env var (depa) | `eyJzZXJ2aWNl...` |
| `TRUST_STORE` | Trust store directory | `tmp/trust_store` |

---

**END OF REPORT**

**Next Steps**: Implement Fix 1 (add `/api/parameters` endpoint) and Fix 2 (update documentation).

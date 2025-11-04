# Co-Signing Workflow Verification

## Question
When TDC submits a co-signed contract, does the blob storage backend properly:
1. ✅ Get a **new** entryId (2.16 instead of 2.15)?
2. ✅ Store it as a **separate** blob?
3. ✅ Keep **both** 2.15.cose (TDP only) and 2.16.cose (TDP+TDC) in storage?

## Answer: YES ✅

The blob storage implementation correctly handles co-signing by treating each submission as a **new contract** with a **unique sequence number**.

---

## Co-Signing Flow Step-by-Step

### Step 1: TDP Submits Initial Contract

**Script:** `demo/contract/4-register-contract.sh`

```bash
scitt submit-contract $TMP_DIR/contract.cose \
    --receipt $TMP_DIR/contract.receipt.cbor \
    --url $CONTRACT_URL
```

**Azure Function Processing** (`function_app.py:195-208`):

```python
# 1. Acquire lease on sequence counter
sequence_number = get_next_sequence_number_atomic(container_client)
# Counter: 14 → 15

# 2. Generate contract ID
contract_id = f"2.{sequence_number}"
# Result: "2.15"

# 3. Upload to blob storage
blob_name = f"{contract_id}.cose"
# Result: "2.15.cose"

blob_client.upload_blob(contract_data, overwrite=False)
# Stores TDP's single-signature contract
```

**Response:**
```json
{
    "entryId": "2.15",
    "sequenceNumber": 15,
    "timestamp": 1234567890
}
```

**Blob Storage State:**
```
contracts/
  ├── _sequence_counter.txt  (contains: "15")
  └── 2.15.cose              (TDP signature only)
```

---

### Step 2: TDC Retrieves TDP's Contract

**Script:** `demo/contract/8-retrieve-contract.sh`

```bash
scitt retrieve-contracts ./tmp/contracts \
    --url $CONTRACT_URL \
    --from 15 \
    --to 15
```

**Blob Storage Operation:**
- Downloads `2.15.cose` from blob storage
- Saves locally as `tmp/contracts/2.15.cose`

**Contract Contents:**
- COSE Sign structure with **1 signature** (TDP's signature)
- Protected headers include `participant_info` listing TDC as allowed co-signer

---

### Step 3: TDC Adds Signature Locally

**Script:** `demo/contract/9-sign-contract.sh`

```bash
scitt sign-contract \
    --contract tmp/contracts/2.15.cose \
    --content-type "application/cose" \
    --did-doc $TMP_DIR1/did.json \
    --key $TMP_DIR1/key.pem \
    --out $TMP_DIR1/contract.cose \
    --add-signature    # ← Key flag!
```

**Local Operation** (`crypto.py:765-771`):
```python
if add_signature:
    msg = SignMessage.decode(contract)
    signers = msg.signers
    signers.append(CoseSignature(phdr=signature_headers, key=...))
    msg.signers = signers
    return msg.encode(tag=True)
```

**Result:**
- `$TMP_DIR1/contract.cose` now has **2 signatures**:
  1. TDP's original signature
  2. TDC's new signature
- This is a **different COSE structure** than the original

---

### Step 4: TDC Submits Co-Signed Contract

**Script:** `demo/contract/10-register-contract.sh`

```bash
scitt submit-contract $TMP_DIR/contract.cose \
    --receipt $TMP_DIR/contract.receipt.cbor \
    --url $CONTRACT_URL
```

**Azure Function Processing** (`function_app.py:195-208`):

```python
# 1. Receive co-signed contract (2 signatures)
contract_data = req.get_body()
# Contains TDP + TDC signatures

# 2. Acquire lease on sequence counter
sequence_number = get_next_sequence_number_atomic(container_client)
# Counter: 15 → 16   ← NEW SEQUENCE NUMBER!

# 3. Generate contract ID
contract_id = f"2.{sequence_number}"
# Result: "2.16"   ← NEW CONTRACT ID!

# 4. Upload to blob storage
blob_name = f"{contract_id}.cose"
# Result: "2.16.cose"   ← NEW BLOB NAME!

blob_client.upload_blob(contract_data, overwrite=False)
# Stores co-signed contract as SEPARATE blob
```

**Critical Code** (`function_app.py:215`):
```python
blob_client.upload_blob(contract_data, overwrite=False)
#                                      ^^^^^^^^^^^^^^
# overwrite=False ensures we DON'T replace existing blobs
```

**Response:**
```json
{
    "entryId": "2.16",      ← NEW ID!
    "sequenceNumber": 16,    ← NEW SEQUENCE!
    "timestamp": 1234567891
}
```

**Blob Storage State After Co-Signing:**
```
contracts/
  ├── _sequence_counter.txt  (contains: "16")
  ├── 2.15.cose              (TDP signature only) ✅ STILL EXISTS
  └── 2.16.cose              (TDP + TDC signatures) ✅ NEW BLOB
```

---

## Key Design Properties

### 1. Every Submission Gets New Sequence Number

**Atomic Counter Increment** (`function_app.py:42-102`):
```python
def get_next_sequence_number_atomic(container_client) -> int:
    lease = blob_client.acquire_lease(lease_duration=15)

    # Read current value
    current_value = int(download_stream.readall().decode('utf-8'))

    # Increment
    next_sequence = current_value + 1

    # Write back
    blob_client.upload_blob(str(next_sequence), overwrite=True, lease=lease)

    return next_sequence
```

**Result:** Each POST request increments counter, no exceptions.

### 2. No Content Deduplication

The Azure Function does **NOT** check:
- ❌ If contract content already exists
- ❌ If contract is similar to previous submission
- ❌ If contract has same claims/payload

Every submission is treated as **unique** and gets a **new ID**.

### 3. Separate Blob Storage

```python
blob_name = f"{contract_id}.cose"
# 2.15.cose → TDP version
# 2.16.cose → Co-signed version

blob_client.upload_blob(contract_data, overwrite=False)
# Creates NEW blob, doesn't replace existing
```

### 4. Historical Preservation

**Both versions are preserved:**
- `2.15.cose` - Original contract with TDP signature
- `2.16.cose` - Co-signed contract with TDP + TDC signatures

This creates an **audit trail** of contract evolution:
1. `2.15` - Initial submission (1 signature)
2. `2.16` - Co-signed submission (2 signatures)

---

## Comparison with CCF Behavior

| Aspect | CCF | Blob Storage | Match? |
|--------|-----|--------------|--------|
| **TDP submits** | Transaction 2.15 | Contract 2.15 | ✅ Yes |
| **TDC retrieves** | GET /entries/2.15 | Download 2.15.cose | ✅ Yes |
| **TDC adds signature** | Local operation | Local operation | ✅ Yes |
| **TDC submits** | Transaction 2.16 | Contract 2.16 | ✅ Yes |
| **New ID assigned** | Yes (consensus) | Yes (atomic counter) | ✅ Yes |
| **Both versions exist** | Yes (ledger history) | Yes (separate blobs) | ✅ Yes |
| **Independent retrieval** | GET /entries/2.15 or 2.16 | Download 2.15.cose or 2.16.cose | ✅ Yes |

**Conclusion:** Blob storage **exactly matches** CCF co-signing behavior!

---

## Verification Test

### Manual Test Script

```bash
#!/bin/bash
# Test co-signing workflow with blob storage

export PYSCITT_BACKEND=blob
export CONTRACT_URL=https://myfunction.azurewebsites.net/api
export PYSCITT_BLOB_SERVICE_URL=https://myfunction.azurewebsites.net

# 1. TDP submits contract
echo "=== TDP Submission ==="
scitt submit-contract tdp/contract.cose --receipt tdp/receipt.cbor
# Expected output: "Submitted ... as contract 2.15"

# 2. Verify blob exists
az storage blob list --container-name contracts --prefix "2.15"
# Expected: 2.15.cose exists

# 3. TDC retrieves contract
echo "=== TDC Retrieval ==="
scitt retrieve-contracts ./retrieved --from 15 --to 15
# Expected: Downloaded 2.15.cose

# 4. TDC adds signature
echo "=== TDC Co-Signing ==="
scitt sign-contract \
    --contract retrieved/2.15.cose \
    --content-type "application/cose" \
    --did-doc tdc/did.json \
    --key tdc/key.pem \
    --out tdc/contract.cose \
    --add-signature

# 5. TDC submits co-signed contract
echo "=== TDC Submission ==="
scitt submit-contract tdc/contract.cose --receipt tdc/receipt.cbor
# Expected output: "Submitted ... as contract 2.16"

# 6. Verify both blobs exist
echo "=== Verification ==="
az storage blob list --container-name contracts --prefix "2."
# Expected:
#   - 2.15.cose (TDP only)
#   - 2.16.cose (TDP + TDC)

# 7. Retrieve both and compare
scitt retrieve-contracts ./final --from 15 --to 16
# Expected: Downloaded 2.15.cose and 2.16.cose

# 8. Compare signature counts
echo "=== Signature Comparison ==="
python3 <<EOF
from pyscitt.crypto import parse_cose_sign

# TDP version
with open('final/2.15.cose', 'rb') as f:
    msg1 = parse_cose_sign(f.read())
    print(f"2.15 signatures: {len(msg1.signers)}")  # Expected: 1

# Co-signed version
with open('final/2.16.cose', 'rb') as f:
    msg2 = parse_cose_sign(f.read())
    print(f"2.16 signatures: {len(msg2.signers)}")  # Expected: 2
EOF
```

### Expected Results

```
=== TDP Submission ===
Submitted tdp/contract.cose to blob storage as contract 2.15

=== TDC Retrieval ===
Retrieved contract: 2.15
Downloaded: ./retrieved/2.15.cose

=== TDC Co-Signing ===
Added signature to contract

=== TDC Submission ===
Submitted tdc/contract.cose to blob storage as contract 2.16

=== Verification ===
2.15.cose (TDP signature only)
2.16.cose (TDP + TDC signatures)

=== Signature Comparison ===
2.15 signatures: 1
2.16 signatures: 2
```

---

## Why This Design is Correct

### 1. Matches CCF Semantics

CCF treats co-signed contracts as **new transactions** with **new IDs**:
- Original: Transaction 2.15
- Co-signed: Transaction 2.16

Blob storage does the same:
- Original: Contract 2.15
- Co-signed: Contract 2.16

### 2. Preserves History

Both versions exist independently:
- Users can retrieve TDP-only version (`2.15`)
- Users can retrieve co-signed version (`2.16`)
- Audit trail shows contract evolution

### 3. Avoids Conflicts

Using `overwrite=False` prevents:
- ❌ Accidentally replacing existing contracts
- ❌ Losing original signatures
- ❌ Breaking retrieval references

### 4. Simple Implementation

No need for:
- ❌ Content-based deduplication
- ❌ Version tracking metadata
- ❌ Complex conflict resolution

Each submission is independent and atomic.

---

## Edge Cases Handled

### Q: What if TDC submits the same co-signed contract twice?

**A:** Each submission gets a **new sequence number**:
- First submission: `2.16`
- Second submission: `2.17`

Both blobs are stored (identical content, different IDs).

This matches CCF behavior (duplicate submissions create new transactions).

### Q: What if two TDCs try to co-sign simultaneously?

**A:** Both get **different sequence numbers**:
- TDC1 submission: `2.16` (TDP + TDC1)
- TDC2 submission: `2.17` (TDP + TDC2)

The atomic counter ensures no collisions.

### Q: Can we retrieve the original contract after co-signing?

**A:** **Yes!** Both versions are preserved:
```bash
scitt retrieve-contracts ./contracts --from 15 --to 15  # Gets original
scitt retrieve-contracts ./contracts --from 16 --to 16  # Gets co-signed
```

### Q: What if someone submits a completely different contract with same payload?

**A:** Gets a **new ID** (e.g., `2.18`). The system doesn't deduplicate based on content.

---

## Summary

### ✅ Confirmed Behaviors

1. **New entryId:** TDC submission gets `2.16` (not `2.15`)
2. **Separate blob:** Creates `2.16.cose` (doesn't replace `2.15.cose`)
3. **Both preserved:** Storage contains both `2.15.cose` and `2.16.cose`
4. **Atomic increment:** Sequence counter atomically advances 15 → 16
5. **Independent retrieval:** Can download either version by ID
6. **Signature count:** `2.15` has 1 signature, `2.16` has 2 signatures
7. **CCF compatibility:** Behavior exactly matches CCF transaction semantics

### Why It Works

The Azure Function implementation:
- ✅ Calls `get_next_sequence_number_atomic()` for **every** submission
- ✅ Generates **unique** contract ID per submission
- ✅ Uses `overwrite=False` to prevent replacing existing blobs
- ✅ No content deduplication (treats each POST as new)
- ✅ Preserves historical versions in blob storage

### Code References

| Behavior | Code Location | Line |
|----------|---------------|------|
| Atomic increment | `function_app.py:get_next_sequence_number_atomic()` | 42-102 |
| New contract ID | `function_app.py:contract_id = f"2.{sequence_number}"` | 207 |
| Separate blob | `function_app.py:blob_name = f"{contract_id}.cose"` | 211 |
| No overwrite | `function_app.py:upload_blob(..., overwrite=False)` | 215 |
| Add signature | `crypto.py:sign_contract(..., add_signature=True)` | 765-771 |
| TDC submission | `demo/contract/10-register-contract.sh` | 12-16 |

---

## Conclusion

**The blob storage backend correctly implements co-signing semantics:**

- ✅ Each submission (including co-signed contracts) gets a **new unique ID**
- ✅ All versions are **preserved independently** in blob storage
- ✅ Behavior **exactly matches CCF** transaction semantics
- ✅ No data loss or overwriting occurs
- ✅ Full audit trail of contract evolution is maintained

**The co-signing workflow works correctly with blob storage backend!** 🎯

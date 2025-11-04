# Identifiers vs Service Parameters: Design Rationale

## The Question
Why do we have **dynamic scripts/code** to handle identifiers but **static JSON files** for service parameters?

## Answer: Different Data Lifecycles

| Aspect | **Identifiers (Contract IDs)** | **Service Parameters** |
|--------|--------------------------------|------------------------|
| **Nature** | Dynamic, per-request | Static, service-level |
| **Changes** | Every submission | Rarely (service lifetime) |
| **Uniqueness** | MUST be unique per contract | Shared across all contracts |
| **Concurrency** | Requires atomic operations | Read-only, no conflicts |
| **Generation** | Runtime (server-side) | Pre-generated (once) |
| **State** | Per-request state | Service identity |
| **Storage** | Computed + stored | Just stored |

---

## Part 1: Why Identifiers Need Dynamic Scripts

### Identifiers Are Per-Request State

Every contract submission needs a **unique identifier**:

```
Submission 1 → Contract ID: "2.1"
Submission 2 → Contract ID: "2.2"
Submission 3 → Contract ID: "2.3"
...
Submission N → Contract ID: "2.N"
```

**Key Property:** No two submissions can have the same ID.

### Requirements

1. **Uniqueness Guarantee**
   - Even under concurrent submissions
   - Even with network failures/retries
   - Even across Azure Function instances

2. **Atomic State Management**
   - Read current counter
   - Increment counter
   - Write new counter
   - All must happen atomically (no race conditions)

3. **Server-Side Logic**
   - Client CANNOT generate IDs (would cause conflicts)
   - Server MUST control ID assignment
   - Requires distributed locking (blob lease)

### Implementation: Azure Function + Atomic Counter

**Code:** `function_app.py:42-102`

```python
def get_next_sequence_number_atomic(container_client) -> int:
    """
    Atomically get and increment the sequence counter using blob lease.

    This ensures no two submissions get the same sequence number, even
    under concurrent access.
    """
    blob_client = container_client.get_blob_client(COUNTER_BLOB_NAME)

    # 1. ACQUIRE DISTRIBUTED LOCK (15-second lease)
    lease = blob_client.acquire_lease(lease_duration=15)

    try:
        # 2. READ CURRENT VALUE
        download_stream = blob_client.download_blob(lease=lease)
        current_value = int(download_stream.readall().decode('utf-8'))

        # 3. INCREMENT
        next_sequence = current_value + 1

        # 4. WRITE BACK ATOMICALLY
        blob_client.upload_blob(
            str(next_sequence),
            overwrite=True,
            lease=lease  # Only holder of lease can write
        )

        return next_sequence

    finally:
        # 5. RELEASE LOCK
        lease.release()
```

**Why This Complexity?**

Without atomic operations, this could happen:

```
Time  | Client A              | Client B              | Counter Value
------|-----------------------|-----------------------|--------------
T1    | Read counter: 15      |                       | 15
T2    |                       | Read counter: 15      | 15
T3    | Increment: 16         |                       | 15
T4    |                       | Increment: 16         | 15
T5    | Write: 16             |                       | 16
T6    |                       | Write: 16             | 16
      | Gets ID: 2.16         | Gets ID: 2.16         | ❌ COLLISION!
```

**With blob lease (atomic):**

```
Time  | Client A              | Client B              | Counter Value
------|-----------------------|-----------------------|--------------
T1    | Acquire lease ✅      |                       | 15
T2    |                       | Try acquire (blocked) | 15
T3    | Read: 15, Write: 16   |                       | 15 → 16
T4    | Release lease         |                       | 16
T5    | Gets ID: 2.16 ✅      |                       | 16
T6    |                       | Acquire lease ✅      | 16
T7    |                       | Read: 16, Write: 17   | 16 → 17
T8    |                       | Release lease         | 17
T9    |                       | Gets ID: 2.17 ✅      | 17
      | UNIQUE!               | UNIQUE!               | ✅ NO COLLISION
```

### Why JSON Alone Wouldn't Work

If we just used a static JSON file with a counter:

```json
{
  "nextSequenceNumber": 15
}
```

**Problems:**
1. ❌ No atomicity - race conditions
2. ❌ No distributed locking - concurrent overwrites
3. ❌ No server control - clients could manipulate
4. ❌ No retry safety - network failures cause duplicates

**Identifiers REQUIRE runtime logic with concurrency control.**

---

## Part 2: Why Service Parameters Use Static JSON

### Service Parameters Are Service Identity

Service parameters represent **who the service is**, not per-request state:

```json
{
  "serviceId": "mock-blob-storage-service",
  "treeAlgorithm": "CCF",
  "signatureAlgorithm": "ES256",
  "serviceCertificate": "MIIDbTCCA..."
}
```

**Key Property:** These values are the SAME for all contracts from this service.

### Characteristics

1. **Static Configuration**
   - Set once when service is deployed
   - Don't change per submission
   - Represent service's cryptographic identity

2. **Read-Only**
   - Clients download and cache
   - No writes needed
   - No concurrency issues

3. **Service Lifetime**
   - May change when service identity rotates (rare)
   - But stable across thousands of contract submissions
   - Changing these is a major service event

4. **Trust Store Entry**
   - Clients save to local trust store
   - Used to verify ALL receipts from this service
   - Part of "root of trust" establishment

### Why Static JSON Works Perfectly

**File:** `mock_trust_store/mock-blob-storage-service.json`

```json
{
  "serviceId": "mock-blob-storage-service",
  "treeAlgorithm": "CCF",
  "signatureAlgorithm": "ES256",
  "serviceCertificate": "MIIDbTCCA..."
}
```

**Advantages:**

1. ✅ **Simple** - No complex logic needed
2. ✅ **Portable** - Can be copied, shared, versioned
3. ✅ **Cacheable** - Download once, use forever (until rotation)
4. ✅ **Human-readable** - Easy to inspect and verify
5. ✅ **No concurrency issues** - Read-only access
6. ✅ **Standards-compliant** - Matches CCF `/parameters` format

### Service Parameters Don't Need Scripts Because

```
Contract 1 → Uses service params (from JSON)
Contract 2 → Uses service params (same JSON)
Contract 3 → Uses service params (same JSON)
...
Contract N → Uses service params (same JSON)
```

**Same data, reused N times. No dynamic generation needed.**

---

## Comparison Table

| Feature | Identifiers | Service Parameters |
|---------|-------------|-------------------|
| **Value Example** | `"2.15"`, `"2.16"`, `"2.17"` | `"mock-blob-storage-service"` |
| **Frequency of Change** | Every request | Once per service deployment |
| **Uniqueness Requirement** | Must be unique per contract | Same for all contracts |
| **Generation** | Azure Function at runtime | Pre-generated, stored as JSON |
| **Concurrency Control** | Blob lease (distributed lock) | None (read-only) |
| **Client Access** | Receives in POST response | Downloads via GET `/parameters` |
| **Storage** | Computed + stored per contract | Single JSON file for service |
| **State Type** | Per-request state | Service identity |
| **Code Complexity** | ~60 lines (atomic increment) | ~5 lines (return JSON) |
| **What Breaks If Wrong** | ID collisions, lost contracts | Verification fails, wrong trust |

---

## Real-World Analogy

### Identifiers = Order Numbers at Restaurant

**Dynamic Script/Logic:**

```
Customer 1 arrives → "Order #15" ← Assigned by POS system
Customer 2 arrives → "Order #16" ← Next number
Customer 3 arrives → "Order #17" ← Next number
```

**Why POS system (script) is needed:**
- Must ensure no duplicate order numbers
- Must handle concurrent orders (multiple cashiers)
- Must persist state (can't restart at #1 after reboot)
- Customers don't pick their own numbers (chaos!)

### Service Parameters = Restaurant Identity

**Static JSON:**

```json
{
  "restaurantName": "Bob's Burgers",
  "address": "123 Ocean Ave",
  "phone": "555-1234",
  "certificate": "Health Inspection: Grade A"
}
```

**Why JSON file works:**
- Restaurant identity doesn't change per order
- Same info on every receipt
- Can be printed on menu (cached)
- Only changes when restaurant moves (rare)

---

## Why Both Approaches Are Used Together

### Azure Function Endpoint: `/api/submit`

**Dynamic (requires script):**

```python
@app.route(route="submit", methods=["POST"])
def submit_contract(req: func.HttpRequest) -> func.HttpResponse:
    # DYNAMIC: Generate new unique ID
    sequence_number = get_next_sequence_number_atomic(container_client)
    contract_id = f"2.{sequence_number}"  # ← Different every time

    return func.HttpResponse(json.dumps({
        "entryId": contract_id  # ← Unique per request
    }))
```

### Azure Function Endpoint: `/api/parameters`

**Static (just return JSON):**

```python
@app.route(route="parameters", methods=["GET"])
def get_parameters(req: func.HttpRequest) -> func.HttpResponse:
    # STATIC: Return constant service identity
    return func.HttpResponse(
        json.dumps(MOCK_SERVICE_PARAMETERS)  # ← Same every time
    )
```

**Both are needed, but have different lifecycles.**

---

## Alternative Designs Considered

### Alternative 1: Generate Identifiers Client-Side?

**Problem:** Race conditions and collisions

```python
# Client 1
contract_id = generate_uuid()  # "abc123"
POST /api/submit with ID "abc123"

# Client 2 (concurrent)
contract_id = generate_uuid()  # "def456"
POST /api/submit with ID "def456"
```

**Issues:**
- ❌ Clients could generate same UUID (unlikely but possible)
- ❌ No ordering guarantee (can't retrieve by range)
- ❌ Can't ensure sequential numbering
- ❌ Clients could manipulate IDs maliciously

**Why CCF/Blob use server-assigned IDs:** Server controls ordering and uniqueness.

### Alternative 2: Generate Service Parameters Dynamically?

**Problem:** No benefit, adds complexity

```python
@app.route(route="parameters", methods=["GET"])
def get_parameters(req: func.HttpRequest) -> func.HttpResponse:
    # Unnecessarily complex:
    service_id = os.environ.get("SERVICE_ID")
    cert = load_certificate_from_keyvault()
    params = {
        "serviceId": service_id,
        "serviceCertificate": base64.b64encode(cert).decode()
    }
    return func.HttpResponse(json.dumps(params))
```

**Issues:**
- ❌ Adds latency (certificate loading per request)
- ❌ Increases failure points (KeyVault API)
- ❌ Harder to test (need full infrastructure)
- ❌ Same result every time anyway (waste)

**Why JSON is better:** Pre-compute once, serve fast.

### Alternative 3: Store Identifiers in JSON?

```json
{
  "usedIds": ["2.1", "2.2", "2.3", ..., "2.999999"]
}
```

**Problems:**
- ❌ File grows unbounded (GB+ after many submissions)
- ❌ No atomic read-modify-write guarantee
- ❌ Slow (must parse entire history)
- ❌ Doesn't scale to millions of contracts

**Why counter blob is better:** O(1) size, atomic operations.

---

## CCF Behavior (For Comparison)

### CCF Identifiers (Transaction IDs)

**Also dynamic, requires consensus:**

```cpp
// CCF internal logic (simplified)
std::string assign_transaction_id() {
    auto consensus = get_raft_consensus();

    // Atomic through Raft consensus
    auto view = consensus.get_current_view();
    auto seqno = consensus.get_next_seqno();

    return fmt::format("{}.{}", view, seqno);
}
```

**Properties:**
- Dynamic (changes per transaction)
- Requires distributed consensus (Raft)
- Atomic across nodes
- Server-assigned

### CCF Service Parameters

**Also static, returned from configuration:**

```cpp
// CCF endpoint (simplified)
GetServiceParameters::Out get_parameters() {
    auto config = load_service_configuration();

    return {
        .service_id = config.service_id,
        .tree_algorithm = "CCF",
        .signature_algorithm = "ES256",
        .service_certificate = config.service_cert
    };
}
```

**Properties:**
- Static (service configuration)
- Read from KV store
- Same for all transactions
- Returned as JSON

**Blob storage mirrors this design!**

---

## Summary

### Why Identifiers Need Scripts

1. ✅ **Must be unique** - Requires atomic counter
2. ✅ **Change per request** - Dynamic generation
3. ✅ **Concurrency control** - Distributed locking (blob lease)
4. ✅ **Server-assigned** - Prevents client manipulation
5. ✅ **State management** - Persistent counter storage

**Result:** Azure Function with 60 lines of logic for atomic increment.

### Why Service Parameters Use JSON

1. ✅ **Static configuration** - Doesn't change per request
2. ✅ **Service identity** - Same for all contracts
3. ✅ **Read-only** - No concurrency issues
4. ✅ **Cacheable** - Download once, use forever
5. ✅ **Simple** - No complex logic needed

**Result:** Single JSON file, 5 lines of code to serve it.

### Design Principle

```
Dynamic Data (per-request) → Requires scripts/logic
Static Data (per-service)  → Use JSON files
```

This separation of concerns:
- ✅ Keeps code simple where possible
- ✅ Adds complexity only where necessary
- ✅ Matches CCF architecture
- ✅ Follows principle of least complexity

---

## Code References

| Component | Type | Code Location | Complexity |
|-----------|------|---------------|------------|
| **Identifier generation** | Dynamic script | `function_app.py:42-102` | ~60 lines (atomic logic) |
| **Identifier assignment** | Dynamic script | `function_app.py:197-208` | Runtime per request |
| **Service parameters** | Static JSON | `function_app.py:33-38` | ~5 lines (constant) |
| **Parameters endpoint** | Static JSON | `function_app.py:249-286` | Just return constant |
| **Trust store file** | Static JSON | `mock_trust_store/*.json` | Pre-generated |

---

## Conclusion

**Different data types require different handling strategies:**

- **Identifiers** = Per-request state → Need atomic scripts
- **Service parameters** = Service identity → Use static JSON

This isn't arbitrary - it's driven by the fundamental nature of the data and its lifecycle. The design matches both CCF's architecture and standard distributed systems patterns.

**Right tool for the right job!** 🎯

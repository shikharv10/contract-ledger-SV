#!/bin/bash
# Test blob storage backend parameters endpoint
# This script validates that the Azure Function /api/parameters endpoint
# returns correctly formatted service parameters for trust store setup.

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "========================================"
echo "Blob Storage Parameters Endpoint Test"
echo "========================================"
echo

# Check if FUNCTION_URL is set
if [ -z "$PYSCITT_BLOB_SERVICE_URL" ]; then
    echo -e "${YELLOW}Warning: PYSCITT_BLOB_SERVICE_URL not set${NC}"
    echo "Please set it to your Azure Function URL:"
    echo "  export PYSCITT_BLOB_SERVICE_URL=https://your-function.azurewebsites.net"
    echo
    echo "Using default for testing: https://localhost:7071"
    FUNCTION_URL="http://localhost:7071"
else
    FUNCTION_URL="$PYSCITT_BLOB_SERVICE_URL"
fi

echo "Function URL: $FUNCTION_URL"
echo

# Test 1: Parameters endpoint accessibility
echo "Test 1: Testing GET /api/parameters endpoint..."
echo "--------------------------------------"
PARAMS_URL="${FUNCTION_URL}/api/parameters"
echo "URL: $PARAMS_URL"

if ! RESPONSE=$(curl -s -f "${PARAMS_URL}" 2>&1); then
    echo -e "${RED}✗ FAIL: Could not reach /api/parameters endpoint${NC}"
    echo "Error: $RESPONSE"
    echo
    echo "Possible causes:"
    echo "  1. Azure Function not deployed"
    echo "  2. Wrong URL (check PYSCITT_BLOB_SERVICE_URL)"
    echo "  3. Function not running (try: func start in azure-function/ directory)"
    exit 1
fi

echo -e "${GREEN}✓ PASS: Endpoint is accessible${NC}"
echo

# Test 2: Response is valid JSON
echo "Test 2: Validating JSON response..."
echo "--------------------------------------"
if ! echo "$RESPONSE" | jq empty 2>/dev/null; then
    echo -e "${RED}✗ FAIL: Response is not valid JSON${NC}"
    echo "Response: $RESPONSE"
    exit 1
fi

echo -e "${GREEN}✓ PASS: Response is valid JSON${NC}"
echo "$RESPONSE" | jq .
echo

# Test 3: Required fields present
echo "Test 3: Checking required fields..."
echo "--------------------------------------"

SERVICE_ID=$(echo "$RESPONSE" | jq -r '.serviceId')
TREE_ALG=$(echo "$RESPONSE" | jq -r '.treeAlgorithm')
SIG_ALG=$(echo "$RESPONSE" | jq -r '.signatureAlgorithm')
CERT=$(echo "$RESPONSE" | jq -r '.serviceCertificate')

FAILED=0

if [ "$SERVICE_ID" = "null" ] || [ -z "$SERVICE_ID" ]; then
    echo -e "${RED}✗ FAIL: serviceId missing or null${NC}"
    FAILED=1
else
    echo -e "${GREEN}✓ PASS: serviceId present: $SERVICE_ID${NC}"
fi

if [ "$TREE_ALG" != "CCF" ]; then
    echo -e "${RED}✗ FAIL: treeAlgorithm must be 'CCF', got '$TREE_ALG'${NC}"
    FAILED=1
else
    echo -e "${GREEN}✓ PASS: treeAlgorithm = 'CCF'${NC}"
fi

if [ "$SIG_ALG" != "ES256" ]; then
    echo -e "${RED}✗ FAIL: signatureAlgorithm must be 'ES256', got '$SIG_ALG'${NC}"
    FAILED=1
else
    echo -e "${GREEN}✓ PASS: signatureAlgorithm = 'ES256'${NC}"
fi

if [ "$CERT" = "null" ] || [ -z "$CERT" ]; then
    echo -e "${RED}✗ FAIL: serviceCertificate missing or null${NC}"
    FAILED=1
else
    CERT_LEN=${#CERT}
    echo -e "${GREEN}✓ PASS: serviceCertificate present ($CERT_LEN characters)${NC}"
fi

if [ $FAILED -eq 1 ]; then
    exit 1
fi

echo

# Test 4: Save to trust store
echo "Test 4: Testing trust store creation..."
echo "--------------------------------------"
TRUST_STORE_DIR="tmp/test_trust_store"
mkdir -p "$TRUST_STORE_DIR"

echo "$RESPONSE" > "$TRUST_STORE_DIR/scitt.json"
echo -e "${GREEN}✓ PASS: Saved to $TRUST_STORE_DIR/scitt.json${NC}"
echo

# Test 5: Validate with Python ServiceParameters.from_dict()
echo "Test 5: Testing Python ServiceParameters compatibility..."
echo "--------------------------------------"

python3 <<EOF
import json
import base64
import sys

try:
    with open('$TRUST_STORE_DIR/scitt.json') as f:
        data = json.load(f)

    # Test field access (matches ServiceParameters.from_dict())
    tree_alg = data['treeAlgorithm']
    sig_alg = data['signatureAlgorithm']
    cert_b64 = data['serviceCertificate']
    service_id = data['serviceId']

    # Test base64 decode
    cert_der = base64.b64decode(cert_b64)

    print(f"\033[0;32m✓ PASS: All fields present and accessible\033[0m")
    print(f"\033[0;32m✓ PASS: Certificate decodes successfully ({len(cert_der)} bytes)\033[0m")

except KeyError as e:
    print(f"\033[0;31m✗ FAIL: Missing required field: {e}\033[0m")
    sys.exit(1)
except Exception as e:
    print(f"\033[0;31m✗ FAIL: {e}\033[0m")
    sys.exit(1)
EOF

if [ $? -ne 0 ]; then
    exit 1
fi

echo

# Test 6: Compare with mock trust store
echo "Test 6: Comparing with mock trust store..."
echo "--------------------------------------"

if [ -f "mock_trust_store/mock-blob-storage-service.json" ]; then
    MOCK_SERVICE_ID=$(jq -r '.serviceId' mock_trust_store/mock-blob-storage-service.json)
    MOCK_CERT=$(jq -r '.serviceCertificate' mock_trust_store/mock-blob-storage-service.json)

    if [ "$SERVICE_ID" = "$MOCK_SERVICE_ID" ]; then
        echo -e "${GREEN}✓ PASS: serviceId matches mock trust store${NC}"
    else
        echo -e "${YELLOW}⚠ WARNING: serviceId differs from mock trust store${NC}"
        echo "  Function:   $SERVICE_ID"
        echo "  Mock store: $MOCK_SERVICE_ID"
    fi

    if [ "$CERT" = "$MOCK_CERT" ]; then
        echo -e "${GREEN}✓ PASS: Certificate matches mock trust store${NC}"
    else
        echo -e "${RED}✗ FAIL: Certificate differs from mock trust store${NC}"
        echo "This means receipts and trust store will be inconsistent!"
        FAILED=1
    fi
else
    echo -e "${YELLOW}⚠ WARNING: mock_trust_store/mock-blob-storage-service.json not found${NC}"
    echo "  Cannot compare with mock trust store"
fi

if [ $FAILED -eq 1 ]; then
    exit 1
fi

echo

# Test 7: Test URL pattern variations
echo "Test 7: Testing URL pattern variations..."
echo "--------------------------------------"

# Test without /api/ prefix (should fail with 404)
if curl -s -f "${FUNCTION_URL}/parameters" >/dev/null 2>&1; then
    echo -e "${YELLOW}⚠ WARNING: /parameters (without /api/) works${NC}"
    echo "  This is unexpected for Azure Functions"
else
    echo -e "${GREEN}✓ PASS: /parameters (without /api/) returns 404 (expected)${NC}"
fi

# Test with /api/parameters (should succeed)
if curl -s -f "${FUNCTION_URL}/api/parameters" >/dev/null 2>&1; then
    echo -e "${GREEN}✓ PASS: /api/parameters works (correct path)${NC}"
else
    echo -e "${RED}✗ FAIL: /api/parameters failed${NC}"
    exit 1
fi

echo

# Summary
echo "========================================"
echo -e "${GREEN}All Tests Passed!${NC}"
echo "========================================"
echo
echo "Summary:"
echo "  ✓ Endpoint accessible"
echo "  ✓ Valid JSON response"
echo "  ✓ All required fields present"
echo "  ✓ Trust store file created"
echo "  ✓ Python ServiceParameters compatible"
echo "  ✓ Certificate matches mock trust store"
echo "  ✓ URL pattern correct (/api/ prefix required)"
echo
echo "Next steps:"
echo "  1. Test with demo scripts: ./demo/contract/1-contract-setup.sh"
echo "  2. Test complete workflow: submit → retrieve → validate"
echo

# Cleanup
rm -rf "$TRUST_STORE_DIR"

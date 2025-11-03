# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import argparse
import os
from pathlib import Path
from typing import Optional

from ..client import Client
from ..verify import StaticTrustStore, verify_contract_receipt
from .client_arguments import add_client_arguments, create_client


# Static mock certificate for consistent testing
# Subject: C=US, O=Mock SCITT Service, CN=blob-storage-mock
# Valid: 2025-11-03 to 2026-11-03
# This certificate is used for all blob storage mock receipts
MOCK_CERTIFICATE_DER = b'0\x82\x03m0\x82\x02U\xa0\x03\x02\x01\x02\x02\x14l\x9cL\xd0\x88\x90\\\xe6~\'\xf3AP\xf1\xae\xac\xc8Vf\x8b0\r\x06\t*\x86H\x86\xf7\r\x01\x01\x0b\x05\x000F1\x0b0\t\x06\x03U\x04\x06\x13\x02US1\x1b0\x19\x06\x03U\x04\n\x0c\x12Mock SCITT Service1\x1a0\x18\x06\x03U\x04\x03\x0c\x11blob-storage-mock0\x1e\x17\r251103095548Z\x17\r261103095548Z0F1\x0b0\t\x06\x03U\x04\x06\x13\x02US1\x1b0\x19\x06\x03U\x04\n\x0c\x12Mock SCITT Service1\x1a0\x18\x06\x03U\x04\x03\x0c\x11blob-storage-mock0\x82\x01"0\r\x06\t*\x86H\x86\xf7\r\x01\x01\x01\x05\x00\x03\x82\x01\x0f\x000\x82\x01\n\x02\x82\x01\x01\x00\x9bW\xea\xa0\x9d\x85z\x92\xd0\xfc\x14\xfb-n.PVFI5\xa3\xc2*\xa1\x01\xec&\x1c\xf2\x98\xd1\xc2\x90\r\xb3\xa4\xa6r_\x18s\xc9 \xe6~\xa3\xbc\xf9~\xb4RnH\x04\xf6;\xd4\x19\xf0\xae$\xae\xac\x07/\xe2\xf4\xa0\xeb\x8e\x9av\x93\xfd\xcc\xb2\x87\xec[\x9d\xf8\xad\xc4\x1bU\xcf\x05\x11\xf7b\xd3)\xcf2\x1b{1\x12\x10#\xb6\xff\xa2%(\xab5\xcc\x9f\x05p\xb01.\xf8.5\xdd\xc5\x8a\x05:V\x88\x7f\xd9F\x935+g\xbc\xfe1\xb1\x87t\xdc.s\xb5\xbe\xbb\x86\x06\x86P\x8byI\xb9\x0c\x8a\xd9\x107\x1e\xb7\xffZ\xda\x05)\x03\x90\xa8E\xd1\x8e\x95\xa2\xc1\xe7\xbc\xd6\xcb\x9e\x8d\xa7N(l\xe04m\xe8$\\\x85\xa6Q\xfb\xac\xc9\xbf\x87*]\xd2\xae6B\xb4\x98O\x01\xd9Y&\xf9-m\xec\xcb\x8e\xd1Kk\xc4Jq\x8e\n\xc1\xf9\xa2\xa6\x90b_\xae\xc5\x17\x87)\x83j\xf5\xe2\xf8l\xb1\x8bk\xdf\x17#\x17tb/\xf4\x92\xc8\xa0W\x02\x03\x01\x00\x01\xa3S0Q0\x1d\x06\x03U\x1d\x0e\x04\x16\x04\x14"w]\x01\xb1`x(\'5,\xde,\xb8\xc3\x19\xb1\xe4K\x960\x1f\x06\x03U\x1d#\x04\x180\x16\x80\x14"w]\x01\xb1`x(\'5,\xde,\xb8\xc3\x19\xb1\xe4K\x960\x0f\x06\x03U\x1d\x13\x01\x01\xff\x04\x050\x03\x01\x01\xff0\r\x06\t*\x86H\x86\xf7\r\x01\x01\x0b\x05\x00\x03\x82\x01\x01\x00\x1b\x14T\xc4 \xe5\x1c\x99m\xebK\x8e~\x97\x8d\x02Q\xb1?\xf2B\xac\xaf\x97\x1fQ`\x87\x96\xaf\xc8\xe1(\nv?\x18I6\x86\xa6t\xc8X\xba{U\x82>\xa3F\xa7\xcb_\xbbpGo\xa7\x04\xb6\tU\x87\xeaSy\x9b\xe6\xb9\xe6\x1f\xbd<B3\xb4\xb5\xbb\xe0\x0e\xe0{~\xa3\x0e\xb1\x9d\\\xa2\x04$\xfb\xb0o#^M\xab_\xbd\r\x90\x96\xf2#M\tO\xc1\xb5\xc5K\r#\xb8\xb7\xed\x99\x06\x98\x83\r\x9f\xae\xef\\\xa1\xafX\x86\xb4+\xe9\xd4p"_ \xe7\xa9\xd9\x13\xd5\xd8\xeew\xa2<\xe8l\x93D|\xdb\x0e:\x9dgb\x00\x80\r\xf9;X\x05\x94\xf7\xb8\xef\xc3\nY\x8a\x06\xa7\xf7P\xe5\x9b\xdd\xc3z\xaf0}k\xdd)Z\x93\x16tt\xc7\xac\x15f\x91B\x99\x07\x81\xc3\xcc\x0f\xf0\xe8\x14a\xfds\xca{\xbb\xeb\xdcI\xe7\xee\xd9\xf4-\xc7\t0TP\xa7\xa6\x94\xa8\x98\x97\x9c\xa6n\xe1[\xf5T@\xa2T1\xa7&)uSPa\x0b\xe9s'


def _create_mock_receipt(contract_id: str, contract_data: bytes) -> bytes:
    """
    Create a mock CBOR receipt for testing validation workflow.

    This receipt has the correct structure for SCITT/CCF receipts but contains
    mock cryptographic data. It will parse correctly but fail cryptographic
    verification (as expected for training/demo purposes).

    Args:
        contract_id: The contract ID (e.g., "2.15")
        contract_data: The raw contract bytes

    Returns:
        CBOR-encoded receipt bytes
    """
    import cbor2
    import hashlib

    # Create protected headers
    # These need to match the structure expected by Receipt.from_cose_obj()
    protected_headers = {
        "tree_alg": "CCF",  # HEADER_PARAM_TREE_ALGORITHM
        "service_id": "mock-blob-storage-service",  # Used for trust store lookup
    }
    phdr_encoded = cbor2.dumps(protected_headers)

    # Create mock receipt contents matching CCFReceiptContents structure
    # [signature, node_certificate, inclusion_proof, leaf_info]

    # Mock signature (64 bytes for ES256)
    mock_signature = b"\x00" * 64

    # Use static mock certificate (consistent with trust store)
    mock_cert = MOCK_CERTIFICATE_DER

    # Mock inclusion proof (empty list - single node tree)
    mock_inclusion_proof = []

    # Mock leaf info [internal_hash, internal_data]
    mock_leaf_info = [
        hashlib.sha256(contract_id.encode()).digest(),  # internal_hash
        contract_id.encode(),  # internal_data
    ]

    # Assemble receipt contents
    receipt_contents = [
        mock_signature,
        mock_cert,
        mock_inclusion_proof,
        mock_leaf_info,
    ]

    # Full receipt structure: [phdr_encoded, contents]
    receipt_cose_obj = [phdr_encoded, receipt_contents]

    return cbor2.dumps(receipt_cose_obj)


def submit_to_blob_storage(path: Path, receipt_path: Optional[Path] = None) -> str:
    """
    Submit contract to Azure Blob Storage via Azure Function endpoint.

    The Azure Function handles atomic sequence number assignment and storage.

    Args:
        path: Path to the .cose contract file
        receipt_path: Optional path to write mock receipt (CBOR format for testing)

    Returns:
        str: The contract ID (e.g., "2.15")

    Raises:
        ValueError: If file extension is invalid or required env vars are missing
        RuntimeError: If submission fails
    """
    try:
        import httpx
        from loguru import logger
    except ImportError:
        raise RuntimeError(
            "Required dependencies not installed. "
            "Install with: pip install httpx loguru"
        )

    # Validate file
    if path.suffix != ".cose":
        raise ValueError("unsupported file extension, expected .cose")

    # Get configuration from environment
    service_url = os.environ.get("PYSCITT_BLOB_SERVICE_URL")

    if not service_url:
        raise ValueError(
            "Missing PYSCITT_BLOB_SERVICE_URL environment variable. "
            "Set it to your Azure Function endpoint (e.g., https://myfunction.azurewebsites.net)"
        )

    logger.info(f"Submitting contract to blob storage via {service_url}")

    # Read contract file
    with open(path, "rb") as f:
        contract_data = f.read()

    # Submit to Azure Function endpoint
    submit_url = f"{service_url.rstrip('/')}/api/submit"

    try:
        logger.debug(f"POST {submit_url}")
        response = httpx.post(
            submit_url,
            content=contract_data,
            headers={"Content-Type": "application/cose"},
            timeout=30.0
        )
        response.raise_for_status()

        result = response.json()
        contract_id = result.get("entryId")

        if not contract_id:
            raise RuntimeError(f"Invalid response from blob storage service: {result}")

        logger.info(f"Contract assigned ID: {contract_id}")

    except httpx.HTTPError as e:
        logger.error(f"Failed to submit contract: {e}")
        raise RuntimeError(f"Contract submission failed: {e}")

    # Print to stdout (user captures this)
    print(f"Submitted {path} to blob storage as contract {contract_id}")

    # Create mock CBOR receipt if requested
    if receipt_path:
        try:
            mock_receipt = _create_mock_receipt(contract_id, contract_data)
            with open(receipt_path, "wb") as f:
                f.write(mock_receipt)
            logger.info(f"Created mock CBOR receipt: {receipt_path}")
            print(f"Created mock receipt at {receipt_path}")
            print("NOTE: This is a mock receipt for testing workflow only. Cryptographic verification will fail (expected).")
        except Exception as e:
            logger.warning(f"Failed to create receipt file: {e}")

    return contract_id


def submit_signed_contract(
    client: Client,
    path: Path,
    receipt_path: Optional[Path],
    service_trust_store_path: Optional[Path],
    skip_confirmation: bool,
):
    if path.suffix != ".cose":
        raise ValueError("unsupported file extension")

    with open(path, "rb") as f:
        signed_contract = f.read()

    if skip_confirmation:
        pending = client.submit_claim(signed_contract, skip_confirmation=True)
        print(f"Submitted {path} as operation {pending.operation_tx}")
        print("Confirmation of submission was skipped! Claim may not be registered.")
        return

    submission = client.submit_claim(signed_contract)
    print(f"Submitted {path} as transaction {submission.tx}")

    if receipt_path:
        with open(receipt_path, "wb") as f:
            f.write(submission.raw_receipt)
        print(f"Received {receipt_path}")

    if service_trust_store_path:
        service_trust_store = StaticTrustStore.load(service_trust_store_path)
        verify_contract_receipt(
            signed_contract,
            receipt=submission.receipt,
            service_trust_store=service_trust_store,
        )


def cli(fn):
    parser = fn(
        description="Submit signed contract to contract ledger and retrieve receipt"
    )
    add_client_arguments(parser, with_auth_token=True)
    parser.add_argument("path", type=Path, help="Path to signed contract file")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--receipt", type=Path, help="Output path to receipt file")
    group.add_argument(
        "--skip-confirmation",
        action="store_true",
        help="Don't wait for confirmation or a receipt",
    )
    parser.add_argument(
        "--service-trust-store",
        type=Path,
        help="Folder containing JSON parameter files of SCITT services to trust, used to verify the claim",
    )

    def cmd(args):
        backend = os.environ.get("PYSCITT_BACKEND", "ccf").lower()

        if backend == "blob":
            # Blob storage mode - submit via Azure Function endpoint
            submit_to_blob_storage(args.path, args.receipt)
        elif backend == "ccf":
            # CCF mode - existing logic
            client = create_client(args)
            submit_signed_contract(
                client,
                args.path,
                args.receipt,
                args.service_trust_store,
                args.skip_confirmation,
            )
        else:
            raise ValueError(
                f"Unknown backend: '{backend}'. "
                "Set PYSCITT_BACKEND to 'ccf' or 'blob'"
            )

    parser.set_defaults(func=cmd)

    return parser


if __name__ == "__main__":
    parser = cli(argparse.ArgumentParser)
    args = parser.parse_args()
    args.func(args)

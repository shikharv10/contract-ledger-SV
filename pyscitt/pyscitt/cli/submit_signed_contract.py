# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import argparse
import os
from pathlib import Path
from typing import Optional

from ..client import Client
from ..verify import StaticTrustStore, verify_contract_receipt
from .client_arguments import add_client_arguments, create_client


def submit_to_blob_storage(path: Path, receipt_path: Optional[Path] = None) -> str:
    """
    Submit contract to Azure Blob Storage via Azure Function endpoint.

    The Azure Function handles atomic sequence number assignment and storage.

    Args:
        path: Path to the .cose contract file
        receipt_path: Optional path to write synthetic receipt (JSON format)

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

    import json
    import time

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

    # Create synthetic receipt if requested
    if receipt_path:
        receipt_data = {
            "contract_id": contract_id,
            "timestamp": int(time.time()),
            "backend": "blob_storage",
            "service_url": service_url,
            "note": "This is a synthetic receipt for training/demo purposes only. No cryptographic guarantees."
        }
        try:
            with open(receipt_path, "w") as f:
                json.dump(receipt_data, f, indent=2)
            logger.info(f"Created synthetic receipt: {receipt_path}")
            print(f"Created synthetic receipt at {receipt_path}")
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

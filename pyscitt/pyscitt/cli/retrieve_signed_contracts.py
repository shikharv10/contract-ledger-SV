# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import argparse
import os
from pathlib import Path
from typing import Optional

from ..client import Client
from ..verify import StaticTrustStore, verify_contract_receipt, verify_receipt
from .client_arguments import add_client_arguments, create_client
from ..crypto import parse_cose_sign


def retrieve_from_blob_storage(
    base_path: Path,
    contract_id: Optional[str] = None,
    from_seqno: Optional[int] = None,
    to_seqno: Optional[int] = None,
    service_trust_store_path: Optional[Path] = None,
):
    """
    Retrieve contracts from Azure Blob Storage.

    Args:
        base_path: Directory to save retrieved contracts
        contract_id: Single contract ID to retrieve (e.g., "2.15")
        from_seqno: Start of sequence range (e.g., 15)
        to_seqno: End of sequence range (e.g., 20)
        service_trust_store_path: Trust store path (ignored in blob mode)

    Note: Either contract_id OR from_seqno must be provided.
    """
    try:
        from azure.storage.blob import BlobServiceClient
        from loguru import logger
    except ImportError:
        raise RuntimeError(
            "Azure blob storage dependencies not installed. "
            "Install with: pip install azure-storage-blob loguru"
        )

    base_path.mkdir(parents=True, exist_ok=True)

    # Get credentials from environment
    account_name = os.environ.get("PYSCITT_BLOB_ACCOUNT")
    account_key = os.environ.get("PYSCITT_BLOB_KEY")
    container_name = os.environ.get("PYSCITT_BLOB_CONTAINER", "contracts")

    if not account_name or not account_key:
        raise ValueError(
            "Missing blob storage credentials. "
            "Set PYSCITT_BLOB_ACCOUNT and PYSCITT_BLOB_KEY"
        )

    logger.info("Retrieving contracts from blob storage")
    logger.debug(f"Account: {account_name}, Container: {container_name}")

    # Connect to blob storage
    account_url = f"https://{account_name}.blob.core.windows.net"
    blob_service_client = BlobServiceClient(
        account_url=account_url,
        credential=account_key
    )
    container_client = blob_service_client.get_container_client(container_name)

    # Determine which contracts to retrieve
    if contract_id:
        # Single contract
        contract_ids = [contract_id]
        logger.info(f"Retrieving single contract: {contract_id}")
    elif from_seqno is not None:
        # Range of contracts
        end = to_seqno if to_seqno is not None else from_seqno
        contract_ids = [f"2.{seq}" for seq in range(from_seqno, end + 1)]
        logger.info(f"Retrieving contract range: 2.{from_seqno} to 2.{end}")
    else:
        raise ValueError("Either --contract-id or --from must be provided")

    # Trust store note
    if service_trust_store_path:
        logger.info(
            "Trust store provided but verification skipped in blob mode "
            "(no cryptographic receipts available)"
        )

    # Download each contract
    retrieved_count = 0
    for cid in contract_ids:
        blob_name = f"{cid}.cose"
        blob_client = container_client.get_blob_client(blob_name)

        try:
            # Download contract
            logger.debug(f"Downloading {blob_name}")
            download_stream = blob_client.download_blob()
            contract_data = download_stream.readall()

            # Save .cose file
            cose_path = base_path / f"{cid}.cose"
            with open(cose_path, "wb") as f:
                f.write(contract_data)
            logger.info(f"Saved contract: {cose_path}")

            # Extract and save JSON payload
            try:
                _, payload, _ = parse_cose_sign(contract_data)
                json_path = base_path / f"{cid}.json"
                with open(json_path, "wb") as f:
                    f.write(payload)
                logger.debug(f"Extracted payload: {json_path}")
            except Exception as e:
                logger.warning(f"Could not extract payload from {cid}: {e}")

            retrieved_count += 1
            print(f"Retrieved contract {cid}")

        except Exception as e:
            logger.warning(f"Contract {cid} not found or download failed: {e}")
            # Continue with next contract (blob may not exist in range)
            continue

    if retrieved_count == 0:
        logger.warning("No contracts were retrieved")
        print("No contracts found matching the criteria")
    else:
        logger.info(f"Successfully retrieved {retrieved_count} contract(s)")
        print(f"Retrieved {retrieved_count} contract(s) to {base_path}")


def retrieve_signed_contracts(
    client: Client,
    base_path: Path,
    from_seqno: Optional[int],
    to_seqno: Optional[int],
    service_trust_store_path: Optional[Path],
    embed_receipt: Optional[bool] = False,
):
    base_path.mkdir(parents=True, exist_ok=True)

    if service_trust_store_path:
        service_trust_store = StaticTrustStore.load(service_trust_store_path)
    else:
        service_trust_store = None

    for tx in client.enumerate_claims(start=from_seqno, end=to_seqno):
        claim = client.get_claim(tx, embed_receipt=embed_receipt)
        path = base_path / f"{tx}.cose"
        json_path = base_path /f"{tx}.json"

        if service_trust_store and embed_receipt:
            verify_contract_receipt(claim, service_trust_store=service_trust_store)

        with open(path, "wb") as f:
            f.write(claim)

        _, payload, _ = parse_cose_sign(claim)
        with open(json_path, "wb") as f:
            f.write(payload)

def cli(fn):
    parser = fn(
        description="Retrieve signed claimsets from a SCITT CCF Ledger together with receipts"
    )
    add_client_arguments(parser)
    parser.add_argument(
        "path", type=Path, help="Folder to store signed claimsets and receipts"
    )
    parser.add_argument(
        "--contract-id",
        type=str,
        help="Contract ID for blob mode (e.g., 2.15)"
    )
    parser.add_argument(
        "--from", dest="from_seqno", type=int, help="Start seqno (optional)"
    )
    parser.add_argument("--to", dest="to_seqno", type=int, help="End seqno (optional)")
    parser.add_argument(
        "--service-trust-store",
        type=Path,
        help="Folder containing JSON parameter files of SCITT services to trust",
    )

    parser.add_argument(
        "-e",
        "--embed-receipt",
        action="store_true",
        help=argparse.SUPPRESS,
        default=False,
    )

    def cmd(args):
        backend = os.environ.get("PYSCITT_BACKEND", "ccf").lower()

        if backend == "blob":
            # Blob storage mode - retrieve from Azure Blob Storage
            retrieve_from_blob_storage(
                args.path,
                getattr(args, 'contract_id', None),
                args.from_seqno,
                args.to_seqno,
                args.service_trust_store,
            )
        elif backend == "ccf":
            # CCF mode - existing logic
            client = create_client(args)
            retrieve_signed_contracts(
                client,
                args.path,
                args.from_seqno,
                args.to_seqno,
                args.service_trust_store,
                args.embed_receipt,
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

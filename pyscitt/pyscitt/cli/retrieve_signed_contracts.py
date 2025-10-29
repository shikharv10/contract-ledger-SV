# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import argparse
import os
from pathlib import Path
from typing import Optional

from ..client import Client
from ..verify import StaticTrustStore, verify_contract_receipt
from .client_arguments import add_client_arguments, create_client
from ..crypto import parse_cose_sign


def retrieve_signed_contracts(
    client: Client,
    base_path: Path,
    from_seqno: Optional[int],
    to_seqno: Optional[int],
    service_trust_store_path: Optional[Path],
    embed_receipt: Optional[bool] = False,
):
    """Retrieve signed contracts from CCF ledger."""
    base_path.mkdir(parents=True, exist_ok=True)

    if service_trust_store_path:
        service_trust_store = StaticTrustStore.load(service_trust_store_path)
    else:
        service_trust_store = None

    for tx in client.enumerate_claims(start=from_seqno, end=to_seqno):
        claim = client.get_claim(tx, embed_receipt=embed_receipt)
        path = base_path / f"{tx}.cose"
        json_path = base_path / f"{tx}.json"

        if service_trust_store and embed_receipt:
            verify_contract_receipt(claim, service_trust_store=service_trust_store)

        with open(path, "wb") as f:
            f.write(claim)

        _, payload, _ = parse_cose_sign(claim)
        with open(json_path, "wb") as f:
            f.write(payload)


def retrieve_from_blob_storage(
    base_path: Path,
    from_seqno: Optional[int],
    to_seqno: Optional[int],
    service_trust_store_path: Optional[Path],
):
    """Retrieve signed contracts from Azure Blob Storage."""
    from azure.storage.blob import BlobServiceClient
    from azure.core.exceptions import ResourceNotFoundError, AzureError

    # Get Azure credentials from environment
    account_name = os.environ.get("PYSCITT_BLOB_ACCOUNT")
    account_key = os.environ.get("PYSCITT_BLOB_KEY")
    container_name = os.environ.get("PYSCITT_BLOB_CONTAINER")

    if not account_name:
        raise ValueError("PYSCITT_BLOB_ACCOUNT environment variable required for blob backend")
    if not account_key:
        raise ValueError("PYSCITT_BLOB_KEY environment variable required for blob backend")
    if not container_name:
        raise ValueError("PYSCITT_BLOB_CONTAINER environment variable required for blob backend")

    # Initialize blob service client
    account_url = f"https://{account_name}.blob.core.windows.net"
    blob_service_client = BlobServiceClient(account_url=account_url, credential=account_key)
    container_client = blob_service_client.get_container_client(container_name)

    base_path.mkdir(parents=True, exist_ok=True)

    # Load trust store if provided
    if service_trust_store_path:
        service_trust_store = StaticTrustStore.load(service_trust_store_path)
    else:
        service_trust_store = None

    # Download trust store from blob storage
    try:
        trust_store_path = base_path / "trust_store"
        blob_list = container_client.list_blobs(name_starts_with="trust_store/")
        trust_store_files = [b for b in blob_list if b.name.endswith(".did.json")]

        if trust_store_files:
            trust_store_path.mkdir(parents=True, exist_ok=True)
            for blob in trust_store_files:
                blob_client = container_client.get_blob_client(blob.name)
                download_stream = blob_client.download_blob()
                filename = Path(blob.name).name
                with open(trust_store_path / filename, "wb") as f:
                    f.write(download_stream.readall())
    except (ResourceNotFoundError, AzureError):
        pass  # Trust store is optional

    # Enumerate and download contracts
    try:
        blob_list = container_client.list_blobs()
    except AzureError as e:
        raise RuntimeError(f"Failed to enumerate contracts: {e}")

    # Filter for .cose files
    contract_ids = []
    for blob in blob_list:
        if blob.name.endswith(".cose"):
            contract_id = blob.name[:-5]  # Remove .cose extension
            try:
                contract_num = int(contract_id)
                if from_seqno is not None and contract_num < from_seqno:
                    continue
                if to_seqno is not None and contract_num > to_seqno:
                    continue
                contract_ids.append((contract_num, contract_id))
            except ValueError:
                contract_ids.append((float("inf"), contract_id))

    # Sort and process contracts
    contract_ids.sort()
    for _, contract_id in contract_ids:
        try:
            # Download contract
            blob_name = f"{contract_id}.cose"
            try:
                blob_client = container_client.get_blob_client(blob_name)
                download_stream = blob_client.download_blob()
                claim = download_stream.readall()
            except ResourceNotFoundError:
                raise RuntimeError(f"Contract {contract_id} not found. Expected blob: {blob_name}")
            except AzureError as e:
                raise RuntimeError(f"Failed to download contract {contract_id}: {e}")

            # Save COSE file
            cose_path = base_path / f"{contract_id}.cose"
            with open(cose_path, "wb") as f:
                f.write(claim)

            # Verify receipt if trust store is provided
            if service_trust_store:
                try:
                    verify_contract_receipt(claim, service_trust_store=service_trust_store)
                except Exception:
                    pass  # Non-fatal

            # Parse COSE and extract JSON payload
            try:
                _, payload, _ = parse_cose_sign(claim)
                if payload:
                    json_path = base_path / f"{contract_id}.json"
                    with open(json_path, "wb") as f:
                        f.write(payload)
            except Exception as e:
                # Save error marker
                error_path = base_path / f"{contract_id}.json.failed"
                with open(error_path, "w") as f:
                    f.write(f"COSE parsing failed: {e}\n")

        except Exception:
            continue  # Skip failed contracts


def cli(fn):
    parser = fn(
        description="Retrieve signed contracts from SCITT storage (CCF Ledger or Azure Blob Storage)"
    )

    # Add client arguments for CCF backend (optional if using blob backend)
    add_client_arguments(parser)

    parser.add_argument(
        "path", type=Path, help="Folder to store signed contracts and receipts"
    )
    parser.add_argument(
        "--contract-id",
        type=int,
        help="Retrieve a specific contract by ID (alternative to --from/--to)",
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
        # Handle --contract-id as shorthand for --from X --to X
        from_seqno = args.from_seqno
        to_seqno = args.to_seqno

        if args.contract_id is not None:
            if from_seqno is not None or to_seqno is not None:
                raise ValueError(
                    "Cannot specify both --contract-id and --from/--to. "
                    "Use --contract-id for a single contract, or --from/--to for a range."
                )
            from_seqno = args.contract_id
            to_seqno = args.contract_id

        # Determine backend type from environment variable
        backend_type = os.environ.get("PYSCITT_BACKEND", "ccf").lower()

        if backend_type == "blob":
            # Use blob storage backend
            retrieve_from_blob_storage(
                args.path,
                from_seqno,
                to_seqno,
                args.service_trust_store,
            )
        elif backend_type == "ccf":
            # Use CCF backend (existing logic)
            client = create_client(args)
            retrieve_signed_contracts(
                client,
                args.path,
                from_seqno,
                to_seqno,
                args.service_trust_store,
                args.embed_receipt,
            )
        else:
            raise ValueError(
                f"Unknown backend type: {backend_type}. "
                f"Valid options are: 'ccf', 'blob'. "
                f"Set via PYSCITT_BACKEND environment variable."
            )

    parser.set_defaults(func=cmd)
    return parser


if __name__ == "__main__":
    parser = cli(argparse.ArgumentParser)
    args = parser.parse_args()
    args.func(args)

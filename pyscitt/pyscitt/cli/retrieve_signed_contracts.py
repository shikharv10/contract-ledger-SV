# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import argparse
import os
from pathlib import Path
from typing import Optional

from ..backends import CCFBackend, BlobStorageBackend, ContractBackend
from ..client import Client
from .client_arguments import add_client_arguments, create_client


def create_backend() -> ContractBackend:
    """
    Create the appropriate backend based on PYSCITT_BACKEND environment variable.

    Returns:
        A ContractBackend instance (CCFBackend or BlobStorageBackend)
    """
    backend_type = os.environ.get("PYSCITT_BACKEND", "ccf").lower()

    if backend_type == "blob":
        # Create blob storage backend
        return BlobStorageBackend()
    elif backend_type == "ccf":
        # Create CCF backend - need to get client from args
        # This will be passed in from the CLI
        return None  # Placeholder, will be created in cli() function
    else:
        raise ValueError(
            f"Unknown backend type: {backend_type}. "
            f"Valid options are: 'ccf', 'blob'"
        )


def retrieve_signed_contracts(
    backend: ContractBackend,
    base_path: Path,
    from_seqno: Optional[int],
    to_seqno: Optional[int],
    service_trust_store_path: Optional[Path],
    embed_receipt: Optional[bool] = False,
):
    """
    Retrieve signed contracts using the specified backend.

    Args:
        backend: The backend to use for retrieving contracts
        base_path: Directory to save retrieved contracts
        from_seqno: Starting sequence number (optional)
        to_seqno: Ending sequence number (optional)
        service_trust_store_path: Path to trust store for verification (optional)
        embed_receipt: Whether to embed receipts in COSE files (optional)
    """
    backend.retrieve_contracts(
        base_path=base_path,
        from_seqno=from_seqno,
        to_seqno=to_seqno,
        service_trust_store_path=service_trust_store_path,
        embed_receipt=embed_receipt,
    )

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
            # Create blob storage backend
            backend = BlobStorageBackend()
        elif backend_type == "ccf":
            # Create CCF backend with client
            client = create_client(args)
            backend = CCFBackend(client)
        else:
            raise ValueError(
                f"Unknown backend type: {backend_type}. "
                f"Valid options are: 'ccf', 'blob'. "
                f"Set via PYSCITT_BACKEND environment variable."
            )

        retrieve_signed_contracts(
            backend,
            args.path,
            from_seqno,
            to_seqno,
            args.service_trust_store,
            args.embed_receipt,
        )

    parser.set_defaults(func=cmd)
    return parser


if __name__ == "__main__":
    parser = cli(argparse.ArgumentParser)
    args = parser.parse_args()
    args.func(args)

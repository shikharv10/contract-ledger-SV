# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import os
from pathlib import Path
from typing import Optional, Iterable

from azure.storage.blob import BlobServiceClient
from loguru import logger as LOG

from .base import ContractBackend
from ..crypto import parse_cose_sign
from ..verify import StaticTrustStore, verify_contract_receipt


class BlobStorageBackend(ContractBackend):
    """
    Backend for retrieving contracts from Azure Blob Storage.

    Environment variables required:
    - PYSCITT_BLOB_ACCOUNT: Storage account name
    - PYSCITT_BLOB_KEY: Storage account key
    - PYSCITT_BLOB_CONTAINER: Container name
    """

    def __init__(
        self,
        account_name: Optional[str] = None,
        account_key: Optional[str] = None,
        container_name: Optional[str] = None,
    ):
        """
        Initialize the Blob Storage backend.

        Args:
            account_name: Azure storage account name (defaults to PYSCITT_BLOB_ACCOUNT env var)
            account_key: Azure storage account key (defaults to PYSCITT_BLOB_KEY env var)
            container_name: Container name (defaults to PYSCITT_BLOB_CONTAINER env var)
        """
        self.account_name = account_name or os.environ.get("PYSCITT_BLOB_ACCOUNT")
        self.account_key = account_key or os.environ.get("PYSCITT_BLOB_KEY")
        self.container_name = container_name or os.environ.get("PYSCITT_BLOB_CONTAINER")

        if not self.account_name:
            raise ValueError(
                "Storage account name must be provided via account_name parameter "
                "or PYSCITT_BLOB_ACCOUNT environment variable"
            )

        if not self.account_key:
            raise ValueError(
                "Storage account key must be provided via account_key parameter "
                "or PYSCITT_BLOB_KEY environment variable"
            )

        if not self.container_name:
            raise ValueError(
                "Container name must be provided via container_name parameter "
                "or PYSCITT_BLOB_CONTAINER environment variable"
            )

        # Initialize blob service client
        account_url = f"https://{self.account_name}.blob.core.windows.net"
        self.blob_service_client = BlobServiceClient(
            account_url=account_url, credential=self.account_key
        )
        self.container_client = self.blob_service_client.get_container_client(
            self.container_name
        )

        LOG.info(
            f"Initialized BlobStorageBackend: account={self.account_name}, "
            f"container={self.container_name}"
        )

    def enumerate_contracts(
        self,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> Iterable[str]:
        """
        Enumerate all available contract IDs from blob storage.

        Looks for blobs with .cose extension and extracts the contract ID.

        Args:
            start: Starting sequence number (optional)
            end: Ending sequence number (optional)

        Yields:
            Contract IDs as strings
        """
        LOG.info("Enumerating contracts from blob storage")

        # List all blobs with .cose extension
        blob_list = self.container_client.list_blobs()

        contract_ids = []
        for blob in blob_list:
            if blob.name.endswith(".cose"):
                # Extract contract ID from blob name (e.g., "123.cose" -> "123")
                contract_id = blob.name[:-5]  # Remove .cose extension

                # Try to convert to int for filtering
                try:
                    contract_num = int(contract_id)

                    # Apply filtering if specified
                    if start is not None and contract_num < start:
                        continue
                    if end is not None and contract_num > end:
                        continue

                    contract_ids.append((contract_num, contract_id))
                except ValueError:
                    # Not a numeric ID, include it anyway
                    LOG.warning(f"Non-numeric contract ID found: {contract_id}")
                    contract_ids.append((float("inf"), contract_id))

        # Sort by numeric value and yield IDs
        contract_ids.sort()
        for _, contract_id in contract_ids:
            LOG.debug(f"Found contract: {contract_id}")
            yield contract_id

    def get_contract(self, contract_id: str, embed_receipt: bool = False) -> bytes:
        """
        Get a specific contract by ID from blob storage.

        Args:
            contract_id: The contract ID to retrieve
            embed_receipt: Whether to embed receipt (not supported for blob storage)

        Returns:
            The contract as bytes (COSE format)
        """
        if embed_receipt:
            LOG.warning(
                "embed_receipt=True not fully supported for blob storage backend"
            )

        blob_name = f"{contract_id}.cose"
        LOG.debug(f"Downloading blob: {blob_name}")

        blob_client = self.container_client.get_blob_client(blob_name)
        download_stream = blob_client.download_blob()
        return download_stream.readall()

    def retrieve_contracts(
        self,
        base_path: Path,
        from_seqno: Optional[int] = None,
        to_seqno: Optional[int] = None,
        service_trust_store_path: Optional[Path] = None,
        embed_receipt: Optional[bool] = False,
    ) -> None:
        """
        Retrieve contracts from blob storage and save them to disk.

        Args:
            base_path: Directory to save retrieved contracts
            from_seqno: Starting sequence number (optional)
            to_seqno: Ending sequence number (optional)
            service_trust_store_path: Path to trust store for verification (optional)
            embed_receipt: Whether to embed receipts (not fully supported)
        """
        base_path.mkdir(parents=True, exist_ok=True)

        # Load trust store if provided
        if service_trust_store_path:
            service_trust_store = StaticTrustStore.load(service_trust_store_path)
            LOG.info(f"Loaded trust store from {service_trust_store_path}")
        else:
            service_trust_store = None

        # Download trust store from blob storage if it exists
        self._download_trust_store(base_path)

        # Enumerate and download contracts
        for contract_id in self.enumerate_contracts(start=from_seqno, end=to_seqno):
            try:
                LOG.info(f"Retrieving contract: {contract_id}")
                claim = self.get_contract(contract_id, embed_receipt=embed_receipt)

                # Save COSE file
                cose_path = base_path / f"{contract_id}.cose"
                with open(cose_path, "wb") as f:
                    f.write(claim)
                LOG.debug(f"Saved COSE to {cose_path}")

                # Verify receipt if trust store is provided
                if service_trust_store and embed_receipt:
                    try:
                        verify_contract_receipt(
                            claim, service_trust_store=service_trust_store
                        )
                        LOG.info(f"Verified receipt for contract {contract_id}")
                    except Exception as e:
                        LOG.error(f"Failed to verify receipt for {contract_id}: {e}")

                # Parse COSE and extract JSON payload
                try:
                    _, payload, _ = parse_cose_sign(claim)

                    # Save JSON file with contract ID prefix
                    json_path = base_path / f"{contract_id}.json"
                    with open(json_path, "wb") as f:
                        f.write(payload)
                    LOG.debug(f"Saved JSON to {json_path}")

                except Exception as e:
                    LOG.error(f"Failed to parse COSE for {contract_id}: {e}")

            except Exception as e:
                LOG.error(f"Failed to retrieve contract {contract_id}: {e}")
                continue

        LOG.info(f"Finished retrieving contracts to {base_path}")

    def _download_trust_store(self, base_path: Path) -> None:
        """
        Download trust store files (*.did.json) from blob storage.

        Args:
            base_path: Base directory to save trust store files
        """
        trust_store_path = base_path / "trust_store"

        try:
            # List all blobs with trust_store/ prefix
            blob_list = self.container_client.list_blobs(
                name_starts_with="trust_store/"
            )

            for blob in blob_list:
                if blob.name.endswith(".did.json"):
                    LOG.info(f"Downloading trust store file: {blob.name}")

                    # Create trust_store directory if it doesn't exist
                    trust_store_path.mkdir(parents=True, exist_ok=True)

                    # Download the file
                    blob_client = self.container_client.get_blob_client(blob.name)
                    download_stream = blob_client.download_blob()

                    # Extract filename and save
                    filename = Path(blob.name).name
                    file_path = trust_store_path / filename

                    with open(file_path, "wb") as f:
                        f.write(download_stream.readall())

                    LOG.debug(f"Saved trust store file to {file_path}")

        except Exception as e:
            LOG.warning(f"Could not download trust store files: {e}")

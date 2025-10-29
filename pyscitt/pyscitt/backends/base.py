# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Iterable


class ContractBackend(ABC):
    """
    Abstract base class for contract storage backends.

    Backends are responsible for retrieving and uploading contracts
    from different storage systems (CCF ledger, Azure Blob Storage, etc.)
    """

    @abstractmethod
    def retrieve_contracts(
        self,
        base_path: Path,
        from_seqno: Optional[int] = None,
        to_seqno: Optional[int] = None,
        service_trust_store_path: Optional[Path] = None,
        embed_receipt: Optional[bool] = False,
    ) -> None:
        """
        Retrieve contracts from the backend and save them to disk.

        Args:
            base_path: Directory to save retrieved contracts
            from_seqno: Starting sequence number (optional)
            to_seqno: Ending sequence number (optional)
            service_trust_store_path: Path to trust store for verification (optional)
            embed_receipt: Whether to embed receipts in COSE files (optional)
        """
        pass

    @abstractmethod
    def enumerate_contracts(
        self,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> Iterable[str]:
        """
        Enumerate all available contract IDs.

        Args:
            start: Starting sequence number (optional)
            end: Ending sequence number (optional)

        Yields:
            Contract IDs as strings
        """
        pass

    @abstractmethod
    def get_contract(self, contract_id: str, embed_receipt: bool = False) -> bytes:
        """
        Get a specific contract by ID.

        Args:
            contract_id: The contract ID to retrieve
            embed_receipt: Whether to embed receipt in the COSE file

        Returns:
            The contract as bytes (COSE format)
        """
        pass

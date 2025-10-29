# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from pathlib import Path
from typing import Optional, Iterable

from .base import ContractBackend
from ..client import Client
from ..verify import StaticTrustStore, verify_contract_receipt
from ..crypto import parse_cose_sign


class CCFBackend(ContractBackend):
    """
    Backend for retrieving contracts from a CCF (Confidential Consortium Framework) ledger.
    """

    def __init__(self, client: Client):
        """
        Initialize the CCF backend with a client.

        Args:
            client: An initialized CCF Client instance
        """
        self.client = client

    def enumerate_contracts(
        self,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> Iterable[str]:
        """
        Enumerate all available contract IDs from the CCF ledger.

        Args:
            start: Starting sequence number (optional)
            end: Ending sequence number (optional)

        Yields:
            Contract IDs (transaction IDs) as strings
        """
        return self.client.enumerate_claims(start=start, end=end)

    def get_contract(self, contract_id: str, embed_receipt: bool = False) -> bytes:
        """
        Get a specific contract by ID from the CCF ledger.

        Args:
            contract_id: The contract ID (transaction ID) to retrieve
            embed_receipt: Whether to embed receipt in the COSE file

        Returns:
            The contract as bytes (COSE format)
        """
        return self.client.get_claim(contract_id, embed_receipt=embed_receipt)

    def retrieve_contracts(
        self,
        base_path: Path,
        from_seqno: Optional[int] = None,
        to_seqno: Optional[int] = None,
        service_trust_store_path: Optional[Path] = None,
        embed_receipt: Optional[bool] = False,
    ) -> None:
        """
        Retrieve contracts from the CCF ledger and save them to disk.

        Args:
            base_path: Directory to save retrieved contracts
            from_seqno: Starting sequence number (optional)
            to_seqno: Ending sequence number (optional)
            service_trust_store_path: Path to trust store for verification (optional)
            embed_receipt: Whether to embed receipts in COSE files (optional)
        """
        base_path.mkdir(parents=True, exist_ok=True)

        if service_trust_store_path:
            service_trust_store = StaticTrustStore.load(service_trust_store_path)
        else:
            service_trust_store = None

        for tx in self.enumerate_contracts(start=from_seqno, end=to_seqno):
            claim = self.get_contract(tx, embed_receipt=embed_receipt)
            path = base_path / f"{tx}.cose"
            json_path = base_path / f"{tx}.json"

            if service_trust_store and embed_receipt:
                verify_contract_receipt(claim, service_trust_store=service_trust_store)

            with open(path, "wb") as f:
                f.write(claim)

            _, payload, _ = parse_cose_sign(claim)
            with open(json_path, "wb") as f:
                f.write(payload)

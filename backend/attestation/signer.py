"""
Attestation Signer Module
Signs EIP-712 structured typed data with ECDSA or KMS/HSM abstraction.
"""

from typing import Dict, Any, Tuple
from eth_account import Account
from eth_account.messages import encode_typed_data

class AttestationSigner:
    def __init__(self, private_key_hex: str):
        self.account = Account.from_key(private_key_hex)
        self.address = self.account.address

    def sign_typed_data(self, typed_data: Dict[str, Any]) -> str:
        """
        Signs typed data conforming to EIP-712.
        Returns 0x-prefixed hex string of 65-byte signature.
        """
        signable_message = encode_typed_data(full_message=typed_data)
        signed_message = self.account.sign_message(signable_message)
        return signed_message.signature.hex()

    def format_contract_args(self, typed_data: Dict[str, Any], signature_hex: str) -> Tuple:
        """
        Formats message and signature into the tuple expected by
        ASOAdapter.submitAttestation(Attestation calldata a).
        """
        msg = typed_data["message"]
        obs_tuple_list = [
            (
                bytes.fromhex(obs["sourceId"].replace("0x", "")),
                bytes.fromhex(obs["sourceGroup"].replace("0x", "")),
                obs["price"],
                obs["timestamp"]
            )
            for obs in msg["observations"]
        ]

        attestation_tuple = (
            bytes.fromhex(msg["assetId"].replace("0x", "")),
            msg["aggregatePrice"],
            obs_tuple_list,
            msg["windowStart"],
            msg["windowEnd"],
            msg["roundId"],
            msg["validUntil"],
            bytes.fromhex(signature_hex.replace("0x", ""))
        )
        return attestation_tuple

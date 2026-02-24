import os
#!/usr/bin/env python3
"""
Test an actual x402 payment to CryptoSignals402.
Uses our EVM wallet with Base Sepolia testnet USDC.
"""

import sys
import json
import time
from typing import Any

# x402 imports
from x402.client import x402ClientSync
from x402.mechanisms.evm.exact import ExactEvmScheme
from x402.mechanisms.evm.signer import ClientEvmSigner
from x402.http.clients.requests import x402_requests
import requests

PRIVATE_KEY = os.environ.get("CRYPTO402_PRIVATE_KEY", "")  # NEVER hardcode keys!
BASE_URL = "http://localhost:3871"

# Use web3 Account as signer (implements ClientEvmSigner protocol)
from web3 import Web3
from eth_account import Account as EthAccount
from eth_account.messages import encode_typed_data


class Web3Signer:
    """Implements ClientEvmSigner using web3/eth_account."""
    
    def __init__(self, private_key: str):
        self._account = EthAccount.from_key(private_key)
        
    @property
    def address(self) -> str:
        return self._account.address
    
    def sign_typed_data(self, domain, types, primary_type, message) -> bytes:
        """Sign EIP-712 typed data."""
        import dataclasses
        
        # domain is a TypedDataDomain dataclass
        domain_dict = {
            "name": domain.name,
            "version": domain.version,
            "chainId": domain.chain_id,
            "verifyingContract": domain.verifying_contract,
        }
        
        # types values are lists of TypedDataField dataclasses
        types_dict = {
            k: [{"name": f.name, "type": f.type} for f in v]
            for k, v in types.items()
        }
        
        # Build EIP712Domain type from domain keys
        domain_type_fields = []
        field_type_map = {"name": "string", "version": "string", "chainId": "uint256", "verifyingContract": "address"}
        for key in domain_dict:
            if domain_dict[key] is not None:
                domain_type_fields.append({"name": key, "type": field_type_map.get(key, "string")})
        
        structured_data = {
            "types": {
                "EIP712Domain": domain_type_fields,
                **types_dict,
            },
            "domain": {k: v for k, v in domain_dict.items() if v is not None},
            "primaryType": primary_type,
            "message": message,
        }
        
        signed = self._account.sign_typed_data(full_message=structured_data)
        return signed.signature


def test_payment():
    """Make a real x402 payment and get carry signals."""
    print(f"🔑 Setting up wallet...")
    signer = Web3Signer(PRIVATE_KEY)
    print(f"   Address: {signer.address}")
    
    # Create x402 client
    scheme = ExactEvmScheme(signer=signer)
    client = x402ClientSync()
    client.register("eip155:*", scheme)
    
    # Create requests session with x402 payment handling
    session = x402_requests(client)
    
    print(f"\n💳 Calling /api/v1/carry/signals (will pay $0.01 USDC on Base Sepolia)...")
    start = time.time()
    
    try:
        resp = session.get(f"{BASE_URL}/api/v1/carry/signals", timeout=30)
        elapsed = time.time() - start
        
        print(f"   Status: {resp.status_code} ({elapsed:.2f}s)")
        
        if resp.status_code == 200:
            data = resp.json()
            signals = data.get("data", [])
            print(f"\n✅ PAYMENT SUCCESSFUL! Got {len(signals)} carry signals")
            print("\n📊 Top 5 Carry Trade Signals:")
            for s in signals[:5]:
                conf = "★" * int(s['confirmation_score'] * 3)
                print(f"   {s['coin']:8s} {s['direction']:5s} | APR: {s['estimated_apr']:7.0f}% | {conf} | Risk: {s['risk']}")
        else:
            print(f"   Response: {resp.text[:300]}")
            
    except Exception as e:
        print(f"⚠️ Error: {type(e).__name__}: {e}")
        print("\n   Note: This fails if wallet has no Base Sepolia USDC")
        print("   Get testnet USDC at: https://faucet.circle.com/")


if __name__ == "__main__":
    test_payment()

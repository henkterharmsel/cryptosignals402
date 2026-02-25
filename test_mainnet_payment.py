#!/usr/bin/env python3
"""
Test a REAL x402 payment to CryptoSignals402 on Base MAINNET.
Uses real USDC — this is the first production x402 payment!
"""

import os
import sys
import json
import time
from datetime import datetime, timezone

from web3 import Web3
from eth_account import Account as EthAccount
from x402.client import x402ClientSync
from x402.mechanisms.evm.exact import register_exact_evm_client
from x402.http.clients.requests import x402_requests

# ─── Config ────────────────────────────────────────────────────────────────────

PRIVATE_KEY = os.environ.get("CRYPTO402_PRIVATE_KEY", "")  # NEVER hardcode keys!
BASE_URL = "http://localhost:3871"
NETWORK = "eip155:8453"  # Base mainnet

# ─── Signer (from x402 SDK signers.py) ─────────────────────────────────────────

from x402.mechanisms.evm.signers import EthAccountSigner

# ─── Main ──────────────────────────────────────────────────────────────────────

def check_balances():
    """Check ETH and USDC balances before payment."""
    account = EthAccount.from_key(PRIVATE_KEY)
    w3 = Web3(Web3.HTTPProvider("https://mainnet.base.org"))
    
    eth_bal = w3.eth.get_balance(account.address)
    
    # USDC balance
    usdc_abi = [{"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", 
                  "outputs": [{"type": "uint256"}], "type": "function", "stateMutability": "view"}]
    usdc = w3.eth.contract(address=Web3.to_checksum_address("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"), abi=usdc_abi)
    usdc_bal = usdc.functions.balanceOf(account.address).call()
    
    print(f"   ETH: {eth_bal/1e18:.6f} ETH")
    print(f"   USDC: ${usdc_bal/1e6:.4f}")
    
    return usdc_bal


def test_mainnet_payment():
    """Make a real x402 payment on Base mainnet."""
    print(f"\n{'='*60}")
    print(f"🚀 CryptoSignals402 — FIRST REAL x402 PAYMENT")
    print(f"   Network: Base Mainnet (eip155:8453)")
    print(f"   Time: {datetime.now(timezone.utc).isoformat()}")
    print(f"{'='*60}\n")
    
    # Setup signer
    account = EthAccount.from_key(PRIVATE_KEY)
    signer = EthAccountSigner(account)
    print(f"💳 Payer wallet: {signer.address}")
    
    print("\n📊 Pre-payment balances:")
    usdc_before = check_balances()
    
    if usdc_before < 10000:  # Less than $0.01 USDC
        print(f"\n❌ Insufficient USDC (need at least $0.01)")
        return False
    
    # Setup x402 client
    client = x402ClientSync()
    register_exact_evm_client(client, signer)
    
    # Create session with x402 payment handling
    session = x402_requests(client)
    
    print(f"\n💸 Making payment: GET /api/v1/carry/signals")
    print(f"   Price: $0.01 USDC on Base mainnet")
    
    start = time.time()
    
    try:
        resp = session.get(f"{BASE_URL}/api/v1/carry/signals", timeout=60)
        elapsed = time.time() - start
        
        print(f"\n⚡ Response: HTTP {resp.status_code} ({elapsed:.2f}s)")
        
        if resp.status_code == 200:
            data = resp.json()
            signals = data.get("data", [])
            
            print(f"\n✅ PAYMENT SUCCESSFUL! Got {len(signals)} carry signals")
            print(f"\n📊 Top Carry Trade Opportunities:")
            for s in signals[:5]:
                conf = "★" * max(1, int(s.get('confirmation_score', 0.5) * 3))
                apr = s.get('estimated_apr', 0)
                direction = s.get('direction', 'LONG')
                coin = s.get('coin', '?')
                print(f"   {coin:8s} {direction:5s} | APR: {apr:8.0f}% | {conf}")
            
            # Check post-payment balances
            from web3 import Web3
            w3 = Web3(Web3.HTTPProvider("https://mainnet.base.org"))
            usdc_abi = [{"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", 
                          "outputs": [{"type": "uint256"}], "type": "function", "stateMutability": "view"}]
            usdc_c = w3.eth.contract(address=Web3.to_checksum_address("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"), abi=usdc_abi)
            usdc_after = usdc_c.functions.balanceOf(account.address).call()
            
            print(f"\n💰 Post-payment USDC: ${usdc_after/1e6:.4f}")
            print(f"   Paid: ${(usdc_before - usdc_after)/1e6:.4f} USDC")
            
            # Check facilitator stats
            import requests
            stats = requests.get("http://localhost:3872/facilitator/stats", timeout=5).json()
            print(f"\n📈 Facilitator stats:")
            print(f"   Total settlements: {stats.get('total_successful', 0)}")
            print(f"   Last TX: {stats.get('last_tx', {}).get('hash', 'none')}")
            
            return True
        
        elif resp.status_code == 402:
            print(f"\n❌ Still got 402 — payment not processed")
            print(f"   Response: {resp.text[:200]}")
            return False
        else:
            print(f"\n⚠️  Unexpected status: {resp.text[:300]}")
            return False
            
    except Exception as e:
        print(f"\n❌ Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_mainnet_payment()
    if success:
        print(f"\n{'='*60}")
        print(f"🎉 FIRST REAL x402 PAYMENT COMPLETE!")
        print(f"   CryptoSignals402 is now earning real USDC on Base mainnet")
        print(f"   Revenue model: $0.01 per API call, fully autonomous")
        print(f"{'='*60}\n")
    else:
        print(f"\n⚠️  Payment test incomplete - check facilitator logs")
    sys.exit(0 if success else 1)

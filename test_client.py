#!/usr/bin/env python3
import os
"""
Test client for CryptoSignals402 x402 API.
Makes real x402 payments using testnet USDC on Base Sepolia.

Usage: python test_client.py <endpoint>
  python test_client.py status          # Free (no payment)
  python test_client.py carry           # Paid ($0.01 USDC)
  python test_client.py all             # Paid ($0.01 USDC)
"""

import sys
import json
import time

PRIVATE_KEY = os.environ.get("CRYPTO402_PRIVATE_KEY", "")
BASE_URL = "http://localhost:3871"

def test_free():
    """Test free endpoints (no payment needed)."""
    import urllib.request
    print("🆓 Testing free endpoints...")
    
    for path in ["/api/v1/status", "/api/v1/funding/extremes"]:
        try:
            resp = urllib.request.urlopen(f"{BASE_URL}{path}", timeout=10)
            data = json.loads(resp.read())
            print(f"  ✅ GET {path} → 200 OK")
            if path == "/api/v1/funding/extremes":
                extremes = data.get("data", [])[:3]
                for e in extremes:
                    print(f"     {e['coin']}/{e['venue']}: {e['rate_8h_pct']:+.2f}%/8h ({e['estimated_apr']:+.0f}% APR)")
        except Exception as e:
            print(f"  ❌ GET {path} → {e}")


def test_402_response():
    """Test that paid endpoints correctly return 402."""
    import urllib.request, urllib.error
    print("\n💳 Testing 402 Payment Required responses...")
    
    for path in ["/api/v1/funding/all", "/api/v1/carry/signals"]:
        try:
            urllib.request.urlopen(f"{BASE_URL}{path}", timeout=10)
            print(f"  ❌ GET {path} → Should have been 402!")
        except urllib.error.HTTPError as e:
            if e.code == 402:
                payment_req = e.headers.get("PAYMENT-REQUIRED", "")
                if payment_req:
                    # Decode the payment requirements
                    import base64
                    req_data = json.loads(base64.b64decode(payment_req))
                    accepts = req_data.get("accepts", [{}])[0]
                    network = accepts.get("network", "?")
                    amount = int(accepts.get("amount", 0)) / 1e6  # USDC has 6 decimals
                    pay_to = accepts.get("payTo", "?")
                    print(f"  ✅ GET {path} → 402 Payment Required")
                    print(f"     Network: {network}")
                    print(f"     Amount: ${amount:.4f} USDC")
                    print(f"     Pay to: {pay_to[:20]}...")
                else:
                    print(f"  ⚠️ GET {path} → 402 but no PAYMENT-REQUIRED header")
            else:
                print(f"  ❌ GET {path} → HTTP {e.code}")
        except Exception as e:
            print(f"  ❌ GET {path} → {e}")


def test_paid_with_x402():
    """Attempt to make a real x402 payment."""
    print("\n🔑 Testing paid endpoint with x402 payment...")
    
    # Check if x402 requests client is available
    try:
        from x402.http.clients.requests import create_x402_session
    except ImportError:
        print("  ⚠️ x402[requests] not installed — install with: pip install x402[requests,evm]")
        return
    
    try:
        from eth_account import Account
    except ImportError:
        print("  ⚠️ eth_account not available in this environment")
        # Try with web3
        try:
            from web3 import Web3
            from web3.middleware import ExtraDataToPOAMiddleware
            print("  ℹ️ Using web3 for account management")
            w3 = Web3()
            account = w3.eth.account.from_key(PRIVATE_KEY)
            print(f"  Wallet: {account.address}")
        except Exception as e:
            print(f"  ❌ Could not create account: {e}")
            return
    else:
        account = Account.from_key(PRIVATE_KEY)
        print(f"  Wallet: {account.address}")
    
    try:
        session = create_x402_session(account)
        print("  Calling /api/v1/carry/signals (will try to pay $0.01 USDC on Base Sepolia)...")
        start = time.time()
        resp = session.get(f"{BASE_URL}/api/v1/carry/signals", timeout=30)
        elapsed = time.time() - start
        
        print(f"  Status: {resp.status_code} ({elapsed:.2f}s)")
        if resp.status_code == 200:
            data = resp.json()
            signals = data.get("data", [])
            print(f"  ✅ Payment successful! Got {len(signals)} carry signals")
            for s in signals[:3]:
                print(f"     {s['coin']}: {s['direction']} on {s['venue']} | APR: {s['estimated_apr']:.0f}% | Risk: {s['risk']}")
        else:
            print(f"  ❌ Failed: {resp.text[:200]}")
    except Exception as e:
        print(f"  ⚠️ Payment test error: {type(e).__name__}: {e}")
        print("     (This is expected if wallet has no Base Sepolia USDC)")


if __name__ == "__main__":
    endpoint = sys.argv[1] if len(sys.argv) > 1 else "all"
    
    print(f"🧪 CryptoSignals402 — x402 Test Client")
    print(f"   Server: {BASE_URL}")
    print(f"   Test: {endpoint}\n")
    
    test_free()
    test_402_response()
    
    if endpoint in ("paid", "all", "carry"):
        test_paid_with_x402()
    
    print("\n✅ Tests complete!")

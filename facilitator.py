#!/usr/bin/env python3
"""
Self-Hosted x402 Facilitator — Base Mainnet
Verifies and settles EIP-3009 USDC payments on Base (eip155:8453)

Port: 3873
URL: http://localhost:3873/facilitator

Endpoints (called by x402 resource servers):
  GET  /facilitator/supported
  POST /facilitator/verify   { x402Version, paymentPayload, paymentRequirements }
  POST /facilitator/settle   { x402Version, paymentPayload, paymentRequirements }
  GET  /facilitator/health
  GET  /facilitator/stats
"""

import os
import json
import sqlite3
import time
import logging
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request

from x402.facilitator import x402FacilitatorSync
from x402.mechanisms.evm.signers import FacilitatorWeb3Signer
from x402.mechanisms.evm.exact import register_exact_evm_facilitator
from x402.schemas import (
    PaymentPayload,
    PaymentRequirements,
    SettleResponse,
    VerifyResponse,
)

# ─── Config ────────────────────────────────────────────────────────────────────

PORT = int(os.environ.get("FACILITATOR_PORT", 3873))
PRIVATE_KEY = os.environ.get("FACILITATOR_PRIVATE_KEY", "")
BASE_MAINNET_RPC = os.environ.get("BASE_RPC", "https://mainnet.base.org")
NETWORK = "eip155:8453"  # Base mainnet

ANALYTICS_DB = Path(__file__).parent / "facilitator_analytics.db"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [FACILITATOR] %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ─── Flask App ─────────────────────────────────────────────────────────────────

app = Flask(__name__)

# ─── Facilitator Setup ─────────────────────────────────────────────────────────

facilitator: x402FacilitatorSync | None = None
facilitator_address: str = ""

def setup_facilitator():
    global facilitator, facilitator_address
    if not PRIVATE_KEY:
        raise ValueError("FACILITATOR_PRIVATE_KEY environment variable required")
    
    key = PRIVATE_KEY if PRIVATE_KEY.startswith("0x") else "0x" + PRIVATE_KEY
    
    log.info("🔑 Setting up FacilitatorWeb3Signer for Base mainnet...")
    signer = FacilitatorWeb3Signer(
        private_key=key,
        rpc_url=BASE_MAINNET_RPC,
    )
    facilitator_address = signer.address
    log.info(f"   Signer address: {signer.address}")
    
    # Check ETH balance
    from web3 import Web3
    w3 = Web3(Web3.HTTPProvider(BASE_MAINNET_RPC))
    bal = w3.eth.get_balance(signer.address)
    log.info(f"   ETH balance: {bal/1e18:.8f} ETH")
    if bal < 10000000000000:  # 0.00001 ETH minimum
        log.warning("   ⚠️  Very low ETH balance — facilitator may fail to settle!")
    
    facilitator = x402FacilitatorSync()
    register_exact_evm_facilitator(
        facilitator, 
        signer, 
        networks=[NETWORK]
    )
    log.info(f"✅ Facilitator ready for {NETWORK}")

# ─── Analytics ─────────────────────────────────────────────────────────────────

def init_analytics():
    conn = sqlite3.connect(str(ANALYTICS_DB))
    conn.execute("""CREATE TABLE IF NOT EXISTS settlements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER NOT NULL,
        tx_hash TEXT,
        payer TEXT,
        amount TEXT,
        success INTEGER NOT NULL DEFAULT 0,
        error TEXT
    )""")
    conn.commit()
    conn.close()

def log_settlement(tx_hash=None, payer=None, amount=None, success=True, error=None):
    try:
        conn = sqlite3.connect(str(ANALYTICS_DB))
        conn.execute(
            "INSERT INTO settlements (timestamp, tx_hash, payer, amount, success, error) VALUES (?,?,?,?,?,?)",
            (int(time.time()), tx_hash, payer, amount, 1 if success else 0, error)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.error(f"Analytics error: {e}")

# ─── Routes ────────────────────────────────────────────────────────────────────

@app.route("/facilitator/supported")
def supported():
    """Return supported payment kinds."""
    if facilitator is None:
        return jsonify({"error": "Facilitator not initialized"}), 503
    
    try:
        sup = facilitator.get_supported()
        return jsonify({
            "kinds": [
                {
                    "x402_version": k.x402_version,
                    "scheme": k.scheme,
                    "network": k.network,
                }
                for k in sup.kinds
            ],
            "signers": sup.signers,
        })
    except Exception as e:
        log.error(f"Supported error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/facilitator/verify", methods=["POST"])
def verify():
    """Verify a payment payload.
    
    Body: { x402Version: 2, paymentPayload: {...}, paymentRequirements: {...} }
    Response: { is_valid: bool, invalid_reason?: str }
    """
    if facilitator is None:
        return jsonify({"isValid": False, "invalidReason": "Facilitator not initialized"}), 503
    
    try:
        body = request.get_json(force=True)
        if not body:
            return jsonify({"isValid": False, "invalidReason": "Empty request body"}), 400
        
        log.info(f"📋 Verify from {request.remote_addr}")
        
        # x402 SDK sends camelCase keys
        payload_data = body.get("paymentPayload", body.get("payload", {}))
        req_data = body.get("paymentRequirements", body.get("payment_requirements", {}))
        
        payload = PaymentPayload.model_validate(payload_data)
        requirements = PaymentRequirements.model_validate(req_data)
        
        result = facilitator.verify(payload, requirements)
        
        log.info(f"   is_valid={result.is_valid}" + 
                 (f" reason={result.invalid_reason}" if not result.is_valid else " ✅"))
        
        # Return in format the SDK expects
        response_data = result.model_dump(by_alias=True, exclude_none=True)
        return jsonify(response_data)
        
    except Exception as e:
        log.error(f"Verify error: {e}", exc_info=True)
        return jsonify({"isValid": False, "invalidReason": str(e)}), 500


@app.route("/facilitator/settle", methods=["POST"])
def settle():
    """Settle a payment — submits on-chain USDC transferWithAuthorization.
    
    Body: { x402Version: 2, paymentPayload: {...}, paymentRequirements: {...} }
    Response: { success: bool, transaction?: str, network?: str, payer?: str }
    """
    if facilitator is None:
        return jsonify({"success": False, "errorReason": "Facilitator not initialized"}), 503
    
    try:
        body = request.get_json(force=True)
        if not body:
            return jsonify({"success": False, "errorReason": "Empty request body"}), 400
        
        log.info(f"💸 Settle from {request.remote_addr}")
        
        payload_data = body.get("paymentPayload", body.get("payload", {}))
        req_data = body.get("paymentRequirements", body.get("payment_requirements", {}))
        
        payload = PaymentPayload.model_validate(payload_data)
        requirements = PaymentRequirements.model_validate(req_data)
        
        result = facilitator.settle(payload, requirements)
        
        if result.success:
            log.info(f"   ✅ Settled! TX: {result.transaction}")
            log_settlement(
                tx_hash=result.transaction,
                payer=result.payer,
                amount=str(getattr(requirements, 'max_amount_required', 'unknown')),
                success=True
            )
        else:
            log.warning(f"   ❌ Failed: {result.error_reason}")
            log_settlement(success=False, error=result.error_reason)
        
        return jsonify(result.model_dump(by_alias=True, exclude_none=True))
            
    except Exception as e:
        log.error(f"Settle error: {e}", exc_info=True)
        log_settlement(success=False, error=str(e))
        return jsonify({"success": False, "errorReason": str(e)}), 500


@app.route("/facilitator/health")
def health():
    """Health check."""
    return jsonify({
        "status": "ok" if facilitator else "not_initialized",
        "network": NETWORK,
        "signer": facilitator_address,
        "port": PORT,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/facilitator/stats")
def stats():
    """Settlement statistics."""
    try:
        conn = sqlite3.connect(str(ANALYTICS_DB))
        total = conn.execute("SELECT COUNT(*), SUM(success) FROM settlements").fetchone()
        recent = conn.execute(
            "SELECT COUNT(*), SUM(success) FROM settlements WHERE timestamp > ?",
            (int(time.time()) - 86400,)
        ).fetchone()
        last_tx = conn.execute(
            "SELECT tx_hash, payer, timestamp FROM settlements WHERE success=1 ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return jsonify({
            "total_settlements": total[0] or 0,
            "total_successful": total[1] or 0,
            "last_24h_settlements": recent[0] or 0,
            "last_24h_successful": recent[1] or 0,
            "last_tx": {"hash": last_tx[0], "payer": last_tx[1], "timestamp": last_tx[2]} if last_tx else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n╔════════════════════════════════════════════╗")
    print(f"║  x402 Self-Hosted Facilitator — Base Mainnet  ║")
    print(f"╚════════════════════════════════════════════╝")
    print(f"  Port: {PORT}")
    print(f"  Network: {NETWORK}")
    print(f"  RPC: {BASE_MAINNET_RPC}")
    
    init_analytics()
    setup_facilitator()
    
    print(f"\n🚀 Running on http://0.0.0.0:{PORT}/facilitator")
    print(f"  GET  /facilitator/health")
    print(f"  GET  /facilitator/supported")
    print(f"  POST /facilitator/verify")
    print(f"  POST /facilitator/settle")
    print(f"  GET  /facilitator/stats")
    print()
    
    app.run(host="0.0.0.0", port=PORT, debug=False)

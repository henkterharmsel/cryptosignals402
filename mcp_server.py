#!/usr/bin/env python3
"""
CryptoSignals402 MCP Server
Exposes x402 pay-per-call crypto intelligence as MCP tools.

This MCP server uses x402 protocol internally to pay for data access.
Tools are available at no additional cost — payments handled by wallet config.

Usage:
  python3 mcp_server.py

MCP Tools:
  - get_carry_signals: Top crypto carry trade opportunities
  - get_funding_extremes: Extreme funding rates (free)  
  - get_opportunities: Ranked funding opportunities
  - get_coin_data: Per-coin funding analysis
  - get_status: API health and stats (free)
"""

import json
import sys
import os
import requests

# Configuration
API_BASE = os.environ.get("CRYPTO402_BASE_URL", "http://localhost:3871")

# Simple tool registry
TOOLS = {
    "get_status": {
        "description": "Get CryptoSignals402 API status and statistics (free)",
        "inputSchema": {"type": "object", "properties": {}},
        "endpoint": "/api/v1/status",
        "free": True,
    },
    "get_funding_extremes": {
        "description": "Get top 5 most extreme funding rates across all exchanges (free)",
        "inputSchema": {"type": "object", "properties": {}},
        "endpoint": "/api/v1/funding/extremes",
        "free": True,
    },
    "get_carry_signals": {
        "description": "Get professional carry trade signals with APR estimates ($0.01 USDC via x402)",
        "inputSchema": {"type": "object", "properties": {}},
        "endpoint": "/api/v1/carry/signals",
        "free": False,
    },
    "get_opportunities": {
        "description": "Get ranked funding rate opportunities ($0.01 USDC via x402)",
        "inputSchema": {"type": "object", "properties": {}},
        "endpoint": "/api/v1/opportunities",
        "free": False,
    },
    "get_coin_data": {
        "description": "Get funding rate analysis for a specific coin ($0.01 USDC via x402)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "coin": {"type": "string", "description": "Coin symbol (e.g. BTC, ETH, SOL)"}
            },
            "required": ["coin"],
        },
        "endpoint": "/api/v1/coin/{coin}",
        "free": False,
    },
}


def call_api(endpoint: str, tool_name: str, args: dict) -> dict:
    """Call the x402 API endpoint (handles paid endpoints)."""
    # Build URL
    url = API_BASE + endpoint
    for key, val in args.items():
        url = url.replace("{" + key + "}", val)
    
    tool = TOOLS[tool_name]
    
    if tool["free"]:
        # Free endpoint — direct call
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": str(e)}
    else:
        # Paid endpoint — try x402 client if configured, else return payment info
        private_key = os.environ.get("CRYPTO402_PRIVATE_KEY", "")
        
        if private_key:
            try:
                from eth_account import Account
                from x402.client import x402ClientSync
                from x402.mechanisms.evm.signers import EthAccountSigner
                from x402.mechanisms.evm.exact import register_exact_evm_client
                from x402.http.clients.requests import x402_requests
                
                account = Account.from_key(private_key if private_key.startswith("0x") else "0x" + private_key)
                signer = EthAccountSigner(account)
                client = x402ClientSync()
                register_exact_evm_client(client, signer)
                session = x402_requests(client)
                
                resp = session.get(url, timeout=30)
                resp.raise_for_status()
                return resp.json()
                
            except Exception as e:
                return {
                    "error": str(e),
                    "help": "Set CRYPTO402_PRIVATE_KEY env var with a Base mainnet wallet containing USDC"
                }
        else:
            # Return payment info without calling (wallet not configured)
            return {
                "payment_required": True,
                "price": "$0.01 USDC",
                "network": "Base Mainnet (eip155:8453)",
                "endpoint": url,
                "protocol": "x402",
                "setup": "Set CRYPTO402_PRIVATE_KEY env var with your Base mainnet private key",
                "usdc_contract": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            }


def handle_request(request: dict) -> dict:
    """Handle MCP JSON-RPC request."""
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})
    
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "cryptosignals402",
                    "version": "1.0.0",
                    "description": "Crypto intelligence API with x402 micropayments ($0.01 USDC/call)",
                },
            },
        }
    
    elif method == "tools/list":
        tools_list = []
        for name, tool in TOOLS.items():
            tools_list.append({
                "name": name,
                "description": tool["description"],
                "inputSchema": tool["inputSchema"],
            })
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": tools_list},
        }
    
    elif method == "tools/call":
        tool_name = params.get("name", "")
        args = params.get("arguments", {})
        
        if tool_name not in TOOLS:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": f"Unknown tool: {tool_name}"},
            }
        
        result = call_api(TOOLS[tool_name]["endpoint"], tool_name, args)
        
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                "isError": "error" in result and "payment_required" not in result,
            },
        }
    
    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }


def main():
    """Run MCP server on stdin/stdout."""
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            
            request = json.loads(line.strip())
            response = handle_request(request)
            
            print(json.dumps(response), flush=True)
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"},
            }
            print(json.dumps(error_response), flush=True)


if __name__ == "__main__":
    main()

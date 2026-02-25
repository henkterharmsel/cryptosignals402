#!/usr/bin/env python3
"""
CryptoSignals402 MCP Server
Exposes x402 pay-per-call crypto intelligence as MCP tools.

This MCP server connects to the CryptoSignals402 API and provides:
- Free tools (status, extremes) — no payment needed
- Paid tools ($0.01 USDC each) — requires x402 wallet config

Usage:
  python3 mcp_server.py

Environment:
  CRYPTO402_BASE_URL   — API server URL (default: http://localhost:3871)
  CRYPTO402_PRIVATE_KEY — Wallet private key for x402 payments (optional)

MCP Tools:
  - get_status:           API health and stats (free)
  - get_funding_extremes: Top 5 extreme funding rates (free)
  - get_carry_signals:    Carry trade signals with APR + risk analysis ($0.01)
  - get_funding_all:      Full 229-coin funding dataset ($0.01)
  - get_divergence:       Cross-exchange funding divergences ($0.01)
  - get_coin_data:        Per-coin funding history + stats ($0.01)
  - get_opportunities:    Ranked funding rate opportunities ($0.01)
  - get_bittensor_subnets: Bittensor subnet yield data ($0.01)
  - get_xrpl_pools:       XRPL AMM pool data ($0.01)
"""

import json
import sys
import os

# Configuration
API_BASE = os.environ.get("CRYPTO402_BASE_URL", "http://localhost:3871")

# ─── Tool Registry ─────────────────────────────────────────────────────────────

TOOLS = {
    "get_status": {
        "description": "Get CryptoSignals402 API health, tracked coins count, exchange count, history depth, and last update time. Free — no payment needed.",
        "inputSchema": {"type": "object", "properties": {}},
        "endpoint": "/api/v1/status",
        "free": True,
    },
    "get_funding_extremes": {
        "description": "Get the top 5 most extreme funding rates across Hyperliquid, Binance, and Bybit right now. Shows coin, venue, rate per 8h, and estimated APR. Free — no payment needed.",
        "inputSchema": {"type": "object", "properties": {}},
        "endpoint": "/api/v1/funding/extremes",
        "free": True,
    },
    "get_carry_signals": {
        "description": "Get professional carry trade signals with multi-venue confirmation scores, risk classification (LOW/MEDIUM/HIGH), and estimated APR. Costs $0.01 USDC via x402 on Base Sepolia.",
        "inputSchema": {"type": "object", "properties": {}},
        "endpoint": "/api/v1/carry/signals",
        "free": False,
    },
    "get_funding_all": {
        "description": "Get the complete funding rate dataset — all 229 coins across 3 exchanges (Hyperliquid, Binance, Bybit) with rate per 8h and estimated APR. Costs $0.01 USDC via x402.",
        "inputSchema": {"type": "object", "properties": {}},
        "endpoint": "/api/v1/funding/all",
        "free": False,
    },
    "get_divergence": {
        "description": "Get cross-exchange funding rate divergences for delta-neutral arbitrage strategies. Shows spread, APR, and suggested strategy. Costs $0.01 USDC via x402.",
        "inputSchema": {"type": "object", "properties": {}},
        "endpoint": "/api/v1/funding/divergence",
        "free": False,
    },
    "get_coin_data": {
        "description": "Get 24-hour funding rate history for a specific coin across all venues, with mean rate, max rate, and persistence stats. Costs $0.01 USDC via x402.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "coin": {
                    "type": "string",
                    "description": "Coin symbol (e.g. BTC, ETH, SOL, AZTEC, SKR)"
                },
                "hours": {
                    "type": "integer",
                    "description": "History hours (1-168, default 24)",
                    "default": 24,
                },
            },
            "required": ["coin"],
        },
        "endpoint": "/api/v1/funding/coin/{coin}",
        "free": False,
    },
    "get_opportunities": {
        "description": "Get all current funding rate opportunities ranked by APR — includes extreme rates and cross-exchange arb. Costs $0.01 USDC via x402.",
        "inputSchema": {"type": "object", "properties": {}},
        "endpoint": "/api/v1/funding/opportunities",
        "free": False,
    },
    "get_bittensor_subnets": {
        "description": "Get Bittensor subnet yield rankings — APY, emissions, liquidity, and composite scores for all 129+ subnets. Costs $0.01 USDC via x402.",
        "inputSchema": {"type": "object", "properties": {}},
        "endpoint": "/api/v1/bittensor/subnets",
        "free": False,
    },
    "get_xrpl_pools": {
        "description": "Get XRPL AMM top pools by health score — TVL, trading fees, estimated APY, and LP stats. Costs $0.01 USDC via x402.",
        "inputSchema": {"type": "object", "properties": {}},
        "endpoint": "/api/v1/xrpl/pools",
        "free": False,
    },
}


# ─── API Client ────────────────────────────────────────────────────────────────

def call_api(endpoint: str, tool_name: str, args: dict) -> dict:
    """Call the CryptoSignals402 API endpoint."""
    import urllib.request
    import urllib.error

    # Build URL
    url = API_BASE + endpoint
    for key, val in args.items():
        url = url.replace("{" + key + "}", str(val))

    # Add query params
    query_params = {k: v for k, v in args.items() if "{" + k + "}" not in endpoint}
    if query_params:
        url += "?" + "&".join(f"{k}={v}" for k, v in query_params.items())

    tool = TOOLS[tool_name]

    if tool["free"]:
        # Free endpoint — direct HTTP call
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return {"error": f"HTTP {e.code}: {e.reason}"}
        except Exception as e:
            return {"error": str(e)}
    else:
        # Paid endpoint — try x402 client if wallet configured
        private_key = os.environ.get("CRYPTO402_PRIVATE_KEY", "")

        if private_key:
            try:
                from eth_account import Account
                from x402.client import x402ClientSync
                from x402.mechanisms.evm.exact import register_exact_evm_client
                from x402.http.clients.requests import x402_requests

                # Create signer
                key = private_key if private_key.startswith("0x") else "0x" + private_key
                account = Account.from_key(key)

                # Build client from protocol
                from x402.mechanisms.evm.signers import EthAccountSigner
                signer = EthAccountSigner(account)
                client = x402ClientSync()
                register_exact_evm_client(client, signer)
                session = x402_requests(client)

                resp = session.get(url, timeout=30)
                resp.raise_for_status()
                return resp.json()

            except Exception as e:
                return {
                    "error": f"x402 payment failed: {e}",
                    "help": "Ensure CRYPTO402_PRIVATE_KEY is set with a wallet containing Base Sepolia USDC",
                    "faucet": "https://faucet.circle.com/ (Base Sepolia USDC)",
                }
        else:
            # No wallet — try direct call (will get 402)
            try:
                req = urllib.request.Request(url, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                if e.code == 402:
                    return {
                        "payment_required": True,
                        "price": "$0.01 USDC",
                        "network": "Base Sepolia (eip155:84532)",
                        "endpoint": url,
                        "protocol": "x402",
                        "setup": "Set CRYPTO402_PRIVATE_KEY env var with a wallet private key holding Base Sepolia USDC",
                        "faucet": "https://faucet.circle.com/ (get free testnet USDC)",
                    }
                return {"error": f"HTTP {e.code}: {e.reason}"}
            except Exception as e:
                return {"error": str(e)}


# ─── MCP Protocol Handler ──────────────────────────────────────────────────────

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
                    "version": "1.1.0",
                    "description": "Real-time crypto intelligence API with x402 micropayments. Access funding rates, carry signals, divergences, Bittensor subnets, and XRPL pools for $0.01 USDC per call.",
                },
            },
        }

    elif method == "notifications/initialized":
        # Client notification — no response needed
        return None

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

    elif method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }


def main():
    """Run MCP server on stdin/stdout (JSON-RPC over stdio)."""
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break

            request = json.loads(line.strip())
            response = handle_request(request)

            if response is not None:
                print(json.dumps(response), flush=True)

        except KeyboardInterrupt:
            break
        except json.JSONDecodeError:
            continue
        except Exception as e:
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"},
            }
            print(json.dumps(error_response), flush=True)


if __name__ == "__main__":
    main()

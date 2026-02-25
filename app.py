#!/usr/bin/env python3
"""
CryptoSignals402 — Pay-Per-Call Crypto Intelligence API
Powered by x402 protocol | USDC on Base

Free tier:   /api/v1/status, /api/v1/funding/extremes (top 5)
Paid tier:   Full funding rates, opportunities, carry signals, TAO, XRPL
Price:       $0.01 USDC per call (Base mainnet or Base Sepolia testnet)
Receive to:  0x176Ae77D96D0A015F3Dc748a1CD94DE93A7605a3

Modes:
  NETWORK=mainnet  → eip155:8453  + self-hosted facilitator (port 3873)
  NETWORK=testnet  → eip155:84532 + public facilitator (x402.org)
"""

import json
import os
import sqlite3
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request

# x402 imports
from x402.server import x402ResourceServerSync
from x402.http.facilitator_client import HTTPFacilitatorClientSync, FacilitatorConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.http.middleware.flask import payment_middleware
from x402.http.types import RouteConfig, PaymentOption

# ─── Config ────────────────────────────────────────────────────────────────────

PORT = int(os.environ.get("PORT", 3871))
PAY_TO = os.environ.get("PAY_TO", "0x176Ae77D96D0A015F3Dc748a1CD94DE93A7605a3")

# Dual-mode: testnet (public facilitator) or mainnet (self-hosted)
NETWORK_MODE = os.environ.get("NETWORK_MODE", "testnet")  # "mainnet" or "testnet"

if NETWORK_MODE == "mainnet":
    NETWORK = "eip155:8453"   # Base mainnet
    FACILITATOR_URL = os.environ.get("FACILITATOR_URL", "http://localhost:3873/facilitator")
else:
    NETWORK = "eip155:84532"  # Base Sepolia testnet
    FACILITATOR_URL = os.environ.get("FACILITATOR_URL", "https://x402.org/facilitator")

# Data sources
FUNDING_DB = Path(__file__).parent.parent / "funding-rate-hunter" / "funding_rates.db"
TAO_API = "http://localhost:3863"
XRPL_API = "http://localhost:3864"
FUNDING_API = "http://localhost:3868"

# Analytics DB
ANALYTICS_DB = Path(__file__).parent / "analytics.db"

# ─── Flask App ─────────────────────────────────────────────────────────────────

app = Flask(__name__)

# ─── Data Layer ────────────────────────────────────────────────────────────────

def query_funding_db(sql, params=()):
    """Query the funding rates SQLite database."""
    if not FUNDING_DB.exists():
        return []
    try:
        conn = sqlite3.connect(str(FUNDING_DB), timeout=5)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(sql, params)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        return []


def fetch_api(url, timeout=5):
    """Fetch JSON from an internal API."""
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def get_stats():
    """Get current stats from funding rate DB."""
    rows = query_funding_db("""
        SELECT COUNT(*) as n_snapshots,
               COUNT(DISTINCT coin) as n_coins,
               COUNT(DISTINCT venue) as n_venues,
               MIN(timestamp) as first_ts,
               MAX(timestamp) as last_ts
        FROM funding_snapshots
    """)
    if not rows:
        return {}
    r = rows[0]
    return {
        "snapshots": r["n_snapshots"],
        "coins": r["n_coins"],
        "venues": r["n_venues"],
        "history_hours": round((r["last_ts"] - r["first_ts"]) / 3600, 1) if r["first_ts"] else 0,
        "last_update": datetime.fromtimestamp(r["last_ts"], tz=timezone.utc).isoformat() if r["last_ts"] else None,
    }


def get_latest_rates(limit=None, coin=None):
    """Get most recent funding rates per coin+venue."""
    # Subquery: max timestamp per coin+venue
    where = "WHERE coin = ?" if coin else ""
    params = (coin,) if coin else ()
    sql = f"""
        SELECT fs.coin, fs.venue, fs.rate_8h, fs.apr, fs.timestamp
        FROM funding_snapshots fs
        INNER JOIN (
            SELECT coin, venue, MAX(timestamp) as max_ts
            FROM funding_snapshots
            {where}
            GROUP BY coin, venue
        ) latest ON fs.coin = latest.coin AND fs.venue = latest.venue AND fs.timestamp = latest.max_ts
        ORDER BY ABS(fs.rate_8h) DESC
        {"LIMIT " + str(limit) if limit else ""}
    """
    return query_funding_db(sql, params)


def get_coin_history(coin, hours=24):
    """Get per-coin funding rate history."""
    since = int(time.time()) - hours * 3600
    return query_funding_db("""
        SELECT timestamp, venue, rate_8h, apr
        FROM funding_snapshots
        WHERE coin = ? AND timestamp >= ?
        ORDER BY timestamp DESC
        LIMIT 500
    """, (coin, since))


def get_divergences():
    """Get cross-exchange funding divergences."""
    data = fetch_api(f"{FUNDING_API}/api/opportunities?limit=50")
    if data:
        return [o for o in data if o.get("type") == "cross_exchange_arb"]
    # Fallback: compute from DB
    latest = get_latest_rates()
    coin_venues = {}
    for r in latest:
        coin = r["coin"]
        if coin not in coin_venues:
            coin_venues[coin] = {}
        coin_venues[coin][r["venue"]] = r["rate_8h"]

    divergences = []
    for coin, venues in coin_venues.items():
        venue_list = list(venues.items())
        for i in range(len(venue_list)):
            for j in range(i + 1, len(venue_list)):
                v1, r1 = venue_list[i]
                v2, r2 = venue_list[j]
                spread = abs(r1 - r2)
                apr = spread * (365 * 3) * 100  # 8h periods * 3 per day * 365 days
                if spread > 0.001:  # Only meaningful divergences
                    divergences.append({
                        "coin": coin,
                        "venue1": v1,
                        "venue2": v2,
                        "rate1": round(r1, 6),
                        "rate2": round(r2, 6),
                        "spread": round(spread, 6),
                        "spread_pct": round(spread * 100, 4),
                        "apr": round(apr, 2),
                        "strategy": f"LONG {coin} on {v1}, SHORT on {v2}" if r1 < r2 else f"LONG {coin} on {v2}, SHORT on {v1}",
                    })
    divergences.sort(key=lambda x: x["apr"], reverse=True)
    return divergences[:50]


def get_carry_signals():
    """Compute top carry trade signals with risk metrics."""
    latest = get_latest_rates()
    # Group by coin
    coin_data = {}
    for r in latest:
        c = r["coin"]
        if c not in coin_data:
            coin_data[c] = {"coin": c, "rates": {}}
        coin_data[c]["rates"][r["venue"]] = r["rate_8h"]

    signals = []
    for coin, data in coin_data.items():
        rates = data["rates"]
        if not rates:
            continue

        # Best rate (most negative = long pays you)
        max_abs_rate = max(rates.values(), key=abs)
        venue = [v for v, r in rates.items() if r == max_abs_rate][0]
        direction = "LONG" if max_abs_rate < 0 else "SHORT"
        apr = abs(max_abs_rate) * (365 * 3) * 100

        # Multi-venue confirmation (stronger signal if same sign across venues)
        same_sign = sum(1 for r in rates.values() if (r < 0) == (max_abs_rate < 0))
        confirmation = same_sign / len(rates)

        # Risk score (higher = more risky)
        risk = "LOW" if abs(max_abs_rate) < 0.01 else "MEDIUM" if abs(max_abs_rate) < 0.05 else "HIGH"

        if apr > 10:  # Only signals with meaningful APR
            signals.append({
                "coin": coin,
                "direction": direction,
                "venue": venue,
                "rate_8h": round(max_abs_rate, 6),
                "rate_8h_pct": round(max_abs_rate * 100, 4),
                "estimated_apr": round(apr, 2),
                "venues_tracked": len(rates),
                "confirmation_score": round(confirmation, 2),
                "risk": risk,
                "all_rates": {v: round(r * 100, 4) for v, r in rates.items()},
            })

    signals.sort(key=lambda x: x["estimated_apr"], reverse=True)
    return signals[:100]


# ─── Free Endpoints ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """API landing page with documentation."""
    # Use the request host to generate correct URLs in documentation
    host = request.url_root.rstrip("/")
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CryptoSignals402 — Pay-Per-Call Crypto Intelligence API</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0a0a0f; color: #e0e0e8; font-family: 'Segoe UI', system-ui, sans-serif; }
  .hero { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%); padding: 60px 40px; text-align: center; border-bottom: 1px solid #2a2a4a; }
  .hero h1 { font-size: 2.8em; font-weight: 700; background: linear-gradient(135deg, #64ffda, #1565c0); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 10px; }
  .hero p { color: #9090b0; font-size: 1.1em; margin-top: 10px; }
  .badge { display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 0.8em; font-weight: 600; margin: 4px; }
  .badge-blue { background: #1565c0; color: #fff; }
  .badge-green { background: #00695c; color: #fff; }
  .badge-orange { background: #e65100; color: #fff; }
  .container { max-width: 960px; margin: 0 auto; padding: 40px 20px; }
  .stats-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin: 30px 0; }
  .stat-card { background: #12121e; border: 1px solid #2a2a4a; border-radius: 8px; padding: 20px; text-align: center; }
  .stat-card .value { font-size: 2em; font-weight: 700; color: #64ffda; }
  .stat-card .label { color: #7070a0; font-size: 0.85em; margin-top: 4px; }
  .section { margin: 40px 0; }
  .section h2 { font-size: 1.4em; color: #64ffda; border-bottom: 1px solid #2a2a4a; padding-bottom: 10px; margin-bottom: 20px; }
  .endpoint { background: #12121e; border: 1px solid #2a2a4a; border-radius: 8px; padding: 16px; margin: 10px 0; }
  .endpoint-header { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
  .method { padding: 3px 8px; border-radius: 4px; font-size: 0.8em; font-weight: 700; font-family: monospace; }
  .get { background: #1b5e20; color: #69f0ae; }
  .path { font-family: monospace; color: #64ffda; font-size: 1em; }
  .price { margin-left: auto; font-size: 0.8em; padding: 2px 8px; border-radius: 10px; }
  .free { background: #1b5e20; color: #69f0ae; }
  .paid { background: #b71c1c; color: #ef9a9a; }
  .desc { color: #8080a0; font-size: 0.9em; }
  .params { font-family: monospace; font-size: 0.8em; color: #7070b0; margin-top: 6px; }
  .code-block { background: #080810; border: 1px solid #2a2a4a; border-radius: 6px; padding: 16px; font-family: monospace; font-size: 0.85em; color: #a0d8ef; overflow-x: auto; margin: 10px 0; white-space: pre; }
  .note { background: #1a1a0e; border-left: 3px solid #f57f17; padding: 12px 16px; border-radius: 0 6px 6px 0; color: #ffcc80; font-size: 0.9em; margin: 20px 0; }
  footer { text-align: center; padding: 30px; color: #404060; border-top: 1px solid #1a1a2e; }
</style>
</head>
<body>
<div class="hero">
  <h1>⚡ CryptoSignals402</h1>
  <p>Real-time crypto intelligence, powered by the <strong>x402</strong> pay-per-HTTP protocol</p>
  <div style="margin-top: 16px;">
    <span class="badge badge-blue">🔵 Base (USDC)</span>
    <span class="badge badge-green">✅ 229 Coins</span>
    <span class="badge badge-orange">🔄 Live Data</span>
  </div>
  <p style="margin-top: 20px; font-size: 0.9em; color: #606080;">AI agents and traders pay $0.01 USDC per call — no API keys, no subscriptions</p>
</div>
<div class="container">
  <div class="stats-row" id="stats">
    <div class="stat-card"><div class="value">229</div><div class="label">Coins Tracked</div></div>
    <div class="stat-card"><div class="value">3</div><div class="label">Exchanges</div></div>
    <div class="stat-card"><div class="value">5min</div><div class="label">Update Frequency</div></div>
    <div class="stat-card"><div class="value">$0.01</div><div class="label">Per API Call (USDC)</div></div>
  </div>

  <div class="section">
    <h2>🆓 Free Endpoints</h2>
    <div class="endpoint">
      <div class="endpoint-header">
        <span class="method get">GET</span>
        <span class="path">/api/v1/status</span>
        <span class="price free">FREE</span>
      </div>
      <div class="desc">API health, live stats: coins tracked, history depth, last update</div>
    </div>
    <div class="endpoint">
      <div class="endpoint-header">
        <span class="method get">GET</span>
        <span class="path">/api/v1/funding/extremes</span>
        <span class="price free">FREE</span>
      </div>
      <div class="desc">Top 5 most extreme funding rates right now (teaser)</div>
    </div>
  </div>

  <div class="section">
    <h2>💳 Paid Endpoints — $0.01 USDC/call (Base)</h2>
    <div class="note">💡 Payments are automatic via the x402 protocol. Use any x402-compatible client or the examples below.</div>

    <div class="endpoint">
      <div class="endpoint-header">
        <span class="method get">GET</span>
        <span class="path">/api/v1/funding/all</span>
        <span class="price paid">$0.01</span>
      </div>
      <div class="desc">Complete funding rate dataset — all 229 coins × 3 exchanges (Hyperliquid, Binance, Bybit)</div>
    </div>

    <div class="endpoint">
      <div class="endpoint-header">
        <span class="method get">GET</span>
        <span class="path">/api/v1/funding/opportunities</span>
        <span class="price paid">$0.01</span>
      </div>
      <div class="desc">All current carry trade opportunities ranked by APR with risk classification</div>
    </div>

    <div class="endpoint">
      <div class="endpoint-header">
        <span class="method get">GET</span>
        <span class="path">/api/v1/carry/signals</span>
        <span class="price paid">$0.01</span>
      </div>
      <div class="desc">Computed carry trade signals with multi-venue confirmation scores, risk metrics, and estimated APR</div>
    </div>

    <div class="endpoint">
      <div class="endpoint-header">
        <span class="method get">GET</span>
        <span class="path">/api/v1/funding/divergence</span>
        <span class="price paid">$0.01</span>
      </div>
      <div class="desc">Cross-exchange funding rate divergences for delta-neutral arbitrage strategies</div>
    </div>

    <div class="endpoint">
      <div class="endpoint-header">
        <span class="method get">GET</span>
        <span class="path">/api/v1/funding/coin/{coin}</span>
        <span class="price paid">$0.01</span>
      </div>
      <div class="desc">Per-coin 24h funding rate history across all venues with statistics</div>
      <div class="params">?coin=BTC&hours=24</div>
    </div>

    <div class="endpoint">
      <div class="endpoint-header">
        <span class="method get">GET</span>
        <span class="path">/api/v1/bittensor/subnets</span>
        <span class="price paid">$0.01</span>
      </div>
      <div class="desc">Bittensor subnet yield rankings — APY, emissions, liquidity scores for all 129 subnets</div>
    </div>

    <div class="endpoint">
      <div class="endpoint-header">
        <span class="method get">GET</span>
        <span class="path">/api/v1/xrpl/pools</span>
        <span class="price paid">$0.01</span>
      </div>
      <div class="desc">XRPL AMM top pools by health score — TVL, fees, estimated APY</div>
    </div>
  </div>

  <div class="section">
    <h2>🛠️ Quick Start</h2>
    <p style="color: #8080a0; margin-bottom: 16px;">Using the x402 Python SDK (AI agents, automated systems):</p>
    <div class="code-block">pip install x402[requests,evm]

import requests
from x402.http.clients.requests import create_x402_session
from eth_account import Account

wallet = Account.from_key("YOUR_PRIVATE_KEY")
session = create_x402_session(wallet)

# Get carry signals - pays $0.01 USDC automatically on Base
resp = session.get("{host}/api/v1/carry/signals")
print(resp.json())</div>
    
    <p style="color: #8080a0; margin-bottom: 16px; margin-top: 16px;">Curl (free endpoints only):</p>
    <div class="code-block">curl {host}/api/v1/status
curl {host}/api/v1/funding/extremes</div>
  </div>

  <div class="section">
    <h2>💰 Payment Details</h2>
    <div class="endpoint">
      <div style="color: #8080a0; font-size: 0.9em; line-height: 1.8;">
        <div>🔵 <strong>Network:</strong> Base (Ethereum L2) — chain ID 8453</div>
        <div>💵 <strong>Token:</strong> USDC (native Base USDC)</div>
        <div>💲 <strong>Price:</strong> $0.01 per API call</div>
        <div>📬 <strong>Receive address:</strong> <code style="color: #64ffda;">0x176Ae77D96D0A015F3Dc748a1CD94DE93A7605a3</code></div>
        <div>🤖 <strong>Protocol:</strong> x402 (Coinbase standard) — payments fully automated</div>
      </div>
    </div>
  </div>
</div>
<footer>
  <p>CryptoSignals402 — Built with ❤️ on x402 protocol | Data: Hyperliquid, Binance, Bybit, XRPL, Bittensor</p>
</footer>
</body>
</html>"""
    return html.replace("{host}", host)


@app.route("/api/v1/status")
def status():
    """Free: API health and stats."""
    stats = get_stats()
    return jsonify({
        "status": "ok",
        "service": "CryptoSignals402",
        "version": "1.1.0",
        "protocol": "x402",
        "network": NETWORK,
        "mode": NETWORK_MODE,
        "pay_to": PAY_TO,
        "base_url": request.url_root.rstrip("/"),
        "data": {
            "snapshots": stats.get("snapshots", 0),
            "coins": stats.get("coins", 0),
            "venues": stats.get("venues", 0),
            "history_hours": stats.get("history_hours", 0),
            "last_update": stats.get("last_update"),
        },
        "pricing": {
            "currency": "USDC",
            "network": "Base",
            "price_per_call": "0.01",
            "endpoints": {
                "free": ["/api/v1/status", "/api/v1/funding/extremes"],
                "paid": ["/api/v1/funding/all", "/api/v1/funding/opportunities",
                         "/api/v1/carry/signals", "/api/v1/funding/divergence",
                         "/api/v1/funding/coin/{coin}", "/api/v1/bittensor/subnets",
                         "/api/v1/xrpl/pools"],
            },
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/api/v1/funding/extremes")
def funding_extremes():
    """Free: Top 5 most extreme funding rates (teaser)."""
    rates = get_latest_rates(limit=5)
    result = []
    for r in rates:
        result.append({
            "coin": r["coin"],
            "venue": r["venue"],
            "rate_8h_pct": round(r["rate_8h"] * 100, 4),
            "estimated_apr": round(r["apr"], 2),
            "direction": "LONG" if r["rate_8h"] < 0 else "SHORT",
        })
    return jsonify({
        "data": result,
        "note": "Showing top 5 only. Pay $0.01 USDC on Base for full dataset.",
        "full_endpoint": "/api/v1/funding/all",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


# ─── Paid Endpoints ────────────────────────────────────────────────────────────

@app.route("/api/v1/funding/all")
def funding_all():
    """Paid ($0.01): Full funding rate dataset."""
    rates = get_latest_rates()
    result = []
    for r in rates:
        result.append({
            "coin": r["coin"],
            "venue": r["venue"],
            "rate_8h": round(r["rate_8h"], 8),
            "rate_8h_pct": round(r["rate_8h"] * 100, 6),
            "estimated_apr": round(r["apr"], 2),
            "direction": "LONG" if r["rate_8h"] < 0 else "SHORT",
            "timestamp": r["timestamp"],
        })
    return jsonify({
        "count": len(result),
        "data": result,
        "exchanges": ["HlPerp", "BinPerp", "BybitPerp"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/api/v1/funding/opportunities")
def funding_opportunities():
    """Paid ($0.01): All carry trade opportunities."""
    data = fetch_api(f"{FUNDING_API}/api/opportunities?limit=200")
    if data:
        return jsonify({
            "count": len(data),
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    # Fallback: compute from DB
    rates = get_latest_rates()
    opportunities = []
    for r in rates:
        if abs(r["rate_8h"]) > 0.002:  # >0.2% per 8h = meaningful
            opportunities.append({
                "type": "extreme_rate",
                "coin": r["coin"],
                "venue": r["venue"],
                "rate_8h_pct": round(r["rate_8h"] * 100, 4),
                "apr": round(r["apr"], 2),
                "direction": "LONG" if r["rate_8h"] < 0 else "SHORT",
                "risk": "HIGH" if abs(r["rate_8h"]) > 0.05 else "MEDIUM",
            })
    opportunities.sort(key=lambda x: x["apr"], reverse=True)
    return jsonify({
        "count": len(opportunities),
        "data": opportunities,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/api/v1/carry/signals")
def carry_signals():
    """Paid ($0.01): Computed carry trade signals with analysis."""
    signals = get_carry_signals()
    return jsonify({
        "count": len(signals),
        "data": signals,
        "methodology": {
            "confirmation_score": "Fraction of venues where funding sign agrees (1.0 = all agree)",
            "estimated_apr": "Annualized from 8h rate × 3 × 365",
            "risk": "LOW <1%/8h | MEDIUM 1-5%/8h | HIGH >5%/8h",
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/api/v1/funding/divergence")
def funding_divergence():
    """Paid ($0.01): Cross-exchange funding divergences."""
    divergences = get_divergences()
    return jsonify({
        "count": len(divergences),
        "data": divergences,
        "note": "Delta-neutral strategy: long on exchange with more negative rate, short on other",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/api/v1/funding/coin/<coin>")
def funding_coin(coin):
    """Paid ($0.01): Per-coin funding rate history."""
    hours = min(int(request.args.get("hours", 24)), 168)  # max 7 days
    history = get_coin_history(coin.upper(), hours)
    
    # Compute stats
    rates_8h = [r["rate_8h"] for r in history]
    stats = {}
    if rates_8h:
        stats = {
            "mean_rate_8h_pct": round(sum(rates_8h) / len(rates_8h) * 100, 6),
            "max_rate_8h_pct": round(max(rates_8h, key=abs) * 100, 6),
            "persistence": round(sum(1 for r in rates_8h if r < 0) / len(rates_8h), 2),
            "data_points": len(history),
        }

    return jsonify({
        "coin": coin.upper(),
        "hours_requested": hours,
        "stats": stats,
        "history": [{
            "timestamp": r["timestamp"],
            "venue": r["venue"],
            "rate_8h_pct": round(r["rate_8h"] * 100, 6),
            "estimated_apr": round(r["apr"], 2),
        } for r in history],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/api/v1/bittensor/subnets")
def bittensor_subnets():
    """Paid ($0.01): Bittensor subnet yield rankings."""
    data = fetch_api(f"{TAO_API}/api/subnets")
    if data:
        subnets = data.get("subnets", data) if isinstance(data, dict) else data
        return jsonify({
            "count": len(subnets) if isinstance(subnets, list) else 0,
            "data": subnets,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    return jsonify({"error": "TAO Screener service unavailable", "timestamp": datetime.now(timezone.utc).isoformat()}), 503


@app.route("/api/v1/xrpl/pools")
def xrpl_pools():
    """Paid ($0.01): XRPL AMM top pools."""
    data = fetch_api(f"{XRPL_API}/api/pools?limit=50")
    if data:
        pools = data.get("pools", data) if isinstance(data, dict) else data
        return jsonify({
            "count": len(pools) if isinstance(pools, list) else 0,
            "data": pools,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    return jsonify({"error": "XRPL AMM service unavailable", "timestamp": datetime.now(timezone.utc).isoformat()}), 503


# ─── Analytics Middleware ───────────────────────────────────────────────────────
# NOTE: Must be defined BEFORE app.run() — code after app.run() never executes

def init_analytics():
    """Initialize analytics database."""
    conn = sqlite3.connect(str(ANALYTICS_DB))
    conn.execute("""CREATE TABLE IF NOT EXISTS api_calls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER NOT NULL,
        endpoint TEXT NOT NULL,
        paid INTEGER NOT NULL DEFAULT 0,
        ip TEXT,
        user_agent TEXT
    )""")
    conn.commit()
    conn.close()


def log_call(endpoint, paid=False):
    """Log an API call."""
    try:
        conn = sqlite3.connect(str(ANALYTICS_DB))
        conn.execute("INSERT INTO api_calls (timestamp, endpoint, paid, ip) VALUES (?,?,?,?)",
                     (int(time.time()), endpoint, 1 if paid else 0, request.remote_addr))
        conn.commit()
        conn.close()
    except Exception:
        pass


@app.after_request
def track_request(response):
    """Track all requests for analytics."""
    paid = response.status_code == 200 and request.path.startswith("/api/v1/") and request.path not in ["/api/v1/status", "/api/v1/funding/extremes"]
    log_call(request.path, paid)
    return response


@app.route("/api/v1/analytics")
def analytics():
    """Internal: API usage analytics (no payment required)."""
    since = int(time.time()) - 86400  # last 24h
    conn = sqlite3.connect(str(ANALYTICS_DB))
    rows = conn.execute("""
        SELECT endpoint, COUNT(*) as calls, SUM(paid) as paid_calls
        FROM api_calls WHERE timestamp > ?
        GROUP BY endpoint ORDER BY calls DESC
    """, (since,)).fetchall()
    total = conn.execute("SELECT COUNT(*), SUM(paid) FROM api_calls WHERE timestamp > ?", (since,)).fetchone()
    conn.close()
    return jsonify({
        "last_24h": {
            "total_calls": total[0] or 0,
            "paid_calls": total[1] or 0,
            "revenue_usdc": (total[1] or 0) * 0.01,
        },
        "by_endpoint": [{"endpoint": r[0], "calls": r[1], "paid": r[2]} for r in rows],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


# ─── x402 Payment Middleware Setup ─────────────────────────────────────────────

def setup_x402():
    """Configure x402 payment middleware."""
    facilitator = HTTPFacilitatorClientSync(FacilitatorConfig(url=FACILITATOR_URL))
    server = x402ResourceServerSync(facilitator)
    server.register("eip155:*", ExactEvmServerScheme())

    pay_option = PaymentOption(
        scheme="exact",
        pay_to=PAY_TO,
        price="$0.01",
        network=NETWORK,
    )
    
    protected_routes = {
        "GET /api/v1/funding/all": RouteConfig(
            accepts=pay_option,
            description="Full funding rate dataset — 229 coins × 3 exchanges",
        ),
        "GET /api/v1/funding/opportunities": RouteConfig(
            accepts=pay_option,
            description="All carry trade opportunities ranked by APR",
        ),
        "GET /api/v1/carry/signals": RouteConfig(
            accepts=pay_option,
            description="Carry trade signals with multi-venue confirmation",
        ),
        "GET /api/v1/funding/divergence": RouteConfig(
            accepts=pay_option,
            description="Cross-exchange funding divergences for delta-neutral arb",
        ),
        "GET /api/v1/funding/coin/*": RouteConfig(
            accepts=pay_option,
            description="Per-coin 24h funding rate history",
        ),
        "GET /api/v1/bittensor/subnets": RouteConfig(
            accepts=pay_option,
            description="Bittensor subnet yield rankings — 129 subnets",
        ),
        "GET /api/v1/xrpl/pools": RouteConfig(
            accepts=pay_option,
            description="XRPL AMM top pools by health score",
        ),
    }
    
    payment_middleware(app, protected_routes, server)
    print(f"✅ x402 payment middleware configured")
    print(f"   Mode: {NETWORK_MODE}")
    print(f"   Network: {NETWORK}")
    print(f"   Facilitator: {FACILITATOR_URL}")
    print(f"   Pay-to: {PAY_TO}")
    print(f"   Price: $0.01 USDC per call")
    print(f"   Protected routes: {len(protected_routes)}")


# ─── Initialization ────────────────────────────────────────────────────────────
# Always initialize analytics and x402 middleware at import time
# This ensures gunicorn workers also get the middleware applied

print(f"\n⚡ CryptoSignals402 — x402 Crypto Intelligence API")
print(f"   Port: {PORT}")
print(f"   Mode: {NETWORK_MODE} ({'Base mainnet' if NETWORK_MODE == 'mainnet' else 'Base Sepolia testnet'})")
print(f"   Funding DB: {FUNDING_DB} ({'exists' if FUNDING_DB.exists() else 'MISSING!'})")

init_analytics()
setup_x402()

# ─── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n🚀 Starting server on port {PORT}...\n")
    app.run(host="0.0.0.0", port=PORT, debug=False)

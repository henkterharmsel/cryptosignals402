# CryptoSignals402 — Pay-Per-Call Crypto Intelligence API

**The world's first crypto data API using the x402 payment protocol.**

> AI agents pay $0.01 USDC per call — autonomously, no subscription required.

[![x402 Protocol](https://img.shields.io/badge/x402-Base%20Mainnet-blue)](https://x402.org)
[![USDC](https://img.shields.io/badge/payment-USDC-green)](https://basescan.org)
[![Base Mainnet](https://img.shields.io/badge/network-Base%20Mainnet-0052ff)](https://base.org)

## What is this?

CryptoSignals402 is a pay-per-use crypto market intelligence API that uses the [x402 protocol](https://x402.org) for autonomous micropayments. AI agents can access professional-grade crypto data by paying **$0.01 USDC per call** — no API keys, no subscriptions, no friction.

**Built on x402** — the HTTP 402 Payment Required standard developed by Coinbase and Anthropic (launched Feb 11, 2025). This API was one of the **first** crypto data APIs to go live with x402 on Base mainnet.

## Quick Start

### For AI Agents (x402 Python SDK)

```bash
pip install x402[flask,evm]
```

```python
from x402.client import x402ClientSync
from x402.mechanisms.evm.signers import EthAccountSigner
from x402.mechanisms.evm.exact import register_exact_evm_client
from x402.http.clients.requests import x402_requests
from eth_account import Account

# Setup your Base mainnet wallet (needs USDC)
account = Account.from_key("YOUR_PRIVATE_KEY")
signer = EthAccountSigner(account)

# Create x402 client
client = x402ClientSync()
register_exact_evm_client(client, signer)
session = x402_requests(client)

# Make paid API calls — $0.01 USDC per call
resp = session.get("http://YOUR_HOST:3871/api/v1/carry/signals")
print(resp.json())  # Auto-paid!
```

### For Testing (curl)

```bash
# This returns 402 Payment Required with x402 headers
curl -v http://localhost:3871/api/v1/carry/signals

# Free endpoints (no payment needed)
curl http://localhost:3871/api/v1/status
curl http://localhost:3871/api/v1/funding/extremes
```

## API Endpoints

| Endpoint | Price | Description |
|----------|-------|-------------|
| `GET /api/v1/status` | **FREE** | Service health + stats |
| `GET /api/v1/funding/extremes` | **FREE** | Top 5 extreme funding rates |
| `GET /api/v1/funding/all` | $0.01 | Full funding dataset (229 coins × 3 exchanges) |
| `GET /api/v1/opportunities` | $0.01 | Ranked funding rate opportunities |
| `GET /api/v1/carry/signals` | $0.01 | Professional carry trade signals |
| `GET /api/v1/divergence` | $0.01 | Cross-exchange rate divergence |
| `GET /api/v1/coin/{coin}` | $0.01 | Per-coin funding analysis |
| `GET /api/v1/bittensor/subnets` | $0.01 | Bittensor subnet data |
| `GET /api/v1/xrpl/pools` | $0.01 | XRPL liquidity pool data |

## Payment Details

| Field | Value |
|-------|-------|
| Protocol | [x402](https://x402.org) (HTTP 402 standard) |
| Network | Base Mainnet (eip155:8453) |
| Token | USDC (`0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`) |
| Price | $0.01 per call (10000 USDC micro-units) |
| Pay-to | `0x5ae698C451085C8A213c7E3140c29d4b3aB0Cdd5` |

## Architecture

```
AI Agent (Python/JS)
     │  
     │  GET /api/v1/carry/signals (no auth)
     │  
     ▼
CryptoSignals402 API (port 3871)
     │  
     │  402 Payment Required + x402 headers
     │  
     ▼  
AI Agent signs EIP-3009 authorization
     │  
     │  Retry with X-PAYMENT header
     │  
     ▼
CryptoSignals402 API
     │  
     │  Verify + Settle request
     │  
     ▼
Self-Hosted x402 Facilitator (port 3872)
     │  
     │  transferWithAuthorization on-chain
     │  
     ▼
Base Mainnet — USDC settled ✅
     │  
     │  200 OK + data
     │  
     ▼
AI Agent gets paid API response
```

## Self-Hosting

### Prerequisites

- Python 3.11+
- ETH on Base mainnet (~0.001 ETH for gas)
- A wallet with USDC on Base mainnet (for testing)

### Setup

```bash
# Clone repo
git clone https://github.com/henkterharmsel/cryptosignals402
cd cryptosignals402

# Install dependencies  
pip install x402[flask,evm] flask requests web3 eth-account

# Set environment variables
export FACILITATOR_PRIVATE_KEY="your_private_key_here"
export PAY_TO="0xYOUR_WALLET_ADDRESS"

# Start facilitator (port 3872)
python3 facilitator.py &

# Start API server (port 3871)
python3 app.py
```

### Systemd Services

```bash
# Facilitator
systemctl --user start x402facilitator.service

# API server  
systemctl --user start cryptosignals402.service
```

## Data Sources

The API aggregates data from:
- **Hyperliquid** — decentralized perp DEX
- **Binance Futures** — largest CEX by volume
- **Bybit** — major perp exchange
- **Bittensor** — decentralized AI network subnets
- **XRPL** — XRP Ledger liquidity pools

Data refreshes every 5-15 minutes via background collectors.

## Why x402?

Traditional API monetization requires:
- User accounts + API keys
- Billing setup
- Monthly subscriptions
- Rate limiting complexity

x402 protocol enables:
- **Zero-friction**: Agents pay per call, no setup
- **Autonomous**: No human approval needed
- **Transparent**: Every payment on-chain
- **Fair**: Pay only for what you use

## First-Mover Advantage

As of February 24, 2025, this API is the **first crypto data service** to implement x402 on Base mainnet — just 13 days after the protocol launch (Feb 11, 2025).

## License

MIT — fork freely, but pay your fair share. 🙏

## Contact

- GitHub: [@henkterharmsel](https://github.com/henkterharmsel)
- Payment address: `0x5ae698C451085C8A213c7E3140c29d4b3aB0Cdd5` (Base mainnet)

#!/bin/bash
# CryptoSignals402 Cloudflare Tunnel
# Exposes port 3871 to the internet via trycloudflare.com
exec ~/bin/cloudflared tunnel --url http://localhost:3871 --no-autoupdate --protocol http2

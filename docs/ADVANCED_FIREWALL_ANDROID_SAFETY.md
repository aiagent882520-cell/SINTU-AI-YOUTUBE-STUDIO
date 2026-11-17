# SINTU Advanced Firewall & Android Safety

## Safety boundary

SINTU's firewall is an **application-layer firewall**, not a phone-wide Android
firewall. Termux without root cannot reliably control all Android app traffic.
This feature deliberately does not install iptables/nftables rules, change
Android Private DNS, create a VPN, modify Wi-Fi/mobile settings, or block other
apps. Normal phone connectivity is outside SINTU's control and remains untouched.

## Protection layers

- Keep the FastAPI service bound to `127.0.0.1`; do not expose port 8000 to LAN
  or the public internet.
- Keep admin authentication enabled.
- Keep bridge endpoints protected by separate random bearer tokens (32+
  characters); never put tokens in GitHub issue bodies or logs.
- Preserve the fixed action allowlist; never enable arbitrary shell execution.
- Use the existing per-client API rate limiter, same-origin checks, security
  headers, login throttle and audit log.
- Optional IP/CIDR allowlists must include loopback addresses if local dashboard
  access is needed. A wrong allowlist can lock out the local UI.
- Keep automation-only mode enabled until the full on-device regression and
  production readiness checks pass.

## Read-only audit

Run on Termux:

```bash
cd ~/SINTU-AI-YOUTUBE-STUDIO
.venv/bin/python scripts/firewall_safety_audit.py --json
```

The audit reads SINTU environment settings only. It never edits Android
firewall, VPN, DNS, routing, Wi-Fi or mobile-data configuration. A failed audit
does not automatically rewrite settings or stop services; review the reported
setting before making a deliberate change.

## Recovery

If local dashboard access is blocked, inspect `SINTU_ALLOWED_IPS` in the
project `.env`. For a loopback-only phone setup, leave it blank, or include
`127.0.0.1/32,::1/128`. Restart SINTU with the normal service launcher.
Do not flush Android firewall rules or change system network settings.

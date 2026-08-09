# Remote CLI access to sensor nodes (for central-server agents)

**Purpose.** The sensor Pis (`sdl2-pi0-environ-01`, `-02`, …) are deployed
headless on the tailnet. Coding agents running on the central server
(`sdl2-server-gaia`) — Hermes, Claude Code — need non-interactive SSH to
them for diagnostics and deploys: the 2026-08-08 nightly-unreachability
investigation and the pending metric-rename deploy both required exactly
this. This document is the durable recipe.

## Access model

- **From:** the `sdl2` user on the central server only. Agents inherit that
  identity; no per-agent accounts.
- **Key:** the dedicated `~/.ssh/id_ed25519_lab_pi` keypair on the central
  server (comment `lab-agents@sdl2-server-gaia`). Deliberately NOT the
  shared git key — this one can be revoked by deleting a single
  `authorized_keys` line on each Pi without touching anything else.
- **To:** the `sdl2` user on each Pi, over the tailnet (MagicDNS name).
  Tailscale ACLs remain the outer gate, as everywhere in this lab.
- **Alias:** `~/.ssh/config` on the central server defines one Host alias
  per node (`environ-01`, …) with `BatchMode yes` + `ConnectTimeout 8`, so a
  non-interactive agent fails fast instead of hanging on a password prompt.

```
Host environ-01
    HostName sdl2-pi0-environ-01.tail6a1dd7.ts.net
    User sdl2
    IdentityFile ~/.ssh/id_ed25519_lab_pi
    IdentitiesOnly yes
    BatchMode yes
    ConnectTimeout 8
```

## Enrolling a node (once per Pi)

1. On the central server (skip if the key exists):

   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_lab_pi -N "" \
       -C "lab-agents@sdl2-server-gaia (hermes/claude CLI access to sensor pis)"
   ssh-keyscan -H <pi-magicdns-name> >> ~/.ssh/known_hosts
   ```

2. Install the public key on the Pi — the one step that needs a human
   (password). Either `ssh-copy-id`:

   ```bash
   ssh-copy-id -i ~/.ssh/id_ed25519_lab_pi.pub sdl2@<pi-magicdns-name>
   ```

   or, hardened: append to `~/.ssh/authorized_keys` on the Pi with a
   source restriction so the key works only from the central server —

   ```
   from="100.64.254.6" ssh-ed25519 AAAA… lab-agents@sdl2-server-gaia
   ```

3. Add the Host alias to the central server's `~/.ssh/config` (copy the
   block above, adjust the name), then verify non-interactively:

   ```bash
   ssh environ-01 true && echo OK
   ```

Password auth stays enabled or not at the operator's discretion — the
agents never use it (BatchMode). If you disable it (`PasswordAuthentication
no` in `sshd_config`), keep a console/keyboard recovery path in mind: these
are headless Pi Zeros.

> **Alternative considered:** Tailscale SSH (`tailscale up --ssh` + ACL
> `ssh` rules) removes key management entirely. Not adopted for now — the
> lab's tailnet ACLs are managed coarsely, and a plain `authorized_keys`
> line is easier to audit and revoke per-node than a tailnet-wide policy
> change. Revisit if the node count grows past a handful.

## Ground rules for agents on this channel

Inherited from the lab's `AGENTS.md` conventions; this list is the
node-specific application:

- **Diagnostics freely**: `journalctl`, `systemctl status`, `iw`, `ping`,
  `tailscale status`, reading configs. Anything read-only.
- **Service restarts and deploys only on explicit human request** — the
  standard deploy is:

  ```bash
  ssh environ-01 'cd /opt/sense-every-zone && sudo git pull --ff-only && sudo systemctl restart sense-every-zone'
  curl -fsS http://sdl2-pi0-environ-01.tail6a1dd7.ts.net:8030/zones/env_hte/status | head -c 300
  ```

  (Adjust the checkout path if the node deviates; `systemctl` needs sudo —
  if the Pi's `sdl2` user prompts for a password over BatchMode SSH the
  command fails fast, which is the correct behavior: hand it to a human.)
- **Never** edit `sensors.yaml`, `.env`, or `sshd_config` on a node without
  showing the human the exact change first.
- One node at a time; verify `/zones/<zone>/status` answers before moving on.

## Node network-reliability provisioning (apply to every new node)

Installed on `environ-01` on 2026-08-08 while diagnosing ~10 h nightly
unreachability windows (54.7 % two-day uptime; the Pi itself never went
down — `uptime_seconds` sailed through, battery steady at 90 %). Root
cause consistent with Pi Zero Wi-Fi power-save going dormant during quiet
lab hours; these nodes are **DERP-relay-only** (no direct tailnet path), so
one stale Wi-Fi association / NAT session makes them fully unreachable.

1. **Wi-Fi power-save off**, persisted (NetworkManager images):

   ```bash
   sudo iw wlan0 set power_save off
   sudo tee /etc/NetworkManager/conf.d/wifi-powersave-off.conf >/dev/null <<'EOF'
   [connection]
   wifi.powersave = 2
   EOF
   ```

2. **Keepalive** — keeps the association and the DERP/NAT path warm:

   ```bash
   ( crontab -l 2>/dev/null; echo '* * * * * /usr/bin/ping -c 3 -W 2 100.64.254.6 >/dev/null 2>&1' ) | crontab -
   ```

3. **Persistent journal** (the first incident left no evidence — the
   default volatile journal had rotated it away):

   ```bash
   sudo mkdir -p /etc/systemd/journald.conf.d
   sudo tee /etc/systemd/journald.conf.d/persist.conf >/dev/null <<'EOF'
   [Journal]
   Storage=persistent
   SystemMaxUse=64M
   EOF
   sudo systemctl restart systemd-journald
   ```

Verification of the power-save fix is empirical (does the node survive the
quiet hours?); status as of 2026-08-08: installed, first overnight result
pending. If drops persist with all three in place, suspect the AP's
client-idle policy, not the node.

# Remote CLI access to sensor nodes (for central-server agents)

**Purpose.** The sensor Pis (`sdl2-pi0-environ-01`, `-02`, …) are deployed
headless on the tailnet. Coding agents running on the central server
(`sdl2-server-gaia`) — Hermes, Claude Code — need non-interactive SSH to
them for diagnostics and deploys: the 2026-08-08 nightly-unreachability
investigation and the pending metric-rename deploy both required exactly
this. This document is the durable recipe.

## Access model — Tailscale SSH (what the nodes actually run)

Discovered during enrollment (2026-08-08): the sensor Pis run **Tailscale
SSH** — `tailscaled` intercepts tailnet connections to port 22 and
authenticates by **tailnet identity + ACL**, not `authorized_keys`. A
key-copy attempt fails with `tailnet policy does not permit you to SSH to
this node`; a permitted identity gets a shell with no password. So access
is granted in the tailnet policy file, not on the node:

```json
"ssh": [
  {
    "action": "accept",
    "src":    ["tag:sdl2-server-gaia"],
    "dst":    ["tag:sdl2-devices"],
    "users":  ["sdl2"]
  }
]
```

- **`action: "accept"`**, not `"check"` — `check` demands a browser
  re-auth, which a non-interactive agent can never complete.
- **Scope:** `dst: tag:sdl2-devices` spans all tagged devices, but only
  nodes running the Tailscale SSH server honor it (the Linux Pis; Windows
  device PCs cannot serve Tailscale SSH) — so in practice this grants
  central-server → sensor-node access as `sdl2`, which is the intent.
- **Revocation:** delete the ACL block. Nothing to clean up on any node.
- **Alias:** `~/.ssh/config` on the central server defines one Host alias
  per node (`environ-01`, …) with `BatchMode yes` + `ConnectTimeout 8`, so a
  non-interactive agent fails fast instead of hanging if policy denies it.

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

1. Confirm the node runs Tailscale SSH (they are provisioned that way):
   `tailscale whois <pi-tailnet-ip>` from the server shows its tags;
   an SSH attempt without policy fails with the distinctive
   `tailnet policy does not permit you to SSH to this node`.
2. Ensure the ACL block above exists in the tailnet policy (admin
   console → Access Controls). Adding a node needs **no** policy change
   as long as it carries `tag:sdl2-devices`.
3. Add the Host alias to the central server's `~/.ssh/config` (copy the
   block above, adjust the name), then verify non-interactively:

   ```bash
   ssh environ-01 true && echo OK
   ```

> **Fallback for non-Tailscale-SSH nodes** (or if Tailscale SSH is ever
> turned off): classic key-based sshd. A dedicated keypair already exists
> on the central server for this (`~/.ssh/id_ed25519_lab_pi`, comment
> `lab-agents@sdl2-server-gaia`); install with
> `ssh-copy-id -i ~/.ssh/id_ed25519_lab_pi.pub sdl2@<node>` — optionally
> source-restricted in `authorized_keys` with `from="100.64.254.6"` — and
> add `IdentityFile ~/.ssh/id_ed25519_lab_pi` + `IdentitiesOnly yes` to the
> node's Host alias. Note Tailscale SSH intercepts tailnet port 22 while
> enabled, so `authorized_keys` entries are inert until it is disabled.

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

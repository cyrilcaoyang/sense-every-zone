# Remote CLI access to sensor nodes (for central-server agents)

**Purpose.** The sensor Pis (`sdl2-pi0-environ-01`, `-02`, …) are deployed
headless on the tailnet. Coding agents running on the central server
(`sdl2-server-gaia`) — Hermes, Claude Code — need non-interactive SSH to
them for diagnostics and deploys: the 2026-08-08 nightly-unreachability
investigation and the pending metric-rename deploy both required exactly
this. This document is the durable recipe.

## Access model — second-port key auth (why not port 22)

The sensor Pis run **Tailscale SSH**: `tailscaled` intercepts every tailnet
connection to **port 22** and authenticates by tailnet identity + ACL — a
key-copy attempt fails with `tailnet policy does not permit you to SSH to
this node`, and `authorized_keys` is never consulted. Granting the central
server access that way would mean editing the tailnet policy file, which we
deliberately avoid (tailnet-wide blast radius for a two-machine need).

The interception covers **only port 22**, so agent access runs classic
`sshd` on a **second port (2222)** with ordinary key auth instead:

- **From:** the `sdl2` user on the central server; agents inherit that
  identity. Key: the dedicated `~/.ssh/id_ed25519_lab_pi` (comment
  `lab-agents@sdl2-server-gaia`) — not the shared git key, so revoking
  agent access is deleting one `authorized_keys` line per node.
- **To:** `sdl2@<node>:2222`, key source-restricted with
  `from="100.64.254.6"` so it only works from the central server.
- **Unchanged:** operators keep using plain `ssh sdl2@<node>` (port 22 →
  Tailscale SSH, identity-based, no password) exactly as before.
- **Alias:** `~/.ssh/config` on the central server, one per node —

```
Host environ-01
    HostName sdl2-pi0-environ-01.tail6a1dd7.ts.net
    Port 2222
    User sdl2
    IdentityFile ~/.ssh/id_ed25519_lab_pi
    IdentitiesOnly yes
    BatchMode yes
    ConnectTimeout 8
```

`BatchMode` makes a policy/key failure exit fast instead of hanging on a
prompt no agent can answer.

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

1. **On the Pi** (operator session — Tailscale SSH from a permitted
   identity, or console): open the second port and install the key.

   ```bash
   sudo tee /etc/ssh/sshd_config.d/agent-port.conf >/dev/null <<'EOF'
   # Second port for central-server agent access: tailscaled intercepts
   # tailnet:22 (Tailscale SSH), so key-based agent SSH comes in here.
   Port 22
   Port 2222
   EOF
   sudo sshd -t && sudo systemctl restart ssh

   mkdir -p ~/.ssh && chmod 700 ~/.ssh
   echo 'from="100.64.254.6" ssh-ed25519 <pubkey from the central server> lab-agents@sdl2-server-gaia' >> ~/.ssh/authorized_keys
   chmod 600 ~/.ssh/authorized_keys
   ```

2. **On the central server**: trust the host key on the new port and add
   the Host alias (copy the block above, adjust the name):

   ```bash
   ssh-keyscan -p 2222 -H <pi-magicdns-name> >> ~/.ssh/known_hosts
   ssh <alias> true && echo OK
   ```

3. Caveat that bit us: if the verification **times out** (rather than
   being refused), the tailnet's network ACLs enumerate ports and 2222
   isn't among them — that is the one case that genuinely needs a policy
   edit (or fall back to the Tailscale-SSH ACL `ssh` block, `action:
   "accept"`, never `"check"`).

Two facts agents must know on this channel:

- **Non-login PATH lacks `/usr/sbin`** — call admin tools by full path
  (`/usr/sbin/iw`, `/usr/sbin/sshd`).
- **`sudo` is passwordless for `sdl2` on these nodes** (stock image
  policy, `(ALL : ALL) ALL NOPASSWD`). Agents therefore CAN restart
  services and edit system config — which is exactly why the ground
  rules below are load-bearing rather than decorative.

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

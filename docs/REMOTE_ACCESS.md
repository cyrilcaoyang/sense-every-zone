# Remote CLI access to sensor nodes (for central-server agents)

**Purpose.** The sensor Pis (`sdl2-pi0-environ-01`, `-02`, …) are deployed
headless on the tailnet. Coding agents running on the central server
(`sdl2-server-gaia`) — Hermes, Claude Code — need non-interactive SSH to
them for diagnostics and deploys: the 2026-08-08 unreachability
investigation (root-caused 2026-08-11) and the pending metric-rename deploy both required exactly
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
- **`sudo` requires a password** — and beware the trap that fooled us:
  `sudo` here uses a **global timestamp cache**, so for ~15 minutes after
  any operator types their sudo password in *any* session, an agent's
  `sudo -n` succeeds too. Do not conclude NOPASSWD from one probe.
  Under BatchMode an expired cache fails fast ("a password is required"),
  which is correct: privileged steps (service restarts, config writes)
  go back to a human unless a targeted NOPASSWD line is ever granted.

## Ground rules for agents on this channel

Inherited from the lab's `AGENTS.md` conventions; this list is the
node-specific application:

- **Diagnostics freely**: `journalctl`, `systemctl status`, `iw`, `ping`,
  `tailscale status`, reading configs. Anything read-only. `journalctl`
  needs the `sdl2` account in the `systemd-journal` group — granted on
  `environ-01` 2026-08-11; provisioning item 3 covers new nodes.
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

First installed on `environ-01` 2026-08-08; **root cause corrected
2026-08-11** after the drops continued unchanged. Items 1–2 below were aimed
at a cause that is not the one operating here — they are kept because they
are cheap and harmless, not because they fixed anything. Item 3 needed a
correction to work at all. Item 4 addresses the actual failure.

### The actual failure: the campus DHCP lease expires and NM never re-leases

`env_hte` alternated **~10 h 30 m reachable / ~10 h 40 m unreachable** at
56.3 % availability (4 929 of 8 760 expected samples over six days). The
driver is the `compsci` lease time. **It is not a constant** — the node was
issued 37800 s (10 h 30 m) through 2026-08-10 and 43200 s (12 h) on
2026-08-11, so read it from the device rather than assuming a value:
`nmcli -f DHCP4 device show wlan0 | grep lease_time`. Against the 37800 s
lease, every reachable phase matched it to within the 60 s dashboard poll:

| reachable phase began (UTC) | duration | vs. 37 800 s |
|---|---|---|
| 2026-08-07 10:14:59 | 10h29m45s | −15 s |
| 2026-08-08 07:25:27 | 10h29m57s | −3 s |
| 2026-08-09 04:37:12 | 10h29m50s | −10 s |
| 2026-08-10 01:47:51 | 10h30m42s | +42 s |

Recovery coincides with lease acquisition to the second: the lease issued at
`2026-08-10 22:58:58Z` was followed by the dashboard seeing the node at
`22:59:14Z`, 16 s later.

At expiry the node loses IPv4 reachability and NetworkManager then does
nothing. The journal signature is unmistakable:

- `tailscaled` loops on `connect: network is unreachable` — ENETUNREACH.
  This is *not* a DERP, Wi-Fi, or tailnet problem, however much the
  tailscaled spam makes it look like one. ENETUNREACH by itself only says
  "no route to destination", which fits both "the address was removed" and
  "the address is retained but the default route is gone" — **the 2026-08-11
  expiry settled it: the address is removed.** `ip -4 addr show wlan0` has no
  `inet` line for the whole outage.
- **NetworkManager logs nothing whatsoever.** Across a 42-minute sample of
  one outage: 10 773 tailscaled lines, 129 cron lines, **0 from
  NetworkManager**. It is not retrying, failing, or backing off — it has
  stopped asking.

When it does ask, the campus DHCP server answers in ~400 ms:

    18:58:58  dhcp4 (wlan0): activation: beginning transaction
    18:58:58  dhcp4 (wlan0): state changed no lease
    18:58:59  dhcp4 (wlan0): state changed new lease, address=172.31.35.242

Nothing upstream is refusing the node. The outage is entirely NM failing to
re-acquire.

### Ruled out — do not re-investigate these

- **Wi-Fi power-save** (the 2026-08-08 hypothesis). Confirmed `off`, and the
  drops continued on the same schedule. The link is pristine throughout:
  −47 dBm, 72.2 Mbit/s, 0 RX/TX errors over 3.3 M packets.
- **"Nightly" / quiet-hours / AP client-idle policy.** The period is a
  free-running **21 h 10 m** that drifts ~2 h 50 m earlier each day. The
  2026-08-10 window fell at 08:18–18:59 EDT, squarely in working hours. The
  "nightly" reading was an artifact of a two-day sample.
- **The PiSugar battery HAT / power.** Node uptime ran 11 days across every
  outage, so it never lost power or rebooted; the service process uptime ran
  continuously with it; and the battery read a flat 90–91 % throughout,
  including the samples immediately before and after each drop. The steady
  90 % is the HAT's normal charge plateau, not a fault.
- **The keepalive (item 2).** It cannot help by construction — it only pings,
  and during the outage there is no route for the ping to take. It neither
  detects nor repairs.

### The steps

1. **Wi-Fi power-save off**, persisted (NetworkManager images):

   ```bash
   sudo iw wlan0 set power_save off
   sudo tee /etc/NetworkManager/conf.d/wifi-powersave-off.conf >/dev/null <<'EOF'
   [connection]
   wifi.powersave = 2
   EOF
   ```

2. **Keepalive** — keeps the association warm. Does *not* address the DHCP
   failure above; see "Ruled out".

   ```bash
   ( crontab -l 2>/dev/null; echo '* * * * * /usr/bin/ping -c 3 -W 2 100.64.254.6 >/dev/null 2>&1' ) | crontab -
   ```

3. **Persistent journal + agent read access.** The drop-in alone is **not
   sufficient**: Raspberry Pi OS ships
   `/usr/lib/systemd/journald.conf.d/40-rpi-volatile-storage.conf` with
   `Storage=volatile`, and journald keeps writing to `/run` until explicitly
   flushed. The 2026-08-08 install therefore had no effect —
   `/var/log/journal/` stayed empty for three days and the next incident's
   evidence rotated away again (volatile journal ≈ 8 MB ≈ 5.5 h, and
   tailscaled's ENETUNREACH spam burns through it fast).

   ```bash
   sudo mkdir -p /etc/systemd/journald.conf.d
   sudo tee /etc/systemd/journald.conf.d/persist.conf >/dev/null <<'EOF'
   [Journal]
   Storage=persistent
   SystemMaxUse=64M
   EOF
   sudo journalctl --flush            # the step that was missing
   sudo systemctl restart systemd-journald
   ls /var/log/journal/               # MUST show a machine-id directory
   sudo usermod -aG systemd-journal sdl2   # agents can read it without sudo
   ```

4. **DHCP watchdog.** Source of truth is
   [`deploy/wlan-dhcp-watchdog.sh`](../deploy/wlan-dhcp-watchdog.sh) and
   [`deploy/wlan-dhcp-watchdog.cron`](../deploy/wlan-dhcp-watchdog.cron) in
   this repo — install those rather than pasting from here, so the node and
   the repo cannot drift.

   ```bash
   scp deploy/wlan-dhcp-watchdog.sh environ-01:/tmp/
   ssh environ-01 'sudo install -m 0755 -o root -g root /tmp/wlan-dhcp-watchdog.sh /usr/local/sbin/ && rm /tmp/wlan-dhcp-watchdog.sh'
   scp deploy/wlan-dhcp-watchdog.cron environ-01:/tmp/
   ssh environ-01 'sudo install -m 0644 -o root -g root /tmp/wlan-dhcp-watchdog.cron /etc/cron.d/wlan-dhcp-watchdog && rm /tmp/wlan-dhcp-watchdog.cron'
   ```

   It fires when **either** the default route or the IPv4 address on `wlan0`
   is missing, and only then — so a central-server or DERP outage can never
   bounce a healthy link. `flock` serialises runs (nmcli can block and cron
   fires every 2 min), each attempt is capped with `timeout 60`, and after
   5 consecutive failed reconnects it escalates once to restarting
   NetworkManager.

   > **v1 failed its first live test, and not for the reason first assumed.**
   > Its *trigger* was correct: it fired at 05:30:01, 39 s into the
   > 2026-08-11 05:29:22 EDT expiry, and 152 more times over the next five
   > hours. The *repair* was the bug — it ran `nmcli device reconnect`, which
   > is not a subcommand nmcli has ever had (1.52.1 offers
   > `connect | disconnect | reapply`). Every attempt died on `Error:
   > argument 'reconnect' not understood` and the node stayed down until it
   > was power-cycled at 10:36. The lesson is narrow and worth keeping: the
   > watchdog logged the failure 153 times and nobody was reading, so v3
   > verifies its repair verb exists via `--check` instead of assuming it.
   > v3 has not yet survived a real expiry — treat this step as unproven
   > until it has.

   v1 was also **silent unless it acted**, which made "the trigger never
   became true" indistinguishable from "cron never ran it". v2 separates the
   two: `/run/wlan-dhcp-watchdog.state` is overwritten every run (liveness,
   never grows) and `/var/log/wlan-dhcp-watchdog.log` is appended only on a
   state change or an action. Thirty healthy runs produce one log line.

   Verify a real execution. A malformed `cron.d` file is silently ignored,
   and grepping the journal for the bare script name matches your own `sudo`
   audit lines — match the `CMD` record instead:

   ```bash
   journalctl --since '-10 min' | grep -E 'CRON.*CMD.*wlan-dhcp-watchdog'
   cat /run/wlan-dhcp-watchdog.state    # must be timestamped within 2 min
   cat /var/log/wlan-dhcp-watchdog.log  # state changes + actions only
   ```

### Still open

- **The watchdog is unproven** (see item 4). v3 fixes the repair verb, and
  its branches — including a regression guard asserting `--check` catches a
  missing subcommand — are covered by a stubbed harness, but no build has
  yet survived a real lease expiry. The next one is the test.
- **The watchdog is a mitigation, not a root-cause fix.** *Why* NM stops
  re-acquiring after expiry is still unknown — the first captured expiry had
  already rotated out of the volatile journal. Item 3 is now genuinely
  fixed, so the 2026-08-11 05:29 expiry **is** in the persistent journal;
  diagnose from that rather than guessing.
- **Does the node still need the DERP relay?** After the 2026-08-11 power
  cycle it came up with a *direct* tailnet path (`direct
  172.31.35.242:41641`) rather than relay `tor`. If that holds, one premise
  of the original 2026-08-08 note — that these nodes are DERP-only — is no
  longer true, and the tailscaled log spam that destroyed two incidents'
  evidence should fall away with it. Worth re-checking after the next
  expiry.
- **Durable fix:** a DHCP reservation for the node's MAC from campus IT
  (`environ-01` is `2c:cf:67:e8:9a:4c`), or move the nodes onto a lab AP.
  Either removes the expiry cliff entirely, and a lab AP would likely also
  give a direct tailnet path instead of DERP relay.
- **Cap tailscaled's log volume.** 10 773 lines in 42 minutes during an
  outage is what destroyed the first two incidents' evidence.
- One unexplained single event, low priority:
  `conflict detected for IP address 172.31.35.242 with host 00:00:00:00:00:00`
  — zero-MAC sender, most likely the network's own duplicate-address probe
  rather than a real squatter.

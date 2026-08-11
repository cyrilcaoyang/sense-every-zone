#!/bin/sh
# wlan0 DHCP watchdog -- v2 (2026-08-11)
#
# The campus 'compsci' DHCP lease is 37800 s (10h30m). When it expires,
# NetworkManager does not re-acquire: the node loses IPv4 reachability and
# stays that way for a further ~10h40m while NM logs nothing at all.
#
# v1's TRIGGER was fine -- it fired 39 s into the 2026-08-11 05:29 EDT expiry
# and 153 more times over the next 5 h. What was broken was the REPAIR: it ran
# `nmcli device reconnect`, which is not a subcommand nmcli has ever had
# (1.52.1: connect | disconnect | reapply). Every attempt died on
# "Error: argument 'reconnect' not understood" and the node stayed down until
# it was power-cycled. Hence --check below: the repair verb is now verified to
# exist rather than assumed.
#
# v2 also widened the trigger to fire when EITHER the default route or the
# address is missing. The address was in fact removed, so this was not the bug
# -- but it is strictly more coverage, so it stays.
#
# v1 also wrote nothing unless it acted, so "trigger never became true" and
# "cron never ran it" were indistinguishable. v2 always refreshes STATE
# (overwritten, so it never grows) and appends to LOG on any change or action.
#
# Must run as root (needs nmcli device control). The WD_* env overrides exist
# so the logic can be exercised in a test harness; cron sets none of them.

set -u

IFACE=${WD_IFACE:-wlan0}
if [ "${1:-}" = "--check" ]; then
    rc=0
    for c in ip nmcli flock timeout date; do
        command -v "$c" >/dev/null 2>&1 || { echo "MISSING command: $c"; rc=1; }
    done
    # The v1 bug, in one assertion: never assume a subcommand exists.
    nmcli connection --help 2>&1 | grep -qw up      || { echo "MISSING: nmcli connection up"; rc=1; }
    nmcli device     --help 2>&1 | grep -qw connect || { echo "MISSING: nmcli device connect"; rc=1; }
    [ "$(id -u)" = 0 ] || echo "WARN: not root -- repair actions will fail with insufficient privileges"
    [ "$rc" = 0 ] && echo "selfcheck: OK"
    exit "$rc"
fi
LOG=${WD_LOG:-/var/log/wlan-dhcp-watchdog.log}
STATE=${WD_STATE:-/run/wlan-dhcp-watchdog.state}
FAILS=${WD_FAILS:-/run/wlan-dhcp-watchdog.fails}
LOCK=${WD_LOCK:-/run/wlan-dhcp-watchdog.lock}
MAX_RECONNECT_TRIES=${WD_MAX_TRIES:-5}   # then escalate to restarting NetworkManager

# Serialise: nmcli can block, and cron fires every 2 min.
exec 9>"$LOCK" || exit 0
flock -n 9 || exit 0

now() { date -Is; }
log() { echo "$(now) $*" >>"$LOG"; }

have_addr()  { ip -4 addr show "$IFACE" 2>/dev/null | grep -q 'inet '; }
have_route() { ip -4 route show default 2>/dev/null | grep -q "dev $IFACE"; }

if have_addr;  then a=yes; else a=no; fi
if have_route; then r=yes; else r=no; fi
if [ "$a" = yes ] && [ "$r" = yes ]; then verdict=ok; else verdict=broken; fi

prev=$(cut -d' ' -f2 "$STATE" 2>/dev/null | cut -d= -f2)
echo "$(now) verdict=$verdict addr=$a route=$r" >"$STATE"

if [ "$verdict" != "${prev:-}" ]; then
    log "state ${prev:-unknown} -> $verdict (addr=$a route=$r)"
fi

if [ "$verdict" = ok ]; then
    rm -f "$FAILS"
    exit 0
fi

n=$(cat "$FAILS" 2>/dev/null || echo 0)
n=$((n + 1))
echo "$n" >"$FAILS"

if [ "$n" -ge "$MAX_RECONNECT_TRIES" ]; then
    log "attempt $n: re-activation is not working -- restarting NetworkManager"
    timeout 60 systemctl restart NetworkManager >>"$LOG" 2>&1
    echo 0 >"$FAILS"
else
    # Re-activate the profile: that re-runs the DHCP transaction. Derived at
    # runtime rather than hardcoding 'compsci', so this is not node-specific.
    profile=$(nmcli -g GENERAL.CONNECTION device show "$IFACE" 2>/dev/null)
    if [ -n "$profile" ]; then
        log "attempt $n: addr=$a route=$r -- nmcli connection up $profile"
        timeout 60 nmcli connection up "$profile" >>"$LOG" 2>&1
    else
        log "attempt $n: addr=$a route=$r -- no active profile, nmcli device connect $IFACE"
        timeout 60 nmcli device connect "$IFACE" >>"$LOG" 2>&1
    fi
fi

sleep 8
if have_addr && have_route; then
    log "recovered: $(ip -4 -br addr show "$IFACE") | $(ip -4 route show default)"
    rm -f "$FAILS"
    echo "$(now) verdict=ok addr=yes route=yes" >"$STATE"
else
    if have_addr; then a2=yes; else a2=no; fi
    if have_route; then r2=yes; else r2=no; fi
    log "still broken after attempt $n (addr=$a2 route=$r2)"
fi

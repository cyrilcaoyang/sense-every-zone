#!/bin/sh
# wlan0 DHCP watchdog -- v2 (2026-08-11)
#
# The campus 'compsci' DHCP lease is 37800 s (10h30m). When it expires,
# NetworkManager does not re-acquire: the node loses IPv4 reachability and
# stays that way for a further ~10h40m while NM logs nothing at all.
#
# v1 keyed the trigger on the IPv4 address being absent. That was an over-read
# of the only symptom actually observed -- tailscaled looping on ENETUNREACH --
# which fits BOTH "address removed" and "address retained, default route gone".
# v1 did not fire on the 2026-08-11 05:29 EDT expiry. v2 fires when EITHER the
# default route or the address is missing.
#
# v1 also wrote nothing unless it acted, so "trigger never became true" and
# "cron never ran it" were indistinguishable. v2 always refreshes STATE
# (overwritten, so it never grows) and appends to LOG on any change or action.
#
# Must run as root (needs nmcli device control). The WD_* env overrides exist
# so the logic can be exercised in a test harness; cron sets none of them.

set -u

IFACE=${WD_IFACE:-wlan0}
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
    log "attempt $n: reconnect is not working -- restarting NetworkManager"
    timeout 60 systemctl restart NetworkManager >>"$LOG" 2>&1
    echo 0 >"$FAILS"
else
    log "attempt $n: addr=$a route=$r -- nmcli device reconnect $IFACE"
    timeout 60 nmcli device reconnect "$IFACE" >>"$LOG" 2>&1
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

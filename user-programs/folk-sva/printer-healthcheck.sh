#!/usr/bin/env bash
# Nightly check (01:00, via folk's crontab) that BOTH print paths are
# still actually connected -- not merely present in CUPS.
#
# The two failure modes this exists to catch are ones CUPS hides:
#   - the Canon's DHCP lease moves and the queue URI goes stale; CUPS
#     still reports the queue "idle"
#   - the USB receipt printer stops being talkable-to; CUPS' usb backend
#     answers Send-Document successful-ok and delivers nothing
#
# So we test the devices themselves, not the queue state. Neither check
# prints anything: the USB test claims the interface and releases it,
# which proves reachability without wasting a receipt every night.
#
# Writes a Tcl-dict file that user-programs/folk-sva/status.folk renders
# at http://folk-sva:4273/status.

set -uo pipefail

FOLK_DIR="$HOME/folk"
OUT="$HOME/folk-data/printer-health.txt"
LOG="$HOME/log/printer-health.log"
NET_PRINTER="${NET_PRINTER:-Pixma}"

mkdir -p "$(dirname "$OUT")" "$(dirname "$LOG")"

# Values land inside a Tcl dict, so strip anything that could unbalance it.
san() { tr -d '{}\n\r' <<<"${1:-}" | cut -c1-200; }

log() { printf '%s  %s\n' "$(date -Is)" "$*" >> "$LOG"; }

# Keep the log bounded.
if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG")" -gt $((256 * 1024)) ]; then
    tail -n 300 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

# --- WiFi / network printer -----------------------------------------
wifi_ok=0
wifi_ip=""
wifi_detail="no device URI in CUPS"
uri="$(lpstat -v "$NET_PRINTER" 2>/dev/null | sed -n 's/^device for [^:]*: //p')"
if [ -n "$uri" ]; then
    wifi_ip="$(sed -n 's|^ipps\{0,1\}://\([0-9.]\{7,15\}\).*|\1|p' <<<"$uri")"
    if [ -z "$wifi_ip" ]; then
        wifi_detail="URI is not a literal IP: $uri"
    elif ! timeout 3 bash -c "exec 3<>/dev/tcp/$wifi_ip/631" 2>/dev/null; then
        wifi_detail="no answer on $wifi_ip:631 (lease moved, or printer off)"
    else
        model="$(cd "$FOLK_DIR" && timeout 10 ipptool -T 5 -tv \
            "ipp://$wifi_ip:631/ipp/print" get-printer-attributes.test 2>/dev/null \
            | sed -n 's/.*printer-make-and-model (textWithoutLanguage) = //p' | head -1)"
        if [ -n "$model" ]; then
            wifi_ok=1
            wifi_detail="$model at $wifi_ip"
        else
            wifi_detail="port 631 open at $wifi_ip but no IPP reply"
        fi
    fi
fi

# --- USB receipt printer --------------------------------------------
usb_ok=0
usb_detail="no printer-class USB interface present"
usb_present=0
for f in /sys/bus/usb/devices/*/bInterfaceClass; do
    [ -r "$f" ] || continue
    if [ "$(cat "$f" 2>/dev/null)" = "07" ]; then usb_present=1; break; fi
done
if [ "$usb_present" = 1 ]; then
    if probe="$(cd "$FOLK_DIR" && python3 lib/escpos-usb.py --probe 2>&1)"; then
        usb_ok=1
        usb_detail="$(san "$probe")"
    else
        usb_detail="printer-class device present but not claimable: $(san "$probe")"
    fi
fi

# --- Where we are ----------------------------------------------------
iface="$(ip -4 route show default 2>/dev/null | awk '{print $5; exit}')"
ipcidr="$(ip -4 -o addr show dev "$iface" 2>/dev/null | awk '{print $4; exit}')"
ssid="$(iw dev "$iface" link 2>/dev/null | sed -n 's/^\tSSID: //p')"
[ -z "${ssid:-}" ] && ssid="$(iw dev "$iface" info 2>/dev/null | sed -n 's/^\tssid //p')"

overall=fail
[ "$wifi_ok" = 1 ] && [ "$usb_ok" = 1 ] && overall=ok
[ "$wifi_ok" != "$usb_ok" ] && overall=partial

tmp="$OUT.tmp"
{
    echo "timestamp {$(date -Is)}"
    echo "overall {$overall}"
    echo "wifi_printer {$(san "$NET_PRINTER")}"
    echo "wifi_ok {$wifi_ok}"
    echo "wifi_ip {$(san "$wifi_ip")}"
    echo "wifi_detail {$(san "$wifi_detail")}"
    echo "usb_ok {$usb_ok}"
    echo "usb_detail {$(san "$usb_detail")}"
    echo "iface {$(san "$iface")}"
    echo "ipcidr {$(san "$ipcidr")}"
    echo "ssid {$(san "$ssid")}"
} > "$tmp" && mv "$tmp" "$OUT"

log "overall=$overall wifi=$wifi_ok ($wifi_detail) usb=$usb_ok ($usb_detail)"

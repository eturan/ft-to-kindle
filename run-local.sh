#!/bin/bash
# Fetch myFT and email it to the Kindle. Run by launchd (see launchd/).
# Config lives in ~/.config/ft-to-kindle/env (not in the repo).
set -euo pipefail
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

CONF="$HOME/.config/ft-to-kindle/env"
if [[ ! -f "$CONF" ]]; then
    echo "$(date) missing $CONF" >&2
    exit 1
fi
# shellcheck source=/dev/null
source "$CONF"
# The recipe's fetch shim reads these from the environment.
export MYFT_RSS_URL FT_FETCH_PYTHON FT_COOKIE_FILE
export FT_FETCH_HELPER="$(pwd)/recipes/ft_fetch.py"

# launchd catch-up (RunAtLoad + missed calendar runs) can fire more than once
# a day; the stamp file makes delivery once-per-day.
STAMP_DIR="$HOME/.local/state/ft-to-kindle"
STAMP="$STAMP_DIR/last-sent"
TODAY="$(date +%Y-%m-%d)"
mkdir -p "$STAMP_DIR"
if [[ -f "$STAMP" && "$(cat "$STAMP")" == "$TODAY" ]]; then
    echo "$(date) already sent today, skipping"
    exit 0
fi

OUT="${TMPDIR:-/tmp}/FT myFT $TODAY.epub"
trap 'rm -f "$OUT"' EXIT

# Coming out of sleep the network can take a while to come back; don't
# start fetching (and burn the day's launchd slot) until ft.com:443 accepts
# a TCP connection, up to ~4 minutes.
for _ in $(seq 1 24); do
    if nc -z -G 5 www.ft.com 443 >/dev/null 2>&1; then
        break
    fi
    echo "$(date) waiting for network..."
    sleep 10
done

echo "$(date) fetching myFT..."
ebook-convert recipes/myft.recipe "$OUT"

echo "$(date) sending to kindle..."
# Prefer Amazon's Send to Kindle service (HTTPS): outbound SMTP to Gmail is
# blocked on this network since ~2026-08-27. Falls back to calibre-smtp if
# the one-time stk_send.py registration hasn't been done.
STK_PY="$HOME/.config/ft-to-kindle/stk-venv/bin/python"
if [[ -f "$HOME/.config/ft-to-kindle/stk-client.json" && -x "$STK_PY" ]]; then
    # KINDLE_DEVICE_SERIAL (from the env config) pins delivery to one
    # device - use the exact serial, name substrings also match the
    # phone/desktop reading apps. Unset = send to every device.
    "$STK_PY" recipes/stk_send.py send "$OUT" --title "FT myFT $TODAY" \
        ${KINDLE_DEVICE_SERIAL:+--device "$KINDLE_DEVICE_SERIAL"}
else
    calibre-smtp \
        --attachment "$OUT" \
        --relay "${SMTP_HOST:-smtp.gmail.com}" \
        --port "${SMTP_PORT:-587}" \
        --username "$SMTP_USER" \
        --password "$SMTP_PASS" \
        --encryption-method TLS \
        --subject "FT myFT $TODAY" \
        "$SMTP_USER" "$KINDLE_EMAIL" \
        "Today's myFT edition, delivered by calibre."
fi

echo "$TODAY" > "$STAMP"
echo "$(date) done"

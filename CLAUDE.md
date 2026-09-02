# ft-to-kindle — agent notes

Delivers a personal myFT feed to a Kindle daily, locally via launchd on a
Mac. **README.md is the canonical doc** — it has the full new-machine
runbook ("Setting up on a new Mac") and a troubleshooting table. Read it
before changing anything.

Hard constraints (each one broke in production before; details in README):

- FT 403s datacenter IPs → never move fetching to CI/cloud runners.
- FT 403s non-OpenSSL-3.x TLS stacks and cookie-less bursts → all
  fetching must go through `recipes/ft_fetch.py` with `FT_FETCH_PYTHON`.
- Macs sleep through early-morning slots → the launchd job must keep
  `caffeinate -is` and the hourly retry slots.
- Some corporate/managed networks block outbound SMTP → send via
  `recipes/stk_send.py` (Send to Kindle over HTTPS); calibre-smtp is a
  fallback only. Target the device by exact serial, not name.
- Stock stkclient registers one shared device serial for every install
  worldwide, so registrations die when anyone else registers →
  `stk_send.py` must keep its unique per-machine serial patch.

Secrets live in `~/.config/ft-to-kindle/` (env, ft-cookies.txt,
stk-client.json) — never commit or print them. The stamp file
`~/.local/state/ft-to-kindle/last-sent` dedupes to one delivery/day.

To verify a change works: delete the stamp, `launchctl kickstart
gui/$(id -u)/local.ft-to-kindle`, and watch
`~/Library/Logs/ft-to-kindle.log` until "done".

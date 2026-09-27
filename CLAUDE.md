# ft-to-kindle — agent notes

Delivers a personal myFT feed to a Kindle daily from the user's own
machine. Python package `src/ft2k/`, CLI `ft2k` (`cli.py`): `setup` wizard,
`run`, `doctor`, `status`, `install`. **README.md is the canonical doc**;
its "Why it works this way" section lists production failures that shape
the design - read it before changing anything.

Layout: `config.py` (paths + Settings, plain KEY=value file),
`cookies.py` (ft.com login via browser_cookie3, all Chromium profiles),
`ft_fetch.py` (standalone per-article fetcher spawned by the recipe; no
package imports), `stk.py` (Send to Kindle + unique-serial patch),
`runner.py` (the daily job), `scheduler.py` (launchd / systemd units are
generated, never templated files), `recipes/myft.recipe` (calibre).

Hard constraints (each broke in production before):

- FT 403s datacenter IPs → never move fetching to CI/cloud runners.
- FT 403s non-OpenSSL-3.x TLS stacks and cookie-less bursts → all
  fetching goes through `ft_fetch.py` under `runner.fetch_python()`.
- Machines sleep through early slots → scheduler must keep the sleep
  inhibitor (`caffeinate -is` / `systemd-inhibit`) and hourly retries.
- Some networks block SMTP → deliver via `stk.py` (HTTPS); calibre-smtp
  is fallback only. Target the device by exact serial.
- Stock stkclient shares one device serial worldwide → keep
  `stk._unique_serial()`.

Secrets live in `~/.config/ft-to-kindle/` — never commit or print them.
Stamp `~/.local/state/ft-to-kindle/last-sent` dedupes to one send/day.

Dev loop: `uv venv && uv pip install -e .`, then `.venv/bin/ft2k doctor`
and `.venv/bin/ft2k run --force --no-send --keep /tmp/x.epub` to test a
build without sending. Release: bump `__version__` + pyproject, tag
`vX.Y.Z`, update `Formula/ft-to-kindle.rb` sha256s, push to the tap.

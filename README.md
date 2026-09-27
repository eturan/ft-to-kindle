# FT to Kindle

Your personal **myFT** feed — the topics, companies and columnists you
follow on ft.com — delivered to your Kindle every morning as an e-book.

Runs on your own Mac or Linux machine: each morning it fetches the day's
articles, builds an EPUB with calibre, and pushes it to your Kindle over
Amazon's Send to Kindle service. Nothing leaves your computer except the
finished e-book going to Amazon.

> **You need your own FT subscription.** This tool reads FT with *your*
> login, from *your* connection, for *your* personal reading — the same
> articles you could read in the browser, reformatted for an e-reader.
> Don't use it to redistribute FT content or to read without a subscription.

## Install

**macOS (Homebrew)**

```sh
brew install eturan/tap/ft-to-kindle
ft2k setup
```

**Linux / any OS with [uv](https://docs.astral.sh/uv/)**

```sh
uv tool install ft-to-kindle          # or: pipx install ft-to-kindle
ft2k setup
```

You also need [calibre](https://calibre-ebook.com) (`brew install --cask
calibre`, `sudo pacman -S calibre`, `sudo apt install calibre`…). The
Homebrew formula installs it for you; on Linux `setup` tells you the
command.

## Setup

`ft2k setup` walks you through everything, checking each step as it goes.
It takes about three minutes:

1. **Tools** — finds calibre (offers to install it on a Mac).
2. **Your myFT feed** — paste the RSS link from *myFT → Following* on
   ft.com; it confirms how many articles it sees.
3. **Your ft.com login** — you just need to be signed in to ft.com in a
   browser on this computer (Chrome, Firefox, Safari, Brave, Edge, Arc…).
   The login is re-read every morning, so it never goes stale.
4. **Amazon** — opens the Amazon sign-in page; paste back the address you
   land on. Then pick your Kindle from a numbered list.
5. **Schedule** — installs a daily job (launchd on macOS, a systemd user
   timer on Linux) and offers to send a test edition right away.

Re-run `ft2k setup` any time; it keeps what already works.

## Day to day

```
ft2k status        schedule, last delivery, recent log lines
ft2k doctor        check every part of the setup and say what's wrong
ft2k run --force   send today's edition now (even if one already went)
ft2k log -f        follow the log
ft2k devices       Kindles on your Amazon account
ft2k send FILE     send any EPUB/PDF to your Kindle
ft2k config        show settings; --set KEY=VALUE to change one
ft2k uninstall     remove the schedule (--purge also removes credentials)
```

Delivery is attempted at 07:00 and retried hourly until 12:00, so a
laptop that was asleep or offline at 07:00 still gets its paper. Only one
edition is sent per day.

## Troubleshooting

Run `ft2k doctor` first — it checks each piece and prints what to do.

- **Edition is thin or articles are teasers** — your ft.com login wasn't
  found. Sign in to ft.com in your browser (any profile) and run `ft2k
  doctor`. If you use a browser ft2k can't read, export a `cookies.txt`
  and choose option 2 in `ft2k setup`.
- **"Failed to validate DeviceInfoToken"** — Amazon invalidated the
  connection; run `ft2k setup --reregister`.
- **Paper arrives on your phone too** — pick the Kindle (not a reading
  app) in `ft2k setup`, or `ft2k config --set KINDLE_DEVICE_SERIAL=…`
  with a serial from `ft2k devices`.
- **Nothing ran** — `ft2k status` shows whether the schedule is
  installed; `ft2k install` re-installs it (do this after upgrading).
- **macOS asks for Keychain access** the first time cookies are read
  from Chrome-based browsers — click *Always Allow* so the morning run
  doesn't wait on a prompt.

## Why it works this way

Each of these was a real failure in production. Don't undo them without
re-testing:

1. **It runs on your machine, not in the cloud.** FT's bot protection
   returns HTTP 403 for article pages fetched from datacenter IPs (GitHub
   Actions, Railway, …) regardless of login. An earlier GitHub-Actions
   version "worked" — it mailed a 37 KB *empty* paper every morning.
2. **Articles are fetched by an OpenSSL 3.x python.** FT also filters
   on TLS fingerprint: calibre's bundled OpenSSL, macOS LibreSSL and curl
   get 403; OpenSSL 3.x is served normally. Per-article fetches go
   through `ft_fetch.py`, which also keeps session cookies across calls —
   cookie-less request bursts get blocked.
3. **A sleep inhibitor wraps the run** (`caffeinate -is` /
   `systemd-inhibit`). A 07:00 slot usually fires during a ~1-minute
   DarkWake; without an assertion the machine re-sleeps mid-run and TLS
   handshakes time out. Hourly retries cover a slot that still misses.
4. **Delivery is HTTPS (Send to Kindle), not SMTP.** Some
   corporate/managed networks block outbound SMTP. An SMTP fallback via
   `calibre-smtp` remains for machines where Amazon isn't connected
   (`ft2k config --set SMTP_USER=…` etc.).
5. **Registration uses a unique per-machine device serial.** Stock
   `stkclient` hardcodes one serial for every install worldwide, so any
   other user's registration invalidates yours within hours (upstream
   [PR #199](https://github.com/maxdjohnson/stkclient/pull/199), closed
   unmerged). ft2k derives the serial from your user@host.

## Files

All private data lives in `~/.config/ft-to-kindle/` (mode 0600):
`env` (settings: feed URL, Kindle serial), `ft-cookies.txt` (your ft.com
session), `stk-client.json` (Amazon tokens). Run state is in
`~/.local/state/ft-to-kindle/`; the log is there on Linux and in
`~/Library/Logs/ft-to-kindle.log` on macOS.

## Development

```sh
git clone https://github.com/eturan/ft-to-kindle && cd ft-to-kindle
uv venv && uv pip install -e .
.venv/bin/ft2k doctor
```

`src/ft2k/recipes/myft.recipe` is calibre's upstream Financial Times
recipe with the feed swapped for myFT and fetching routed through
`ft_fetch.py`. If FT changes their markup, refresh the extraction parts
from [upstream](https://raw.githubusercontent.com/kovidgoyal/calibre/master/recipes/financial_times.recipe).

Not affiliated with the Financial Times or Amazon.

## License

GPL-3.0 (see `LICENSE`). The recipes derive from
[calibre](https://github.com/kovidgoyal/calibre)'s Financial Times recipe
(GPL-3.0, © Kovid Goyal and contributors); `stk.py` adapts one function
from [stkclient](https://github.com/maxdjohnson/stkclient) (MIT, © Max
Johnson).

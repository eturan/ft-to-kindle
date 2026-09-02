# FT to Kindle

Daily delivery of your personal **myFT** feed (the topics, companies, and
columnists you follow on ft.com) to your Kindle. Runs **locally on a Mac
via launchd** — every morning it fetches the day's articles, builds an
EPUB with calibre, and pushes it to your Kindle over Amazon's Send to
Kindle service (HTTPS).

> **You need your own FT subscription.** This tool reads FT with *your*
> login (session cookies), from *your* home connection, for *your*
> personal reading — the same articles you could read in the browser,
> reformatted for an e-reader. It is for personal use only: don't use it
> to redistribute FT content or to read without a subscription.

```
launchd (07:00, retries hourly until 12:00, caffeinate keeps Mac awake)
  └─ run-local.sh
       ├─ wait for network (nc to ft.com:443)
       ├─ ebook-convert recipes/myft.recipe  → EPUB
       │    └─ per-article fetch via recipes/ft_fetch.py
       │       (OpenSSL 3.x python + session cookies; FT 403s other TLS stacks)
       └─ recipes/stk_send.py send            → Kindle, over HTTPS
            (fallback: calibre-smtp email, only if stk isn't registered)
```

## Why it works this way (read before "simplifying")

Each of these was a real failure in production; don't undo them without
re-testing:

1. **No cloud runners.** FT's bot protection returns HTTP 403 ("Security
   Verification") for article pages fetched from datacenter IPs (GitHub
   Actions, Railway, …) regardless of login. Fetching needs a
   **residential IP** — a Mac or a small home device. (An earlier
   GitHub-Actions version of this project "worked" — it mailed a 37KB
   *empty* paper every morning because every article came back 403.)
2. **Fetch goes through `ft_fetch.py` with a specific python.** FT also
   filters on TLS fingerprint: calibre's bundled OpenSSL, macOS LibreSSL,
   and curl all get 403; an OpenSSL 3.x python (Homebrew python3) is
   served normally. The helper also keeps session cookies across the
   per-article subprocess calls — cookie-less request bursts get blocked.
3. **`caffeinate -is` + hourly retry slots in the launchd plist.** An
   early-morning slot usually fires during a ~1-minute DarkWake; without
   a sleep assertion the Mac re-sleeps mid-run and TLS handshakes time
   out. Retries at 08:00–12:00 cover a slot that still misses; the stamp
   file keeps delivery to once/day.
4. **Send is HTTPS (Send to Kindle), not SMTP.** Some corporate/managed
   networks block outbound SMTP (ports 25/465/587) to personal mail
   providers. `recipes/stk_send.py` uses the
   [`stkclient`](https://pypi.org/project/stkclient/) library — Amazon
   OAuth once, then token sends over 443. calibre-smtp remains only as a
   fallback for machines where SMTP works and stk isn't registered.
5. **Registration uses a unique per-machine device serial.** Stock
   stkclient 0.1.1 hardcodes one serial for every install worldwide, so
   any other user's registration invalidates yours within hours
   (403 `"Failed to validate DeviceInfoToken"`; upstream
   [PR #199](https://github.com/maxdjohnson/stkclient/pull/199), closed
   unmerged). `stk_send.py` registers a serial derived from your
   user@host instead.

## Setting up on a new Mac (agent runbook)

Prereqs: an FT subscription, an Amazon account with the target Kindle,
Homebrew.

```sh
# 0. Clone and install tools
git clone https://github.com/eturan/ft-to-kindle
cd ft-to-kindle
brew install --cask calibre        # provides ebook-convert, calibre-smtp
brew install python3               # OpenSSL 3.x python for ft_fetch.py

# 1. Config file (values live outside the repo)
mkdir -p ~/.config/ft-to-kindle
cp env.example ~/.config/ft-to-kindle/env
chmod 600 ~/.config/ft-to-kindle/env
$EDITOR ~/.config/ft-to-kindle/env   # fill in each value; comments explain
```

- `MYFT_RSS_URL`: on ft.com open **myFT → Following** and copy the RSS
  URL. It embeds a personal ID and works without login — treat it like a
  password.
- `FT_FETCH_PYTHON`: any python linked against OpenSSL 3.x
  (`python3 -c 'import ssl; print(ssl.OPENSSL_VERSION)'` must say
  OpenSSL 3.x, not LibreSSL).

```sh
# 2. FT subscription cookies (full articles; without them premium
#    articles come through as paywall teasers)
# FT's login page has a CAPTCHA, so export cookies from a browser where
# you're logged in to ft.com — e.g. the "Get cookies.txt LOCALLY"
# extension, Netscape cookies.txt format:
#   save as ~/.config/ft-to-kindle/ft-cookies.txt && chmod 600 it
# This file IS your FT login. Refresh it when a run drops to teasers only.

# 3. Send to Kindle registration (one-time, interactive)
python3 -m venv ~/.config/ft-to-kindle/stk-venv
~/.config/ft-to-kindle/stk-venv/bin/pip install stkclient
STK=~/.config/ft-to-kindle/stk-venv/bin/python
$STK recipes/stk_send.py login-url     # prints an Amazon sign-in URL
# → open it, sign in, copy the URL of the landing page
#   (contains openid.oa2.authorization_code=...)
$STK recipes/stk_send.py register '<that full URL, single-quoted>'
$STK recipes/stk_send.py devices       # lists Kindles + serials
# → put the target Kindle's serial in KINDLE_DEVICE_SERIAL in the env
#   file (use the SERIAL — name substrings also match the phone/Mac
#   reading apps)

# 4. Install the launchd agent (fills in the repo path + home dir)
sed -e "s|__FT2K_DIR__|$(pwd)|" -e "s|__FT2K_HOME__|$HOME|" \
    launchd/local.ft-to-kindle.plist \
    > ~/Library/LaunchAgents/local.ft-to-kindle.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.ft-to-kindle.plist
# (bootstrap also fires a run immediately via RunAtLoad)

# 5. Verify end-to-end
tail -f ~/Library/Logs/ft-to-kindle.log
# success looks like: "fetching myFT..." → per-article download lines →
# "sending to kindle..." → "sent ... to <device>" → "done"
```

## Operations

- **Log**: `~/Library/Logs/ft-to-kindle.log`
- **Once-per-day stamp**: `~/.local/state/ft-to-kindle/last-sent` holds
  the date last delivered. Delete it + `launchctl kickstart
  gui/$(id -u)/local.ft-to-kindle` to force a re-send today.
- **Manual one-off send**:
  `~/.config/ft-to-kindle/stk-venv/bin/python recipes/stk_send.py send
  file.epub --title '...' --device <serial>`
- **Schedule**: hourly slots 07:00–12:00 in
  `launchd/local.ft-to-kindle.plist`; first slot that succeeds wins.
  After editing the plist: re-run the `sed` install line, then
  `launchctl bootout gui/$(id -u)/local.ft-to-kindle` and `bootstrap` it
  again.
- **Article window**: `recipes/myft.recipe` takes ~28h of articles
  (`oldest_article = 1.15` days), max 50 per day.

## Troubleshooting

| Symptom | Likely cause / fix |
| --- | --- |
| Empty/thin paper, log full of 403s | Running from a datacenter IP, or FT session cookies expired (re-export `ft-cookies.txt`), or wrong `FT_FETCH_PYTHON` (must be OpenSSL 3.x). |
| `No articles found, aborting` + TLS handshake timeouts | No usable network when the run fired (Mac in DarkWake). Should self-heal at the next hourly slot; check the plist still wraps the job in `caffeinate -is`. |
| Built the EPUB but send times out | If using the SMTP fallback: outbound SMTP is blocked on your network (common on corporate-managed machines) — do the `stk_send.py` registration instead. |
| `stk-client.json not found` | One-time registration not done on this machine (setup step 3). |
| Send fails: `403 ... "Failed to validate DeviceInfoToken"` | Amazon invalidated the registration — redo setup step 3 (login-url/register). Rare with this repo's per-machine serial; see "Why it works this way" #5. |
| Paper arrives on phone/iPad apps too | `KINDLE_DEVICE_SERIAL` isn't set to the exact serial in the env file. |
| Nothing ran at all | `launchctl list \| grep ft-to-kindle`; re-bootstrap the plist. Also check `~/.config/ft-to-kindle/env` exists — the script exits early without it. |

## Secrets inventory (never commit these)

All under `~/.config/ft-to-kindle/`, all `chmod 600`:

- `env` — myFT feed URL (personal ID), Kindle serial, optional SMTP app
  password
- `ft-cookies.txt` — FT login session
- `stk-client.json` — Amazon Send to Kindle OAuth tokens

## Notes

- `recipes/myft.recipe` is calibre's upstream Financial Times recipe with
  the feed swapped for myFT and fetching routed through `ft_fetch.py`. If
  FT changes their markup, refresh the extraction parts from
  [upstream](https://raw.githubusercontent.com/kovidgoyal/calibre/master/recipes/financial_times.recipe).
- `recipes/financial_times.recipe` is the stock section-based full paper,
  kept in case you want a second edition.
- Not affiliated with the Financial Times or Amazon.

## License

GPL-3.0 (see `LICENSE`). The recipes derive from
[calibre](https://github.com/kovidgoyal/calibre)'s Financial Times recipe
(GPL-3.0, © Kovid Goyal and contributors);
`recipes/stk_send.py` adapts one function from
[stkclient](https://github.com/maxdjohnson/stkclient) (MIT, © Max
Johnson).

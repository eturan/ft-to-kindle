"""ft2k command line: setup wizard, run, doctor, status, devices, install."""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from pathlib import Path

from . import __version__, config, cookies, runner, scheduler, stk

MYFT_RE = re.compile(r"^https://www\.ft\.com/myft/following/[0-9a-f-]{36}\.rss$")


# --- small terminal helpers --------------------------------------------------

def ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def warn(msg: str) -> None:
    print(f"  ! {msg}")


def fail(msg: str) -> None:
    print(f"  ✗ {msg}")


def step(n: int, total: int, title: str) -> None:
    print(f"\n[{n}/{total}] {title}")


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"  {prompt}{suffix}: ").strip()
    except EOFError:
        print()
        sys.exit(1)
    return val or default


def confirm(prompt: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    v = ask(f"{prompt} ({d})").lower()
    if not v:
        return default
    return v.startswith("y")


def open_in_browser(url: str) -> None:
    try:
        if not webbrowser.open(url):
            raise RuntimeError
    except Exception:  # noqa: BLE001
        print(f"  Open this URL in your browser:\n  {url}")


# --- checks (shared by setup and doctor) ------------------------------------

def check_calibre() -> tuple[bool, str]:
    p = runner.find_calibre_tool("ebook-convert")
    if not p:
        return False, "calibre not found"
    try:
        v = subprocess.check_output([p, "--version"], text=True, timeout=30,
                                    env=runner.calibre_env(), stderr=subprocess.DEVNULL).splitlines()[0]
    except Exception:  # noqa: BLE001
        v = p
    return True, v


def install_calibre_hint() -> str:
    if config.IS_MAC:
        return "brew install --cask calibre"
    if shutil.which("pacman"):
        return "sudo pacman -S calibre"
    if shutil.which("apt-get"):
        return "sudo apt install calibre"
    if shutil.which("dnf"):
        return "sudo dnf install calibre"
    return "https://calibre-ebook.com/download"


def try_install_calibre() -> bool:
    if config.IS_MAC and shutil.which("brew"):
        if confirm("calibre is missing. Install it now with Homebrew?"):
            r = subprocess.run(["brew", "install", "--cask", "calibre"])
            return r.returncode == 0 and check_calibre()[0]
    return False


def check_feed(url: str) -> tuple[bool, str]:
    if not MYFT_RE.match(url):
        return False, ("that doesn't look like a myFT feed URL "
                       "(expected https://www.ft.com/myft/following/<id>.rss)")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        root = ET.fromstring(data)
        items = root.findall(".//item")
        first = items[0].findtext("title", "") if items else ""
        return True, f"{len(items)} articles in your feed" + (f' - latest: "{first[:60]}"' if first else "")
    except Exception as e:  # noqa: BLE001
        return False, f"could not read the feed: {e}"


# --- setup wizard -----------------------------------------------------------

def cmd_setup(args) -> int:
    total = 5
    print(f"ft-to-kindle {__version__} setup\n"
          "Every morning this fetches the articles you follow on myFT, builds\n"
          "an e-book and sends it to your Kindle. Everything runs on this\n"
          "computer; your credentials never leave it.")
    config.ensure_dirs()
    settings = config.Settings.load()

    # 1. tools
    step(1, total, "Checking tools")
    have, info = check_calibre()
    if not have and not try_install_calibre():
        fail(f"calibre is required (provides the e-book builder).\n    Install it:  {install_calibre_hint()}\n    then run `ft2k setup` again.")
        return 1
    ok(info)
    py = runner.fetch_python(settings)
    good, ver = runner.openssl_ok(py)
    if good:
        ok(f"python with {ver}")
    else:
        # ft2k's own interpreter is nearly always OpenSSL 3 (uv/brew/distro
        # pythons). LibreSSL means a bare macOS system python.
        warn(f"{py} reports {ver}; FT rejects non-OpenSSL-3 TLS stacks")
        alt = shutil.which("python3.12") or shutil.which("python3") or ""
        if alt and runner.openssl_ok(alt)[0]:
            settings.FT_FETCH_PYTHON = alt
            ok(f"using {alt} for fetching instead")
        else:
            fail("install a Homebrew python (`brew install python`) and re-run setup")
            return 1

    # 2. feed
    step(2, total, "Your myFT feed")
    print("  On ft.com open  myFT → Following  and copy the RSS link\n"
          "  (it looks like https://www.ft.com/myft/following/….rss).")
    while True:
        url = ask("myFT RSS URL", settings.MYFT_RSS_URL)
        good, info = check_feed(url)
        if good:
            ok(info)
            settings.MYFT_RSS_URL = url
            break
        fail(info)
        if not confirm("Try again?"):
            return 1
    settings.save()

    # 3. cookies
    step(3, total, "Your ft.com login")
    print("  Full articles need your FT subscription. ft2k reuses the login of\n"
          "  a browser on this computer - make sure you're signed in to ft.com.")
    while True:
        res = cookies.find_logged_in("auto")
        if res and res.logged_in:
            cookies.export_to_file(res.jar)
            settings.FT_COOKIE_SOURCE = "browser"
            settings.FT_COOKIE_BROWSER = res.browser
            ok(f"signed in to ft.com in {res.browser} ({len(res)} cookies) - will be re-read every morning")
            break
        if res:
            warn(f"found ft.com cookies in {res.browser}, but you're not signed in")
        else:
            warn("no browser with ft.com cookies found")
        print("  Options: (1) sign in to ft.com in your browser, then retry\n"
              "           (2) point to an exported cookies.txt file\n"
              "           (3) skip - articles will come through as teasers")
        choice = ask("Choice", "1")
        if choice == "2":
            p = Path(ask("Path to cookies.txt")).expanduser()
            if p.exists():
                shutil.copy2(p, config.COOKIE_FILE)
                config.COOKIE_FILE.chmod(0o600)
                settings.FT_COOKIE_SOURCE = "file"
                if cookies.file_is_logged_in():
                    ok("cookie file has an ft.com login")
                else:
                    warn("cookie file has no ft.com session cookie - continuing anyway")
                break
            fail(f"{p} not found")
        elif choice == "3":
            break
    settings.save()

    # 4. amazon
    step(4, total, "Send to Kindle (Amazon)")
    if stk.is_registered() and not args.reregister:
        try:
            devs = stk.devices()
            ok(f"already connected to Amazon ({len(devs)} devices)")
        except Exception as e:  # noqa: BLE001
            warn(f"stored Amazon credentials don't work ({e}); reconnecting")
            devs = None
    else:
        devs = None
    if devs is None:
        print("  A browser window will open to sign in to Amazon. After signing in\n"
              "  you land on a page that may look blank or show an error - that's\n"
              "  expected. Copy the FULL address of that page and paste it here.")
        url = stk.login_url()
        input("  Press Enter to open the Amazon sign-in page...")
        open_in_browser(url)
        while True:
            redirect = ask("Paste the address you landed on")
            if "openid.oa2.authorization_code" not in redirect:
                fail("that address has no authorization code in it - copy the whole URL bar")
                continue
            try:
                devs = stk.register(redirect)
                ok("connected to Amazon")
                break
            except Exception as e:  # noqa: BLE001
                fail(f"registration failed: {e}")
                if not confirm("Try again?"):
                    return 1
    APP_WORDS = ("iphone", "ipad", "for mac", "for pc", "android", "for windows")
    kindles = [d for d in devs if not any(w in d.name.lower() for w in APP_WORDS)] or devs
    if not devs:
        fail("no devices on this Amazon account")
        return 1
    print("  Devices on your Amazon account:")
    for i, d in enumerate(devs, 1):
        tag = "" if d in kindles else "  (reading app)"
        print(f"    {i}) {d.name}{tag}")
    default_idx = next((i for i, d in enumerate(devs, 1)
                        if d.serial == settings.KINDLE_DEVICE_SERIAL), None)
    if default_idx is None and len(kindles) == 1:
        default_idx = devs.index(kindles[0]) + 1
    while True:
        pick = ask("Which one gets the paper?", str(default_idx) if default_idx else "")
        if pick.isdigit() and 1 <= int(pick) <= len(devs):
            chosen = devs[int(pick) - 1]
            settings.KINDLE_DEVICE_SERIAL = chosen.serial
            ok(f"deliver to {chosen.name}")
            break
        fail("enter one of the numbers above")
    settings.save()

    # 5. schedule + test
    step(5, total, "Daily schedule")
    try:
        ok(scheduler.install())
    except Exception as e:  # noqa: BLE001
        warn(f"could not install the schedule: {e}\n    You can run `ft2k run` by hand or retry `ft2k install`.")
    hours = config.SCHEDULE_HOURS
    print(f"  Delivery is attempted at {hours[0]:02d}:00 and retried hourly until "
          f"{hours[-1]:02d}:00 if the computer was asleep/offline.")
    print(f"\nSetup complete. Log: {config.LOG_FILE}")
    if confirm("Send a test edition to your Kindle now?"):
        return runner.run(force=True)
    print("Run `ft2k run --force` any time to send one by hand.")
    return 0


# --- other commands ---------------------------------------------------------

def cmd_run(args) -> int:
    try:
        return runner.run(force=args.force, keep=Path(args.keep).expanduser() if args.keep else None,
                          no_send=args.no_send)
    except stk.NotRegistered as e:
        runner.log(str(e))
        return 2
    except subprocess.CalledProcessError as e:
        runner.log(f"step failed: {e}")
        return 1


def cmd_doctor(_args) -> int:
    print(f"ft-to-kindle {__version__} doctor")
    problems = 0
    settings = config.Settings.load()

    have, info = check_calibre()
    (ok if have else fail)(info if have else f"calibre missing - {install_calibre_hint()}")
    problems += not have

    py = runner.fetch_python(settings)
    good, ver = runner.openssl_ok(py)
    (ok if good else fail)(f"fetch python {py}: {ver}")
    problems += not good

    if settings.MYFT_RSS_URL:
        good, info = check_feed(settings.MYFT_RSS_URL)
        (ok if good else fail)(f"myFT feed: {info}")
        problems += not good
    else:
        fail("myFT feed not configured (ft2k setup)")
        problems += 1

    if settings.FT_COOKIE_SOURCE == "browser":
        res = cookies.find_logged_in(settings.FT_COOKIE_BROWSER)
        if res and res.logged_in:
            ok(f"ft.com login: signed in ({res.browser})")
        else:
            warn(f"ft.com login: not signed in in {settings.FT_COOKIE_BROWSER} - "
                 f"{'last saved login still valid' if cookies.file_is_logged_in() else 'articles will be teasers'}")
    else:
        (ok if cookies.file_is_logged_in() else warn)(f"ft.com login: cookie file {config.COOKIE_FILE}")

    if stk.is_registered():
        try:
            devs = stk.devices()
            target = next((d for d in devs if d.serial == settings.KINDLE_DEVICE_SERIAL), None)
            if target:
                ok(f"Amazon: connected, delivering to {target.name}")
            elif settings.KINDLE_DEVICE_SERIAL:
                fail("Amazon: connected, but the chosen Kindle is no longer on the account")
                problems += 1
            else:
                warn(f"Amazon: connected, no device chosen - sends to all {len(devs)}")
        except Exception as e:  # noqa: BLE001
            fail(f"Amazon: credentials rejected ({e}) - run `ft2k setup --reregister`")
            problems += 1
    elif settings.uses_smtp_fallback:
        warn("Amazon: not connected; using the SMTP fallback")
    else:
        fail("Amazon: not connected (ft2k setup)")
        problems += 1

    sched = scheduler.status()
    (ok if sched.startswith("installed") else warn)(f"schedule: {sched}")

    if config.STAMP_FILE.exists():
        ok(f"last delivered: {config.STAMP_FILE.read_text().strip()}")
    else:
        warn("never delivered yet")
    print(f"\n{'all good' if not problems else f'{problems} problem(s)'} - log at {config.LOG_FILE}")
    return 1 if problems else 0


def cmd_status(_args) -> int:
    settings = config.Settings.load()
    print(f"schedule:  {scheduler.status()}")
    print(f"last sent: {config.STAMP_FILE.read_text().strip() if config.STAMP_FILE.exists() else 'never'}")
    print(f"kindle:    {settings.KINDLE_DEVICE_SERIAL or '(all devices)'}")
    print(f"log:       {config.LOG_FILE}")
    if config.LOG_FILE.exists():
        tail = config.LOG_FILE.read_text().splitlines()[-8:]
        print("\n".join("  " + l for l in tail))
    return 0


def cmd_devices(_args) -> int:
    try:
        for d in stk.devices():
            print(f"{d.serial}  {d.name}")
    except stk.NotRegistered as e:
        print(e)
        return 2
    return 0


def cmd_send(args) -> int:
    settings = config.Settings.load()
    p = Path(args.file).expanduser()
    devs = stk.send(p, title=args.title, serial=args.device or settings.KINDLE_DEVICE_SERIAL or None)
    print(f"sent {p.name} to {', '.join(d.name for d in devs)}")
    return 0


def cmd_install(_args) -> int:
    print(scheduler.install())
    return 0


def cmd_uninstall(args) -> int:
    print(scheduler.uninstall())
    if args.purge:
        shutil.rmtree(config.CONFIG_DIR, ignore_errors=True)
        shutil.rmtree(config.STATE_DIR, ignore_errors=True)
        print(f"removed {config.CONFIG_DIR} and {config.STATE_DIR}")
    return 0


def cmd_log(args) -> int:
    if not config.LOG_FILE.exists():
        print(f"no log yet at {config.LOG_FILE}")
        return 0
    if args.follow:
        subprocess.call(["tail", "-n", "40", "-f", str(config.LOG_FILE)])
    else:
        print("\n".join(config.LOG_FILE.read_text().splitlines()[-args.lines:]))
    return 0


def cmd_config(args) -> int:
    settings = config.Settings.load()
    if args.set:
        key, _, val = args.set.partition("=")
        if not hasattr(settings, key) or key.startswith("_"):
            print(f"unknown setting {key}")
            return 1
        setattr(settings, key, val)
        settings.save()
        print(f"{key} updated")
        return 0
    for k, v in vars(settings).items():
        if k.startswith("_"):
            continue
        if k in ("SMTP_PASS",) and v:
            v = "********"
        if k == "MYFT_RSS_URL" and v:
            v = v[:40] + "…"
        print(f"{k}={v}")
    print(f"\nfile: {config.SETTINGS_FILE}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ft2k", description="Deliver your myFT feed to your Kindle every morning.")
    p.add_argument("--version", action="version", version=f"ft-to-kindle {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("setup", help="interactive first-time setup (safe to re-run)")
    s.add_argument("--reregister", action="store_true", help="redo the Amazon sign-in")
    s.set_defaults(func=cmd_setup)

    r = sub.add_parser("run", help="build and send today's edition")
    r.add_argument("--force", action="store_true", help="send even if already sent today")
    r.add_argument("--keep", metavar="PATH", help="also save the EPUB here")
    r.add_argument("--no-send", action="store_true", help="build only")
    r.set_defaults(func=cmd_run)

    sub.add_parser("doctor", help="check every part of the setup").set_defaults(func=cmd_doctor)
    sub.add_parser("status", help="schedule, last delivery, recent log").set_defaults(func=cmd_status)
    sub.add_parser("devices", help="list Kindles on the Amazon account").set_defaults(func=cmd_devices)

    sd = sub.add_parser("send", help="send any file to the Kindle")
    sd.add_argument("file")
    sd.add_argument("--title")
    sd.add_argument("--device", help="serial; default from settings")
    sd.set_defaults(func=cmd_send)

    sub.add_parser("install", help="(re)install the daily schedule").set_defaults(func=cmd_install)
    u = sub.add_parser("uninstall", help="remove the daily schedule")
    u.add_argument("--purge", action="store_true", help="also delete settings and credentials")
    u.set_defaults(func=cmd_uninstall)

    lg = sub.add_parser("log", help="show the log")
    lg.add_argument("-f", "--follow", action="store_true")
    lg.add_argument("-n", "--lines", type=int, default=40)
    lg.set_defaults(func=cmd_log)

    c = sub.add_parser("config", help="show or change a setting")
    c.add_argument("--set", metavar="KEY=VALUE")
    c.set_defaults(func=cmd_config)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    sys.exit(main())

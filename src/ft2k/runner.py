"""The daily job: wait for network, build the EPUB with calibre, send it."""
from __future__ import annotations

import datetime as dt
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import config, cookies, stk

RECIPE = Path(__file__).parent / "recipes" / "myft.recipe"
FETCH_HELPER = Path(__file__).parent / "ft_fetch.py"

# Extra places to look for calibre when launched from a bare launchd/systemd
# environment (no user PATH).
CALIBRE_PATHS = [
    "/opt/homebrew/bin", "/usr/local/bin",
    "/Applications/calibre.app/Contents/MacOS",
    os.path.expanduser("~/Applications/calibre.app/Contents/MacOS"),
    "/usr/bin",
]


def log(msg: str) -> None:
    print(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


def find_calibre_tool(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for d in CALIBRE_PATHS:
        p = Path(d) / name
        if p.exists():
            return str(p)
    return None


def fetch_python(settings: config.Settings) -> str:
    """Interpreter for ft_fetch.py: must link OpenSSL 3.x."""
    if settings.FT_FETCH_PYTHON:
        return settings.FT_FETCH_PYTHON
    return sys.executable


def openssl_ok(python: str) -> tuple[bool, str]:
    try:
        out = subprocess.check_output(
            [python, "-c", "import ssl; print(ssl.OPENSSL_VERSION)"],
            text=True, timeout=20).strip()
    except Exception as e:  # noqa: BLE001
        return False, str(e)
    return out.startswith("OpenSSL 3."), out


def wait_for_network(host: str = "www.ft.com", port: int = 443, attempts: int = 24) -> bool:
    """Coming out of sleep the network can take a while; up to ~4 minutes."""
    for i in range(attempts):
        try:
            with socket.create_connection((host, port), timeout=5):
                return True
        except OSError:
            if i == 0:
                log("waiting for network...")
            time.sleep(10)
    return False


def already_sent_today(today: str) -> bool:
    return config.STAMP_FILE.exists() and config.STAMP_FILE.read_text().strip() == today


def mark_sent(today: str) -> None:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    config.STAMP_FILE.write_text(today + "\n")


def calibre_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for calibre tools.

    calibre's launchers start with ``#!/usr/bin/env python3``; on a user's
    shell that puts pyenv/uv/conda pythons first they'd pick an interpreter
    without calibre's modules. Put the system dirs first and drop python
    env vars that would leak into calibre's interpreter.
    """
    env = dict(base if base is not None else os.environ)
    for k in list(env):
        if k.startswith(("PYTHON", "VIRTUAL_ENV", "CONDA", "PYENV", "UV_")):
            del env[k]
    system = ["/usr/bin", "/bin", "/usr/local/bin", "/opt/homebrew/bin"]
    if config.IS_MAC:
        system = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
    rest = [p for p in env.get("PATH", "").split(os.pathsep) if p and p not in system]
    env["PATH"] = os.pathsep.join(system + rest)
    return env


def build_epub(settings: config.Settings, out: Path, cookie_file: Path | None) -> None:
    ebook_convert = find_calibre_tool("ebook-convert")
    if not ebook_convert:
        raise RuntimeError("calibre's ebook-convert not found - install calibre "
                           "(brew install --cask calibre / sudo pacman -S calibre)")
    env = calibre_env()
    env["MYFT_RSS_URL"] = settings.MYFT_RSS_URL
    env["FT_FETCH_PYTHON"] = fetch_python(settings)
    env["FT_FETCH_HELPER"] = str(FETCH_HELPER)
    if cookie_file:
        env["FT_COOKIE_FILE"] = str(cookie_file)
    subprocess.run([ebook_convert, str(RECIPE), str(out)], env=env, check=True)


def send_epub(settings: config.Settings, out: Path, title: str) -> str:
    if stk.is_registered():
        devs = stk.send(out, title=title, serial=settings.KINDLE_DEVICE_SERIAL or None)
        return ", ".join(d.name for d in devs)
    if settings.uses_smtp_fallback:
        calibre_smtp = find_calibre_tool("calibre-smtp")
        if not calibre_smtp:
            raise RuntimeError("calibre-smtp not found")
        subprocess.run([
            calibre_smtp, "--attachment", str(out),
            "--relay", settings.SMTP_HOST, "--port", settings.SMTP_PORT,
            "--username", settings.SMTP_USER, "--password", settings.SMTP_PASS,
            "--encryption-method", "TLS", "--subject", title,
            settings.SMTP_USER, settings.KINDLE_EMAIL,
            "Today's myFT edition, delivered by ft-to-kindle.",
        ], check=True, env=calibre_env())
        return settings.KINDLE_EMAIL
    raise stk.NotRegistered("Send to Kindle is not set up - run `ft2k setup`")


def run(force: bool = False, keep: Path | None = None, no_send: bool = False) -> int:
    """Deliver today's edition. Returns a process exit code."""
    config.ensure_dirs()
    settings = config.Settings.load()
    if not settings.MYFT_RSS_URL:
        log("not configured - run `ft2k setup`")
        return 2
    today = f"{dt.date.today():%Y-%m-%d}"
    if not force and already_sent_today(today):
        log("already sent today, skipping")
        return 0

    if not wait_for_network():
        log("no network - giving up this attempt")
        return 1

    cookie_file = cookies.refresh(settings, log=log)

    title = f"FT myFT {today}"
    tmpdir = Path(tempfile.mkdtemp(prefix="ft2k-"))
    out = tmpdir / f"{title}.epub"
    try:
        log("fetching myFT...")
        build_epub(settings, out, cookie_file)
        size = out.stat().st_size
        log(f"built {out.name} ({size // 1024} KB)")
        if size < 60_000:
            log("WARNING: the edition is suspiciously small - articles may have "
                "been blocked (403) or your ft.com login may have expired")
        if keep:
            shutil.copy2(out, keep)
            log(f"saved a copy to {keep}")
        if no_send:
            return 0
        log("sending to kindle...")
        target = send_epub(settings, out, title)
        log(f"sent {out.name} to {target}")
        mark_sent(today)
        log("done")
        return 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

"""ft.com login cookies: read from a local browser, or from an exported file.

FT's login page has a CAPTCHA, so the tool never logs in itself - it reuses
the session of a browser the user is already logged in to. Cookies are
written to ``COOKIE_FILE`` (Netscape format) which the per-article fetch
helper then reads and updates.
"""
from __future__ import annotations

import http.cookiejar
import os
import time
from dataclasses import dataclass
from pathlib import Path

from . import config

# Present only when logged in to ft.com (session cookie name as of 2026).
LOGIN_COOKIE_NAMES = ("FTSession_s", "FTSession")

BROWSERS = ("chrome", "chromium", "brave", "edge", "firefox", "safari", "opera", "vivaldi", "arc")


@dataclass
class CookieResult:
    browser: str
    jar: http.cookiejar.CookieJar
    logged_in: bool

    def __len__(self) -> int:
        return len(self.jar)


def _browser_fn(name: str):
    import browser_cookie3  # imported lazily: pulls in crypto libs

    return getattr(browser_cookie3, name, None)


# Chromium-family browsers keep one Cookies DB per profile; browser_cookie3
# only reads "Default", so we enumerate profiles ourselves.
_CHROMIUM_DIRS = {
    "chrome": {"Linux": "~/.config/google-chrome", "Darwin": "~/Library/Application Support/Google/Chrome"},
    "chromium": {"Linux": "~/.config/chromium", "Darwin": "~/Library/Application Support/Chromium"},
    "brave": {"Linux": "~/.config/BraveSoftware/Brave-Browser",
              "Darwin": "~/Library/Application Support/BraveSoftware/Brave-Browser"},
    "edge": {"Linux": "~/.config/microsoft-edge", "Darwin": "~/Library/Application Support/Microsoft Edge"},
    "vivaldi": {"Linux": "~/.config/vivaldi", "Darwin": "~/Library/Application Support/Vivaldi"},
    "arc": {"Darwin": "~/Library/Application Support/Arc/User Data"},
}


def _chromium_profiles(name: str) -> list[tuple[str, Path]]:
    """(profile label, Cookies file) for every profile of a Chromium browser."""
    import json
    import platform

    base = _CHROMIUM_DIRS.get(name, {}).get(platform.system())
    if not base:
        return []
    root = Path(base).expanduser()
    if not root.exists():
        return []
    labels: dict[str, str] = {}
    try:
        info = json.loads((root / "Local State").read_text())["profile"]["info_cache"]
        labels = {k: v.get("name", k) for k, v in info.items()}
    except Exception:  # noqa: BLE001
        pass
    out = []
    for d in sorted(root.iterdir()):
        if d.name == "Default" or d.name.startswith("Profile "):
            for cand in (d / "Cookies", d / "Network" / "Cookies"):
                if cand.exists():
                    out.append((labels.get(d.name, d.name), cand))
                    break
    return out


def _read_jar(name: str, cookie_file: Path | None = None):
    fn = _browser_fn(name)
    if fn is None:
        return None
    try:
        return fn(cookie_file=str(cookie_file), domain_name="ft.com") if cookie_file \
            else fn(domain_name="ft.com")
    except Exception:  # noqa: BLE001
        return None


def _logged_in(jar) -> bool:
    names = {c.name for c in jar}
    return any(n in names for n in LOGIN_COOKIE_NAMES)


def read_browser(name: str) -> CookieResult | None:
    """Return ft.com cookies from one browser (any profile), or None.

    ``name`` may be "chrome" or "chrome:Work" to pin a profile.
    """
    base, _, profile = name.partition(":")
    if base in _CHROMIUM_DIRS:
        profiles = _chromium_profiles(base)
        if profile:
            profiles = [p for p in profiles if p[0] == profile]
        fallback = None
        for label, path in profiles:
            jar = _read_jar(base, path)
            if not jar or not len(jar):
                continue
            res = CookieResult(f"{base}:{label}", jar, _logged_in(jar))
            if res.logged_in:
                return res
            fallback = fallback or res
        if fallback or profiles:
            return fallback
    jar = _read_jar(base)
    if not jar or not len(jar):
        return None
    return CookieResult(base, jar, _logged_in(jar))


def find_logged_in(preferred: str = "auto") -> CookieResult | None:
    """Find a browser that is logged in to ft.com.

    ``preferred`` is a browser name or "auto". Returns the first logged-in
    match; falls back to any browser with ft.com cookies at all (the caller
    can inspect ``.logged_in``).
    """
    order = BROWSERS if preferred == "auto" else (preferred,)
    fallback = None
    for name in order:
        res = read_browser(name)
        if res is None:
            continue
        if res.logged_in:
            return res
        fallback = fallback or res
    # A pinned "browser:profile" that no longer matches - look everywhere.
    if fallback is None and preferred != "auto" and ":" in preferred:
        return find_logged_in("auto")
    return fallback


def export_to_file(jar: http.cookiejar.CookieJar, path: Path = config.COOKIE_FILE) -> Path:
    mcj = http.cookiejar.MozillaCookieJar()
    for c in jar:
        mcj.set_cookie(c)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    mcj.save(str(tmp), ignore_discard=True, ignore_expires=True)
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    return path


def file_is_logged_in(path: Path = config.COOKIE_FILE) -> bool:
    if not path.exists():
        return False
    cj = http.cookiejar.MozillaCookieJar()
    try:
        cj.load(str(path), ignore_discard=True, ignore_expires=True)
    except Exception:
        return False
    now = time.time()
    for c in cj:
        if c.name in LOGIN_COOKIE_NAMES and (c.expires is None or c.expires > now):
            return True
    return False


def refresh(settings: config.Settings, log=print) -> Path | None:
    """Make COOKIE_FILE hold a current ft.com login, per the user's settings.

    Returns the cookie file path, or None when no login could be found
    (the run continues - premium articles then arrive as teasers).
    """
    if settings.FT_COOKIE_SOURCE == "browser":
        res = find_logged_in(settings.FT_COOKIE_BROWSER)
        if res and res.logged_in:
            export_to_file(res.jar)
            log(f"ft.com login: read {len(res)} cookies from {res.browser}")
            return config.COOKIE_FILE
        if file_is_logged_in():
            log("ft.com login: browser not logged in; using previous cookies")
            return config.COOKIE_FILE
        log("WARNING: no ft.com login found in any browser - articles will be teasers. "
            "Log in to ft.com in your browser, or run `ft2k setup` again.")
        return config.COOKIE_FILE if config.COOKIE_FILE.exists() else None
    # source == file
    if file_is_logged_in():
        return config.COOKIE_FILE
    log(f"WARNING: {config.COOKIE_FILE} missing or expired - re-export it from your browser.")
    return config.COOKIE_FILE if config.COOKIE_FILE.exists() else None

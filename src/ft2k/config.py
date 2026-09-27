"""Where ft-to-kindle keeps its files, and the user's settings.

Everything private lives under ``~/.config/ft-to-kindle/`` (mode 0600);
run state (log, once-a-day stamp) under ``~/.local/state/ft-to-kindle/``.
The settings file is plain ``KEY=value`` so it stays readable and
editable by hand and by the previous shell-based version of this tool.
"""
from __future__ import annotations

import os
import platform
import shlex
from dataclasses import dataclass, field, fields
from pathlib import Path

APP = "ft-to-kindle"
IS_MAC = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"

CONFIG_DIR = Path(os.environ.get("FT2K_CONFIG_DIR", Path.home() / ".config" / APP))
STATE_DIR = Path(os.environ.get("FT2K_STATE_DIR", Path.home() / ".local" / "state" / APP))

SETTINGS_FILE = CONFIG_DIR / "env"
COOKIE_FILE = CONFIG_DIR / "ft-cookies.txt"
STK_CREDS_FILE = CONFIG_DIR / "stk-client.json"
STK_OAUTH_STATE_FILE = CONFIG_DIR / "stk-oauth-state.json"
STAMP_FILE = STATE_DIR / "last-sent"
LOG_FILE = (Path.home() / "Library" / "Logs" / f"{APP}.log") if IS_MAC else (STATE_DIR / f"{APP}.log")

# Hourly delivery attempts; the first that succeeds wins (stamp file).
SCHEDULE_HOURS = list(range(7, 13))


@dataclass
class Settings:
    """User settings. Field names double as the keys in the settings file."""

    MYFT_RSS_URL: str = ""
    KINDLE_DEVICE_SERIAL: str = ""
    # "browser" = read ft.com cookies from a local browser on each run;
    # "file" = use the exported Netscape cookies.txt at COOKIE_FILE.
    FT_COOKIE_SOURCE: str = "browser"
    # Which browser to read from when FT_COOKIE_SOURCE=browser ("auto" tries
    # them all and picks the one that is logged in to ft.com).
    FT_COOKIE_BROWSER: str = "auto"
    # Interpreter used for the per-article fetch (must be OpenSSL 3.x).
    # Empty = the python running ft2k.
    FT_FETCH_PYTHON: str = ""
    # SMTP fallback, only used when Send to Kindle isn't registered.
    SMTP_USER: str = ""
    SMTP_PASS: str = ""
    KINDLE_EMAIL: str = ""
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: str = "587"
    _extra: dict[str, str] = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, path: Path = SETTINGS_FILE) -> "Settings":
        s = cls()
        if not path.exists():
            return s
        known = {f.name for f in fields(cls) if not f.name.startswith("_")}
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if val and val[0] in "\"'":
                try:
                    val = shlex.split(val)[0]
                except ValueError:
                    val = val.strip("\"'")
            val = os.path.expandvars(val)
            if key in known:
                setattr(s, key, val)
            else:
                s._extra[key] = val
        return s

    def save(self, path: Path = SETTINGS_FILE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"# {APP} settings - edit with `ft2k config` or by hand.",
            "# Every value here is private to you; keep this file at mode 0600.",
            "",
        ]
        for f in fields(self):
            if f.name.startswith("_"):
                continue
            lines.append(f"{f.name}={shlex.quote(getattr(self, f.name))}")
        for k, v in self._extra.items():
            lines.append(f"{k}={shlex.quote(v)}")
        tmp = path.with_suffix(".tmp")
        tmp.write_text("\n".join(lines) + "\n")
        os.chmod(tmp, 0o600)
        tmp.replace(path)

    @property
    def uses_smtp_fallback(self) -> bool:
        return bool(self.SMTP_USER and self.SMTP_PASS and self.KINDLE_EMAIL)


def ensure_dirs() -> None:
    for d in (CONFIG_DIR, STATE_DIR, LOG_FILE.parent):
        d.mkdir(parents=True, exist_ok=True)
    os.chmod(CONFIG_DIR, 0o700)

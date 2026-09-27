"""Amazon Send to Kindle over HTTPS, via the stkclient library.

Why not SMTP: some corporate/managed networks block outbound SMTP. Why the
serial patch: stock stkclient registers one shared device serial for every
install worldwide, so any other user's registration invalidates yours
(403 "Failed to validate DeviceInfoToken"; upstream PR #199 closed
unmerged). We register a serial derived from user@host instead.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import platform
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import config


class NotRegistered(Exception):
    pass


@dataclass
class Device:
    serial: str
    name: str


def is_registered() -> bool:
    return config.STK_CREDS_FILE.exists()


def _client():
    import stkclient

    if not is_registered():
        raise NotRegistered(f"{config.STK_CREDS_FILE} not found - run `ft2k setup`")
    with open(config.STK_CREDS_FILE) as f:
        return stkclient.Client.load(f)


def login_url() -> str:
    """Start the OAuth flow; returns the Amazon sign-in URL to open."""
    import stkclient

    auth = stkclient.OAuth2()
    url = auth.get_signin_url()
    # create_client verifies the code against the same PKCE verifier, so it
    # must survive between login_url() and register().
    config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config.STK_OAUTH_STATE_FILE.write_text(json.dumps({"verifier": auth._verifier}))
    os.chmod(config.STK_OAUTH_STATE_FILE, 0o600)
    return url


def _unique_serial() -> str:
    seed = f"ft-to-kindle/{getpass.getuser()}@{platform.node()}"
    return hashlib.sha256(seed.encode()).hexdigest().upper()[:32]


def _register_device_with_token_unique(access_token):
    # Adapted from stkclient 0.1.1 api.register_device_with_token
    # (c) Max Johnson, MIT license - only the serial and model differ.
    from stkclient import api

    q = {
        "device_type": "A1K6D1WRW0MALS",
        "device_serial_number": _unique_serial(),
        "pid": "D21NN3GG",
        "auth_token": access_token,
        "auth_token_type": "AccessToken",
        "software_version": "253",
        "os_version": "MacOSX_10.14.6_x64",
        "device_model": "ft-to-kindle",
    }
    body = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<request><parameters>"
        f"<deviceType>{q['device_type']}</deviceType>"
        f"<deviceSerialNumber>{q['device_serial_number']}</deviceSerialNumber>"
        f"<pid>{q['pid']}</pid>"
        f"<authToken>{q['auth_token']}</authToken>"
        f"<authTokenType>{q['auth_token_type']}</authTokenType>"
        f"<softwareVersion>{q['software_version']}</softwareVersion>"
        f"<os_version>{q['os_version']}</os_version>"
        f"<device_model>{q['device_model']}</device_model>"
        "</parameters></request>"
    )
    req = urllib.request.Request(
        url="https://firs-ta-g7g.amazon.com/FirsProxy/registerDeviceWithToken",
        data=body.encode(),
        headers={
            "Content-Type": "text/xml",
            "Expect": "",
            "Accept-Language": "en-US,*",
            "User-Agent": "Mozilla/5.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as r:
            return api.DeviceInfo.from_xml(r.read())
    except urllib.error.HTTPError as e:
        raise api.APIError(str(e), api._text(e)) from e


def register(redirect_url: str) -> list[Device]:
    """Finish the OAuth flow with the URL Amazon redirected to; save creds."""
    import stkclient
    from stkclient import api

    api.register_device_with_token = _register_device_with_token_unique
    auth = stkclient.OAuth2()
    if config.STK_OAUTH_STATE_FILE.exists():
        auth._verifier = json.loads(config.STK_OAUTH_STATE_FILE.read_text())["verifier"]
    client = auth.create_client(redirect_url.strip().strip("'\""))
    config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.STK_CREDS_FILE, "w") as f:
        client.dump(f)
    os.chmod(config.STK_CREDS_FILE, 0o600)
    if config.STK_OAUTH_STATE_FILE.exists():
        config.STK_OAUTH_STATE_FILE.unlink()
    return devices()


def devices() -> list[Device]:
    return [Device(d.device_serial_number, d.device_name) for d in _client().get_owned_devices()]


def send(path: Path, title: str | None = None, serial: str | None = None,
         author: str = "Financial Times") -> list[Device]:
    client = _client()
    devs = [Device(d.device_serial_number, d.device_name) for d in client.get_owned_devices()]
    if serial:
        devs = [d for d in devs if d.serial == serial]
        if not devs:
            raise RuntimeError(f"no Kindle with serial {serial} on this Amazon account "
                               "(run `ft2k devices`)")
    if not devs:
        raise RuntimeError("no Kindle devices on this Amazon account")
    client.send_file(path, [d.serial for d in devs],
                     author=author,
                     title=title or path.stem,
                     format=path.suffix.lstrip(".") or "epub")
    return devs

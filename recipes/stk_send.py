#!/usr/bin/env python3
"""Send a file to the Kindle via Amazon's Send to Kindle service (HTTPS).

Replaces the calibre-smtp email path (outbound SMTP is blocked on some
networks). Run with the venv python: ~/.config/ft-to-kindle/stk-venv/bin/python

One-time setup:
    stk_send.py login-url          # prints an Amazon sign-in URL; open it,
                                   # sign in, copy the final redirect URL
    stk_send.py register '<redirect-url>'   # saves credentials
    stk_send.py devices            # verify your Kindle is listed

Daily use (run-local.sh):
    stk_send.py send book.epub --title 'FT myFT 2026-08-31'
"""
import argparse
import os
import sys
from pathlib import Path

import stkclient

CRED_FILE = os.path.expanduser('~/.config/ft-to-kindle/stk-client.json')
STATE_FILE = os.path.expanduser('~/.config/ft-to-kindle/stk-oauth-state.json')


def load_client():
    if not os.path.exists(CRED_FILE):
        sys.exit(f'{CRED_FILE} not found - run the login-url/register steps first')
    with open(CRED_FILE) as f:
        return stkclient.Client.load(f)


def cmd_login_url(_args):
    import json
    auth = stkclient.OAuth2()
    print(auth.get_signin_url())
    # create_client verifies the code against the same PKCE verifier, so it
    # must be persisted between the login-url and register invocations.
    with open(STATE_FILE, 'w') as f:
        json.dump({"verifier": auth._verifier}, f)
    os.chmod(STATE_FILE, 0o600)
    print('\nOpen the URL, sign in to Amazon, then run:\n'
          "  stk_send.py register '<URL of the page you land on>'", file=sys.stderr)


def _unique_serial():
    # stkclient 0.1.1 hardcodes one device_serial_number for every install
    # worldwide; any other user's registration rebinds it and Amazon then
    # rejects ours with 403 "Failed to validate DeviceInfoToken" (upstream
    # PR #199, closed unmerged). Register under a serial unique to this
    # user+machine instead - stable, so re-registering only rotates our own
    # key binding.
    import getpass
    import hashlib
    import platform
    seed = f'ft-to-kindle/{getpass.getuser()}@{platform.node()}'
    return hashlib.sha256(seed.encode()).hexdigest().upper()[:32]


def _register_device_with_token_unique(access_token):
    # Adapted from stkclient 0.1.1 api.register_device_with_token
    # (c) Max Johnson, MIT license - only the serial and model differ.
    from stkclient import api

    q = {
        'device_type': 'A1K6D1WRW0MALS',
        'device_serial_number': _unique_serial(),
        'pid': 'D21NN3GG',
        'auth_token': access_token,
        'auth_token_type': 'AccessToken',
        'software_version': '253',
        'os_version': 'MacOSX_10.14.6_x64',
        'device_model': 'ft-to-kindle',
    }
    body = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        '<request><parameters>'
        f'<deviceType>{q["device_type"]}</deviceType>'
        f'<deviceSerialNumber>{q["device_serial_number"]}</deviceSerialNumber>'
        f'<pid>{q["pid"]}</pid>'
        f'<authToken>{q["auth_token"]}</authToken>'
        f'<authTokenType>{q["auth_token_type"]}</authTokenType>'
        f'<softwareVersion>{q["software_version"]}</softwareVersion>'
        f'<os_version>{q["os_version"]}</os_version>'
        f'<device_model>{q["device_model"]}</device_model>'
        '</parameters></request>'
    )
    import urllib.error
    import urllib.request
    req = urllib.request.Request(
        url='https://firs-ta-g7g.amazon.com/FirsProxy/registerDeviceWithToken',
        data=body.encode(),
        headers={
            'Content-Type': 'text/xml',
            'Expect': '',
            'Accept-Language': 'en-US,*',
            'User-Agent': 'Mozilla/5.0',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req) as r:
            return api.DeviceInfo.from_xml(r.read())
    except urllib.error.HTTPError as e:
        raise api.APIError(str(e), api._text(e)) from e


def cmd_register(args):
    import json

    from stkclient import api
    api.register_device_with_token = _register_device_with_token_unique
    auth = stkclient.OAuth2()
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            auth._verifier = json.load(f)['verifier']
    client = auth.create_client(args.redirect_url)
    os.makedirs(os.path.dirname(CRED_FILE), exist_ok=True)
    with open(CRED_FILE, 'w') as f:
        client.dump(f)
    os.chmod(CRED_FILE, 0o600)
    if os.path.exists(STATE_FILE):
        os.unlink(STATE_FILE)
    print(f'Registered. Credentials saved to {CRED_FILE}')
    cmd_devices(args)


def cmd_devices(_args):
    client = load_client()
    for d in client.get_owned_devices():
        print(f'{d.device_serial_number}  {d.device_name}')


def cmd_send(args):
    client = load_client()
    devices = client.get_owned_devices()
    if args.device:
        devices = [d for d in devices
                   if args.device == d.device_serial_number
                   or args.device.lower() in d.device_name.lower()]
    if not devices:
        sys.exit('no matching Kindle devices on this account')
    serials = [d.device_serial_number for d in devices]
    path = Path(args.file)
    client.send_file(path, serials,
                     author=args.author,
                     title=args.title or path.stem,
                     format=path.suffix.lstrip('.') or 'epub')
    print(f'sent {path.name} to {", ".join(d.device_name for d in devices)}')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('login-url').set_defaults(func=cmd_login_url)
    r = sub.add_parser('register')
    r.add_argument('redirect_url')
    r.set_defaults(func=cmd_register)
    sub.add_parser('devices').set_defaults(func=cmd_devices)
    s = sub.add_parser('send')
    s.add_argument('file')
    s.add_argument('--title', default=None)
    s.add_argument('--author', default='Financial Times')
    s.add_argument('--device', default=None,
                   help='substring of a device name; default: all devices')
    s.set_defaults(func=cmd_send)
    args = p.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()

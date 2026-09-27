#!/usr/bin/env python3
"""Fetch one ft.com URL and write the raw HTML to stdout.

Invoked as a subprocess by the myFT recipe (calibre's own python has an
OpenSSL that FT's bot protection 403s). Must run under an OpenSSL 3.x
python. Cookies persist across invocations via FT_COOKIE_FILE so the
session established on the first call is reused - FT blocks cookie-less
request bursts. Standalone: no imports from the ft2k package.
"""
import http.cookiejar
import os
import sys
import time
import urllib.error
import urllib.request

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) '
      'Gecko/20100101 Firefox/149.0')
HEADERS = [
    ('User-Agent', UA),
    ('Referer', 'https://www.google.com/'),
    ('Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'),
    ('Accept-Language', 'en-GB,en;q=0.9'),
    ('Sec-Fetch-Dest', 'document'),
    ('Sec-Fetch-Mode', 'navigate'),
    ('Sec-Fetch-Site', 'cross-site'),
    ('Upgrade-Insecure-Requests', '1'),
]


def fetch(url, cookie_file=None, timeout=60):
    cj = http.cookiejar.MozillaCookieJar()
    if cookie_file and os.path.exists(cookie_file):
        try:
            cj.load(cookie_file, ignore_discard=True, ignore_expires=True)
        except Exception:
            pass
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.addheaders = HEADERS

    def prime():
        try:
            opener.open('https://www.ft.com/', timeout=timeout).read()
        except Exception:
            pass

    if not len(cj):
        prime()

    # FT throttles bursts with HTTP 403: back off, re-establish the
    # session, retry a few times before giving up on this article.
    backoffs = [8, 20, 45]
    data = None
    for attempt in range(len(backoffs) + 1):
        try:
            data = opener.open(url, timeout=timeout).read()
            break
        except urllib.error.HTTPError as e:
            if e.code == 403 and attempt < len(backoffs):
                time.sleep(backoffs[attempt])
                prime()
                continue
            raise

    if cookie_file:
        try:
            cj.save(cookie_file, ignore_discard=True, ignore_expires=True)
            os.chmod(cookie_file, 0o600)
        except Exception:
            pass
    return data


def main():
    sys.stdout.buffer.write(fetch(sys.argv[1], os.environ.get('FT_COOKIE_FILE')))


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Fetch one ft.com URL and write the raw HTML to stdout.

Run with an OpenSSL 3.x python (FT's bot protection 403s older TLS stacks).
Cookies persist across invocations via FT_COOKIE_FILE so the session
established on the first call (priming the homepage) is reused — FT blocks
cookie-less request bursts.
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


def main():
    url = sys.argv[1]
    cookie_file = os.environ.get('FT_COOKIE_FILE')
    cj = http.cookiejar.MozillaCookieJar()
    if cookie_file and os.path.exists(cookie_file):
        try:
            cj.load(cookie_file, ignore_discard=True, ignore_expires=True)
        except Exception:
            pass
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj))
    opener.addheaders = HEADERS

    def prime():
        try:
            opener.open('https://www.ft.com/', timeout=60).read()
        except Exception:
            pass

    # Establish a session the first time (no cookies yet).
    if not len(cj):
        prime()

    # FT throttles bursts with HTTP 403. Back off, re-establish the session,
    # and retry a few times before giving up on this article.
    backoffs = [8, 20, 45]
    data = None
    for attempt in range(len(backoffs) + 1):
        try:
            data = opener.open(url, timeout=60).read()
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
        except Exception:
            pass

    sys.stdout.buffer.write(data)


if __name__ == '__main__':
    main()

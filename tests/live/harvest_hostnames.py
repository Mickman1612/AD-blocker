"""List the ad hostnames real pages ask for, so the hosts list can be kept up to date.

Run: python -m tests.live.harvest_hostnames [site names...]
Loads real sites with the extension in a temporary profile and prints each hostname the extension
blocked that the PC-wide list doesn't have yet. Nothing is downloaded from any list provider.
"""
import collections
import json
import pathlib
import sys
import time
import urllib.parse

from tests.harness.browser import Browser
from tests.live.site_check import SITES
from tests.support import EXTENSION, REPO

READY = "chrome.scripting.getRegisteredContentScripts().then(s => s.length > 0)"
DEFAULT_SITES = ["guardian", "cnn", "weather", "smh", "amazon", "stackoverflow", "abc-au", "twitch", "bing",
                 "duckduckgo", "pinterest", "wikipedia", "github"]
EXTRA_PAGES = {
    "youtube-watch": "https://www.youtube.com/watch?v=kJQP7kiw5Fk",
    "forbes-article": "https://www.theverge.com/",
    "reuters": "https://www.bbc.com/news",
    "nine": "https://www.9news.com.au/",
    "seven": "https://7news.com.au/",
    "imdb": "https://www.imdb.com/",
    "fandom": "https://www.fandom.com/",
    "dictionary": "https://www.merriam-webster.com/",
}


def known_hostnames():
    known = set()
    for name in ("ad-domains.txt", "pc-hostnames.txt"):
        path = REPO / "rules-src" / name
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.split("#", 1)[0].strip().lower()
                if line:
                    known.add(line)
    return known


def main():
    names = sys.argv[1:] or (DEFAULT_SITES + list(EXTRA_PAGES))
    pages = {**SITES, **EXTRA_PAGES}
    counts = collections.Counter()
    for name in names:
        with Browser(extension_path=EXTENSION) as browser:
            browser.service_worker_wait_for(READY, timeout=15)
            page = browser.new_page(offline=False)
            try:
                page.goto(pages[name], timeout=40)
            except Exception as error:
                print(f"{name}: {str(error)[:70]}", flush=True)
            time.sleep(8)
            try:
                page.eval("window.scrollTo(0, document.body.scrollHeight / 2)")
            except Exception:
                pass
            time.sleep(4)
            blocked = page.blocked_requests()
            hosts = {urllib.parse.urlsplit(url).hostname for url in blocked}
            counts.update(hosts)
            print(f"{name}: {len(blocked)} blocked requests, {len(hosts)} hostnames", flush=True)
            page.close()
    known = known_hostnames()
    fresh = sorted(host for host in counts if host and host not in known)
    print(f"\n{len(counts)} hostnames seen, {len(fresh)} not listed yet:")
    print(json.dumps(fresh, indent=0))


if __name__ == "__main__":
    main()

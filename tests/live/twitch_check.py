"""Live Twitch check: does the player still work, and do ads show?

Run: python -m tests.live.twitch_check
Uses the most-watched live channels, with and without the extension, in temporary profiles.
"""
import json
import sys
import time

from tests.harness.browser import Browser
from tests.support import EXTENSION

READY = "chrome.scripting.getRegisteredContentScripts().then(s => s.length > 0)"
WATCH_SECONDS = 45
FIND_CHANNELS = """[...new Set([...document.querySelectorAll('a[href^="/"][data-a-target="preview-card-image-link"], a[data-a-target="preview-card-image-link"]')]
    .map(a => a.getAttribute('href')))].slice(0, 5)"""
SAMPLE = """(() => {
  const v = document.querySelector('video');
  return {
    t: v ? v.currentTime : null,
    paused: v ? v.paused : null,
    muted: v ? v.muted : null,
    opacity: v ? v.style.opacity : null,
    rs: v ? v.readyState : null,
    ad: !!document.querySelector('[data-a-target="video-ad-label"],[data-a-target="video-ad-countdown"]'),
    adText: /\\b(ad|commercial break|ads?) /i.test(document.querySelector('[data-a-target="video-player"]')?.innerText || ''),
    error: !!document.querySelector('[data-a-target="player-overlay-content-gate"],[data-a-target="player-error"]'),
    title: document.title.slice(0, 40),
  };
})()"""


def find_channels():
    with Browser() as browser:
        page = browser.new_page(offline=False)
        page.goto("https://www.twitch.tv/directory/all", timeout=45)
        page.wait_for("document.querySelectorAll('a[data-a-target=\"preview-card-image-link\"]').length > 0", timeout=25)
        channels = page.eval(FIND_CHANNELS)
        page.close()
        return channels


def watch(browser, channel):
    page = browser.new_page(offline=False)
    playlists = []

    def on_request(params):
        url = params["request"]["url"]
        if ".m3u8" in url:
            playlists.append(url[:60])

    page.cdp.on("Network.requestWillBeSent", on_request, page.session_id)
    page.goto(f"https://www.twitch.tv{channel}", timeout=45)
    ad_seconds = progress = 0
    last_t = None
    error = False
    first = None
    for second in range(WATCH_SECONDS):
        time.sleep(1)
        sample = page.eval(SAMPLE)
        error = error or sample["error"]
        ad_seconds += 1 if (sample["ad"] or sample["adText"]) else 0
        if sample["t"] is not None and last_t is not None and sample["t"] > last_t + 0.2:
            progress += 1
            first = first if first is not None else second
        last_t = sample["t"]
    final = page.eval(SAMPLE)
    page.close()
    return {"title": final["title"], "secondsAdShown": ad_seconds, "secondsProgressing": progress,
            "firstProgressAt": first, "error": error, "paused": final["paused"], "readyState": final["rs"],
            "muted": final["muted"], "playlists": len(playlists)}


def main():
    channels = sys.argv[1:] or find_channels()[:3]
    print("channels:", channels)
    for channel in channels:
        with Browser() as browser:
            print(channel, "control", json.dumps(watch(browser, channel)), flush=True)
        with Browser(extension_path=EXTENSION) as browser:
            browser.service_worker_wait_for(READY, timeout=15)
            print(channel, "blocked", json.dumps(watch(browser, channel)), flush=True)


if __name__ == "__main__":
    main()

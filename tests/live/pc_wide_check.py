"""Simulate the hosts file on real sites: block exactly its hostnames, with no extension loaded.

Run: python -m tests.live.pc_wide_check [site names...]
Uses temporary profiles and doesn't touch the real hosts file. It answers two questions:
how much do the hostnames remove by themselves, and do they break anything?
"""
import json
import sys
import time

from tests.harness.browser import Browser
from tests.live.site_check import MEASURE, SETTLE_SECONDS, SITES
from tests.support import REPO

DEFAULT_SITES = ["guardian", "cnn", "weather", "smh", "amazon", "stackoverflow", "github", "wikipedia",
                 "abc-au", "twitch"]
YOUTUBE_VIDEOS = ["kJQP7kiw5Fk", "OPf0YbXqDm0"]
YOUTUBE_SAMPLE = """(() => {
  const p = document.querySelector('.html5-video-player');
  const v = document.querySelector('video');
  return {ad: !!p?.classList.contains('ad-showing'), t: v ? v.currentTime : 0,
          prompt: !!document.querySelector('ytd-enforcement-message-view-model'),
          error: !!document.querySelector('.ytp-error')};
})()"""


def host_patterns():
    names = set()
    for line in (REPO / "pc-wide" / "hosts-block.txt").read_text(encoding="ascii").splitlines():
        if line.startswith("0.0.0.0 "):
            names.update(line.split()[1:])
    return [f"*://{name}/*" for name in sorted(names)]


def open_page(browser, patterns):
    page = browser.new_page(offline=False)
    if patterns:
        page._send("Network.setBlockedURLs", {"urls": patterns})
    return page


def visit(browser, url, patterns):
    page = open_page(browser, patterns)
    errors = []
    blocked = []
    page.cdp.on("Runtime.exceptionThrown", lambda _: errors.append(1), page.session_id)
    page.cdp.on("Network.loadingFailed",
                lambda params: blocked.append(1) if params.get("blockedReason") else None, page.session_id)
    started = time.time()
    load_problem = None
    try:
        page.goto(url, timeout=45)
    except Exception as error:
        load_problem = str(error)[:80]
    load_seconds = round(time.time() - started, 1)
    time.sleep(SETTLE_SECONDS)
    page.eval("window.scrollTo(0, document.body.scrollHeight / 2)")
    time.sleep(2)
    result = page.eval(MEASURE)
    result["blocked"] = len(blocked)
    result["jsErrors"] = len(errors)
    result["loadSeconds"] = load_seconds
    if load_problem:
        result["loadProblem"] = load_problem
    page.close()
    return result


def watch_youtube(browser, video, patterns):
    page = open_page(browser, patterns)
    page._send("Page.navigate", {"url": f"https://www.youtube.com/watch?v={video}"})
    ad = prompt = error = False
    started = time.time()
    last = {"t": 0}
    while time.time() - started < 30:
        time.sleep(0.5)
        try:
            last = page.eval(YOUTUBE_SAMPLE)
        except Exception:
            continue
        ad = ad or last["ad"]
        prompt = prompt or last["prompt"]
        error = error or last["error"]
    blocked = len(page.blocked_requests())
    page.close()
    return {"adPlayed": ad, "warningPrompt": prompt, "playerError": error,
            "secondsPlayed": round(last["t"], 1), "blocked": blocked}


def main():
    patterns = host_patterns()
    print(f"Simulating {len(patterns)} blocked hostnames\n")
    rows = {}
    for name in sys.argv[1:] or DEFAULT_SITES:
        with Browser() as browser:
            control = visit(browser, SITES[name], None)
        with Browser() as browser:
            simulated = visit(browser, SITES[name], patterns)
        rows[name] = (control, simulated)
        print(name, json.dumps({"control": control, "simulated": simulated})[:300], flush=True)

    print("\n--- Summary: normal -> hosts list only ---")
    print(f"{'site':14}{'ad frames':12}{'ad slots':12}{'ad labels':12}{'text':16}{'links':13}{'js errors':11}{'blocked':8}")
    for name, (c, s) in rows.items():
        def pair(key):
            return f"{c.get(key, '?')}->{s.get(key, '?')}"
        print(f"{name:14}{pair('adSizedFrames'):12}{pair('adSlots'):12}{pair('adLabels'):12}"
              f"{pair('textLength'):16}{pair('links'):13}{pair('jsErrors'):11}{s.get('blocked', '?'):<8}")

    print("\n--- YouTube with the hosts list only, no extension ---")
    for video in YOUTUBE_VIDEOS:
        with Browser() as browser:
            print(video, json.dumps(watch_youtube(browser, video, patterns)), flush=True)


if __name__ == "__main__":
    main()

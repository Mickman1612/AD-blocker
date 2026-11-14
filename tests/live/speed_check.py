"""How fast do pages and videos open in each setup? Temporary profiles; nothing is installed.

Run: python -m tests.live.speed_check
Setups:
  nothing     no blocking at all
  hosts-only  the ad server list alone, simulated in the browser
  app         the filtering app with its page scripts (a temporary copy)
  app-bare    the filtering app without page scripts (a temporary copy)
  in-browser  the browser extension, which blocks inside the browser the way Brave does
The app copies use temporary certificates, so those browsers skip certificate checks.
"""
import json
import statistics
import sys
import time

from tests.harness.browser import Browser, EDGE
from tests.live.pc_wide_check import host_patterns
from tests.live.proxy_check import RunningApp
from tests.support import EXTENSION

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PAGES = {
    "youtube-home": "https://www.youtube.com/",
    "youtube-watch": "https://www.youtube.com/watch?v=OPf0YbXqDm0",
    "cnn": "https://edition.cnn.com/",
    "guardian": "https://www.theguardian.com/international",
    "google": "https://www.google.com/search?q=running+shoes",
}
VIDEOS = ["kJQP7kiw5Fk", "JGwWNGJdvx8", "RgKAFK5djSk", "OPf0YbXqDm0", "9bZkp7q19f0"]
READY = "chrome.scripting.getRegisteredContentScripts().then(s => s.length > 0)"
COLLECT = """
window.__longTasks = 0; window.__longTaskMs = 0;
try {
  new PerformanceObserver((list) => { for (const e of list.getEntries()) { window.__longTasks++; window.__longTaskMs += e.duration; } })
    .observe({type: 'longtask', buffered: true});
} catch (e) {}
"""
TIMING = """(() => {
  const n = performance.getEntriesByType('navigation')[0] || {};
  const fcp = performance.getEntriesByType('paint').find(p => p.name === 'first-contentful-paint');
  return {firstByte: Math.round(n.responseStart || 0), firstPaint: fcp ? Math.round(fcp.startTime) : null,
          domReady: Math.round(n.domContentLoadedEventEnd || 0), loaded: Math.round(n.loadEventEnd || 0),
          longTaskMs: Math.round(window.__longTaskMs || 0)};
})()"""
PLAYER = """(() => { const p = document.querySelector('.html5-video-player'); const v = document.querySelector('video');
  return {ad: !!p?.classList.contains('ad-showing'), t: v ? v.currentTime : 0}; })()"""


def open_page(browser, blocked):
    page = browser.new_page(offline=False)
    if blocked:
        page._send("Network.setBlockedURLs", {"urls": blocked})
    return page


def measure_page(browser, url, blocked):
    page = open_page(browser, blocked)
    page.add_init_script(COLLECT)
    page._send("Performance.enable")
    try:
        page.goto(url, timeout=60)
    except Exception:
        pass
    time.sleep(8)
    timing = page.eval(TIMING)
    metrics = {m["name"]: m["value"] for m in page._send("Performance.getMetrics")["metrics"]}
    timing["busyMs"] = round(1000 * (metrics.get("ScriptDuration", 0) + metrics.get("LayoutDuration", 0)
                                     + metrics.get("RecalcStyleDuration", 0)))
    page.close()
    return timing


def measure_video(browser, video, blocked):
    page = open_page(browser, blocked)
    started = time.time()
    page._send("Page.navigate", {"url": f"https://www.youtube.com/watch?v={video}"})
    while time.time() - started < 45:
        try:
            state = page.eval(PLAYER)
        except Exception:
            time.sleep(0.2)
            continue
        if state["t"] > 0.3 and not state["ad"]:
            page.close()
            return round(time.time() - started - state["t"], 1)
        time.sleep(0.2)
    page.close()
    return None


def main():
    blocked = host_patterns()
    results = {}
    with RunningApp() as full, RunningApp() as bare:
        bare.server.config.page_snippet = None
        configs = {
            "nothing": dict(options={}, blocked=None),
            "hosts-only": dict(options={}, blocked=blocked),
            "app": dict(options=dict(extra_args=full.args), blocked=None),
            "app-bare": dict(options=dict(extra_args=bare.args), blocked=None),
            "in-browser": dict(options=dict(extension_path=EXTENSION), blocked=None),
        }
        chosen = [name for name in sys.argv[1:] if name in configs]
        if chosen:
            configs = {name: configs[name] for name in chosen}
        for name, setup in configs.items():
            with Browser(**setup["options"]) as browser:
                if "extension_path" in setup["options"]:
                    browser.service_worker_wait_for(READY, timeout=15)
                for page_name, url in PAGES.items():
                    for kind in ("cold", "warm"):
                        timing = measure_page(browser, url, setup["blocked"])
                        results[(name, page_name, kind)] = timing
                        print(name, page_name, kind, json.dumps(timing), flush=True)
            for browser_name, executable in (("edge", EDGE), ("chrome", CHROME)):
                if "extension_path" in setup["options"] and browser_name == "chrome":
                    continue  # Chrome won't load an extension for automated tests.
                for video in VIDEOS:
                    with Browser(executable=executable, **setup["options"]) as browser:
                        if "extension_path" in setup["options"]:
                            browser.service_worker_wait_for(READY, timeout=15)
                        start = measure_video(browser, video, setup["blocked"])
                    results.setdefault((name, "video", browser_name), []).append(start)
                    print(name, "video", browser_name, video, start, flush=True)
        app_errors = full.errors + bare.errors

    names = list(configs)
    print("\n--- Pages, in milliseconds: first paint / fully loaded / browser busy ---")
    print(f"{'page':22}" + "".join(f"{n:>24}" for n in names))
    for page_name in PAGES:
        for kind in ("cold", "warm"):
            row = f"{page_name + ' ' + kind:22}"
            for name in names:
                t = results[(name, page_name, kind)]
                row += f"{str(t['firstPaint']) + ' / ' + str(t['loaded']) + ' / ' + str(t['busyMs']):>24}"
            print(row)
    print("\n--- Videos: seconds until the video itself plays (each of 3 videos) ---")
    for browser_name in ("edge", "chrome"):
        row = f"{browser_name:22}"
        for name in names:
            starts = results.get((name, "video", browser_name))
            row += f"{('-' if starts is None else ', '.join(str(s) for s in starts)):>24}"
        print(row)
    print("\nApp errors:", app_errors[:5] or "none")


if __name__ == "__main__":
    main()

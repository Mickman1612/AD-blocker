"""Live YouTube check: the same videos with and without the extension.

Run: python -m tests.live.youtube_compare [video ids...]
Uses temporary profiles. "No ads" only counts if the control run shows ads for that video.
"""
import json
import sys
import time

from tests.harness.browser import Browser
from tests.support import EXTENSION

DEFAULT_VIDEOS = ["kJQP7kiw5Fk", "JGwWNGJdvx8", "RgKAFK5djSk", "OPf0YbXqDm0", "9bZkp7q19f0", "fRh_vgS2dFE"]
WATCH_SECONDS = 40

SAMPLE = """(() => {
  const player = document.querySelector('.html5-video-player');
  const video = document.querySelector('video');
  const response = window.ytInitialPlayerResponse;
  return {
    adShowing: !!player?.classList.contains('ad-showing'),
    adUi: !!document.querySelector('.ytp-ad-player-overlay, .ytp-ad-player-overlay-layout, .ytp-skip-ad-button, .ytp-ad-preview-container'),
    time: video ? video.currentTime : null,
    duration: video ? video.duration : null,
    paused: video ? video.paused : null,
    adPlacements: response?.adPlacements?.length ?? 0,
    playerAds: response?.playerAds?.length ?? 0,
    adSlots: response?.adSlots?.length ?? 0,
    playability: response?.playabilityStatus?.status ?? null,
    enforcement: !!document.querySelector('ytd-enforcement-message-view-model'),
    title: document.title.slice(0, 40),
  };
})()"""

AD_REQUEST_MARKERS = ("/api/stats/ads", "/pagead/", "doubleclick.net/ytcs", "ad_break")


def watch(browser, video_id):
    page = browser.new_page(offline=False)
    page.goto(f"https://www.youtube.com/watch?v={video_id}", timeout=60)
    first = page.eval(SAMPLE)
    ad_seen = adui_seen = enforcement = False
    furthest = 0.0
    start_delay = None
    last = first
    started = time.time()
    for _ in range(WATCH_SECONDS):
        time.sleep(1)
        last = page.eval(SAMPLE)
        ad_seen = ad_seen or last["adShowing"]
        adui_seen = adui_seen or last["adUi"]
        enforcement = enforcement or last["enforcement"]
        if not last["adShowing"] and last["time"]:
            furthest = max(furthest, last["time"])
            if start_delay is None and last["time"] > 0.2:
                start_delay = round(time.time() - started - last["time"], 1)
    urls = page.requests()
    blocked = page.blocked_requests()
    page.close()
    return {
        "title": first["title"],
        "playability": first["playability"],
        "adDataInPage": first["adPlacements"] + first["playerAds"] + first["adSlots"],
        "adShowing": ad_seen,
        "adUi": adui_seen,
        "enforcementPrompt": enforcement,
        "videoSecondsPlayed": round(furthest, 1),
        "secondsBeforeVideoStarted": start_delay,
        "stillPlaying": last["paused"] is False,
        "adRequestsSent": sum(any(m in u for m in AD_REQUEST_MARKERS) for u in urls) - len(
            [u for u in blocked if any(m in u for m in AD_REQUEST_MARKERS)]),
        "blockedRequests": len(blocked),
    }


def main():
    videos = sys.argv[1:] or DEFAULT_VIDEOS
    results = {}
    print("--- Control: no extension ---")
    with Browser() as browser:
        for video in videos:
            results[video] = {"control": watch(browser, video)}
            print(video, json.dumps(results[video]["control"]))
    print("--- With the extension ---")
    with Browser(extension_path=EXTENSION) as browser:
        browser.service_worker_wait_for(
            "chrome.scripting.getRegisteredContentScripts().then(s => s.length > 0)", timeout=15)
        for video in videos:
            results[video]["blocked"] = watch(browser, video)
            print(video, json.dumps(results[video]["blocked"]))

    print("\n--- Summary ---")
    print(f"{'video':14}{'control ad?':13}{'with ext ad?':14}{'played':9}{'prompt':8}")
    failures = 0
    control_ads = 0
    for video, r in results.items():
        control_ad = r["control"]["adShowing"] or r["control"]["adUi"]
        blocked_ad = r["blocked"]["adShowing"] or r["blocked"]["adUi"]
        control_ads += control_ad
        failures += blocked_ad or r["blocked"]["enforcementPrompt"] or r["blocked"]["videoSecondsPlayed"] < 5
        print(f"{video:14}{str(control_ad):13}{str(blocked_ad):14}"
              f"{r['blocked']['videoSecondsPlayed']:<9}{str(r['blocked']['secondsBeforeVideoStarted']):13}"
              f"{str(r['control']['secondsBeforeVideoStarted']):15}{str(r['blocked']['enforcementPrompt']):8}")
    print(f"Control runs that showed an ad: {control_ads}/{len(results)}")
    print(f"Runs with a problem while blocking: {failures}/{len(results)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

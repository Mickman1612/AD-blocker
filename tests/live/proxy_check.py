"""Live check of the filtering app, with no extension and nothing installed on the system.

Run: python -m tests.live.proxy_check [youtube|sites|twitch]
The app runs from temporary certificates on a spare port and a temporary browser profile is pointed
at it. That browser skips certificate checks because the certificate isn't installed in Windows, so
this doesn't test Windows trusting the certificate. Everything else is the real path.
"""
import asyncio
import json
import pathlib
import sys
import tempfile
import threading
import time

from proxy import app, certs
from proxy.server import ProxyServer
from tests.harness.browser import Browser
from tests.live.site_check import MEASURE, SITES
from tests.live.twitch_check import find_channels, watch as watch_twitch
from tests.live.youtube_compare import watch as watch_youtube

YOUTUBE_VIDEOS = ["kJQP7kiw5Fk", "OPf0YbXqDm0", "9bZkp7q19f0", "JGwWNGJdvx8"]
SITE_NAMES = ["guardian", "cnn", "smh", "weather", "duckduckgo", "bing", "wikipedia", "github", "abc-au", "twitch", "pinterest"]
SEARCH_LINK = 'ytd-video-renderer a[href*="/watch"]'


class RunningApp:
    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        directory = pathlib.Path(self.tmp.name)
        certs.create_certificates(directory, app.certificate_names())
        self.loop = asyncio.new_event_loop()
        ready = threading.Event()
        self.errors = []

        def report(loop, context):
            self.errors.append(str(context.get("exception") or context.get("message"))[:120])

        async def start():
            self.server = ProxyServer(app.load_config(certificate_dir=directory, port=0))
            await self.server.start()
            ready.set()

        def run():
            asyncio.set_event_loop(self.loop)
            self.loop.set_exception_handler(report)
            self.loop.create_task(start())
            self.loop.run_forever()

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        if not ready.wait(30):
            raise TimeoutError("The app didn't start")
        self.args = [f"--proxy-pac-url=http://127.0.0.1:{self.server.port}/proxy.pac", "--ignore-certificate-errors"]
        return self

    def __exit__(self, *_):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)
        self.tmp.cleanup()


def visit(browser, url):
    page = browser.new_page(offline=False)
    errors = []
    page.cdp.on("Runtime.exceptionThrown", lambda _: errors.append(1), page.session_id)
    started = time.time()
    problem = None
    try:
        page.goto(url, timeout=45)
    except Exception as error:
        problem = str(error)[:70]
    seconds = round(time.time() - started, 1)
    time.sleep(8)
    try:
        page.eval("window.scrollTo(0, document.body.scrollHeight / 2)")
        time.sleep(2)
        result = page.eval(MEASURE)
    except Exception as error:
        result = {"measureError": str(error)[:70]}
    result.update(loadSeconds=seconds, jsErrors=len(errors))
    if problem:
        result["loadProblem"] = problem
    page.close()
    return result


def check_youtube(running):
    print("--- YouTube, opening a video directly ---")
    rows = []
    for video in YOUTUBE_VIDEOS:
        with Browser() as browser:
            control = watch_youtube(browser, video)
        with Browser(extra_args=running.args) as browser:
            filtered = watch_youtube(browser, video)
        rows.append((video, control, filtered))
        print(video, json.dumps({k: filtered[k] for k in ("adDataInPage", "adShowing", "adUi", "enforcementPrompt",
                                                          "videoSecondsPlayed", "secondsBeforeVideoStarted")}), flush=True)
    print(f"{'video':14}{'normal: ad?':13}{'app: ad?':10}{'app: played':13}{'app: start':12}{'normal: start':15}{'prompt':8}")
    for video, c, f in rows:
        print(f"{video:14}{str(c['adShowing'] or c['adUi']):13}{str(f['adShowing'] or f['adUi']):10}"
              f"{f['videoSecondsPlayed']:<13}{str(f['secondsBeforeVideoStarted']):12}"
              f"{str(c['secondsBeforeVideoStarted']):15}{str(f['enforcementPrompt']):8}")

    print("\n--- YouTube, clicking from search results to a video ---")
    with Browser(extra_args=running.args) as browser:
        page = browser.new_page(offline=False)
        page.goto("https://www.youtube.com/results?search_query=official+music+video", timeout=60)
        page.wait_for(f"!!document.querySelector('{SEARCH_LINK}')", timeout=25)
        time.sleep(1)
        page.eval(f"document.querySelector('{SEARCH_LINK}').click()")
        started = time.time()
        ad = False
        begun = None
        while time.time() - started < 30:
            state = page.eval("""(() => { const p = document.querySelector('.html5-video-player');
                const v = document.querySelector('video');
                return {ad: !!p?.classList.contains('ad-showing'), t: v ? v.currentTime : 0, url: location.pathname}; })()""")
            ad = ad or state["ad"]
            if state["url"] == "/watch" and state["t"] > 0.3 and begun is None:
                begun = round(time.time() - started - state["t"], 1)
                break
            time.sleep(0.2)
        print(json.dumps({"adShown": ad, "startedAfterClick": begun}), flush=True)
        page.close()


def check_sites(running):
    print("--- Real sites: normal -> through the app ---")
    print(f"{'site':14}{'ad frames':12}{'ad slots':12}{'ad labels':12}{'text':16}{'links':13}{'js errors':11}{'load seconds':14}")
    for name in SITE_NAMES:
        with Browser() as browser:
            c = visit(browser, SITES[name])
        with Browser(extra_args=running.args) as browser:
            f = visit(browser, SITES[name])

        def pair(key):
            return f"{c.get(key, '?')}->{f.get(key, '?')}"
        print(f"{name:14}{pair('adSizedFrames'):12}{pair('adSlots'):12}{pair('adLabels'):12}"
              f"{pair('textLength'):16}{pair('links'):13}{pair('jsErrors'):11}{pair('loadSeconds'):14}"
              f"{f.get('loadProblem', '')}", flush=True)


def check_twitch(running):
    print("--- Twitch, live channels through the app ---")
    for channel in find_channels()[:2]:
        with Browser(extra_args=running.args) as browser:
            result = watch_twitch(browser, channel)
        print(channel, json.dumps(result), flush=True)


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    with RunningApp() as running:
        if which in ("all", "youtube"):
            check_youtube(running)
        if which in ("all", "sites"):
            check_sites(running)
        if which in ("all", "twitch"):
            check_twitch(running)
        print("\nApp errors seen:", running.errors[:8] or "none")


if __name__ == "__main__":
    main()

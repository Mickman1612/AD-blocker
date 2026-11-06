"""Does going through the app make any listed site treat us as a bot?

Run: python -m tests.live.bot_check [rounds] [--windowed]
With --windowed it uses a normal browser window, parked off-screen. Sites often block headless browsers
whatever the route, which hides any difference the app makes.
The app connects to sites with Python's TLS rather than a browser's, which bot protection can notice.
Each page is opened directly and through the app, in temporary profiles, and any challenge page is
reported. This only reads what each site shows. It doesn't try to get past any check.
"""
import json
import re
import sys
import time

from tests.harness.browser import Browser

PAGES = {
    "linkedin": "https://www.linkedin.com/login",
    "linkedin-feed": "https://www.linkedin.com/feed/",
    "x": "https://x.com/i/flow/login",
    "facebook": "https://www.facebook.com/",
    "instagram": "https://www.instagram.com/accounts/login/",
    "tiktok": "https://www.tiktok.com/foryou",
    "pinterest": "https://www.pinterest.com/login/",
    "reddit": "https://www.reddit.com/",
    "old-reddit": "https://old.reddit.com/",
    "twitch": "https://www.twitch.tv/",
    "google": "https://www.google.com/search?q=weather",
    "bing": "https://www.bing.com/search?q=weather",
    "duckduckgo": "https://duckduckgo.com/?q=weather",
    "yahoo": "https://search.yahoo.com/search?p=weather",
    "youtube": "https://www.youtube.com/",
    "youtube-music": "https://music.youtube.com/",
}
CHALLENGE = re.compile(r"attention required|just a moment|prove your humanity|verify you are human|are you a human|"
                       r"unusual traffic|access denied|request blocked|blocked by|security check|captcha|"
                       r"you've been blocked|sorry, you have been blocked|forbidden|error 1020", re.I)
DIRECT = ["--no-proxy-server"]
WINDOWED = "--windowed" in sys.argv
OFF_SCREEN = ["--window-position=-2400,0", "--window-size=1200,900"] if WINDOWED else []


def read_page(args, url):
    with Browser(extra_args=args + OFF_SCREEN, headless=not WINDOWED) as browser:
        page = browser.new_page(offline=False)
        status = {}

        def on_response(params):
            if params.get("type") == "Document" and "code" not in status:
                status["code"] = params["response"].get("status")

        page.cdp.on("Network.responseReceived", on_response, page.session_id)
        problem = None
        try:
            page.goto(url, timeout=35)
        except Exception as error:
            problem = str(error)[:60]
        time.sleep(4)
        try:
            title = page.eval("document.title")[:44]
            text = page.eval("document.body.innerText.slice(0, 1500)")
            links = page.eval("document.links.length")
        except Exception as error:
            title, text, links = "?", "", 0
            problem = problem or str(error)[:60]
        page.close()
    challenged = bool(CHALLENGE.search(title) or CHALLENGE.search(text))
    return {"code": status.get("code"), "title": title, "chars": len(text), "links": links,
            "challenged": challenged, "problem": problem}


def main():
    rounds = int(next((a for a in sys.argv[1:] if a.isdigit()), 1))
    print(f"{'site':15}{'direct':9}{'app':9}{'direct chars':14}{'app chars':11}{'direct links':14}{'app links':11}verdict")
    worse = []
    for name, url in PAGES.items():
        for _ in range(rounds):
            direct = read_page(DIRECT, url)
            through = read_page([], url)
            flag = "same"
            if through["challenged"] and not direct["challenged"]:
                flag = "APP CAUSES A CHALLENGE"
            elif through["code"] != direct["code"] or (through["problem"] and not direct["problem"]):
                flag = "DIFFERENT"
            elif direct["challenged"] and through["challenged"]:
                flag = "both challenged"
            if "APP" in flag or flag == "DIFFERENT":
                worse.append(name)
            print(f"{name:15}{str(direct['code']):9}{str(through['code']):9}{direct['chars']:<14}{through['chars']:<11}"
                  f"{direct['links']:<14}{through['links']:<11}{flag}", flush=True)
            if flag != "same":
                print("    direct:", json.dumps(direct)[:170])
                print("    app:   ", json.dumps(through)[:170], flush=True)
    print("\nSites worse through the app:", sorted(set(worse)) or "none")


if __name__ == "__main__":
    main()

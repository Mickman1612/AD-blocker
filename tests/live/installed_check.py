"""Check the ad blocker as actually installed on this PC. Read-only, using temporary browser profiles.

Run: python -m tests.live.installed_check
The browsers here follow the real Windows proxy setting and certificate store, with no test flags,
so this is the same path your own browsers take.
"""
import json
import socket
import ssl
import subprocess
import sys
import time
import winreg

from proxy import app, install
from tests.harness.browser import Browser, EDGE
from tests.live.site_check import MEASURE

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
ROOT_NAME = "Local Ad Blocker"
VIDEOS = ["kJQP7kiw5Fk", "OPf0YbXqDm0", "JGwWNGJdvx8"]
FILTERED_SITES = ["https://www.youtube.com/", "https://www.bing.com/search?q=shoes"]
AD_SITES = ["https://edition.cnn.com/", "https://www.smh.com.au/"]
UNTOUCHED_SITES = ["https://www.amazon.com.au/", "https://www.paypal.com/au/home", "https://www.commbank.com.au/",
                   "https://accounts.google.com/", "https://github.com/", "https://www.wikipedia.org/"]
PLAYER = """(() => { const p = document.querySelector('.html5-video-player'); const v = document.querySelector('video');
  const r = window.ytInitialPlayerResponse;
  return {ad: !!p?.classList.contains('ad-showing'), t: v ? v.currentTime : 0,
          adData: (r?.adPlacements?.length || 0) + (r?.playerAds?.length || 0),
          prompt: !!document.querySelector('ytd-enforcement-message-view-model'),
          error: !!document.querySelector('.ytp-error')}; })()"""


def open_recording_issuer(browser, url, timeout=45):
    """Open a page and report who issued the certificate the browser accepted for it."""
    page = browser.new_page(offline=False)
    details = {}

    def on_response(params):
        if params.get("type") == "Document" and "issuer" not in details:
            security = params["response"].get("securityDetails") or {}
            details["issuer"] = security.get("issuer")
            details["status"] = params["response"].get("status")

    page.cdp.on("Network.responseReceived", on_response, page.session_id)
    try:
        page.goto(url, timeout=timeout)
    except Exception as error:
        details["problem"] = str(error)[:110]
    return page, details


def lookup(name):
    try:
        return socket.gethostbyname(name)
    except socket.gaierror:
        return "no address (blocked)"  # What Windows reports for a hosts entry of 0.0.0.0.


def system_checks():
    print("--- This PC ---")
    installer = install.Installer()
    for label, passed in installer.status().items():
        print(f"  [{'OK' if passed else '--'}] {label}")

    print(f"  Ad server lookup: securepubads.g.doubleclick.net -> {lookup('securepubads.g.doubleclick.net')}")
    print(f"  Normal lookup: www.youtube.com -> {lookup('www.youtube.com')}")

    ours = [c for c, _, _ in ssl.enum_certificates("ROOT") if ROOT_NAME.encode() in c]
    print(f"  Certificates of ours in Windows: {len(ours)}")
    files = sorted(p.name for p in app.data_dir().iterdir())
    print(f"  App data folder: {files}")
    print(f"  Any master key on disk: {'ca.key' in files}")

    startup = installer._read(install.RUN_KEY, install.VALUE_NAME)
    print(f"  Startup entry: {startup}")
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager") as key:
        print(f"  Windows promoted-apps setting: {winreg.QueryValueEx(key, 'SilentInstalledAppsEnabled')[0]} (0 is off)")

    pid = (app.data_dir() / "running.pid").read_text(encoding="ascii").strip()
    listing = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    print(f"  App process: {listing.strip()[:80]}")


def trust_check():
    """Windows' own root store, verifying through the app the way apps do."""
    print("\n--- Is the certificate trusted, through the app? ---")
    with socket.create_connection(("127.0.0.1", app.PORT), timeout=10) as raw:
        raw.sendall(b"CONNECT www.youtube.com:443 HTTP/1.1\r\nHost: www.youtube.com:443\r\n\r\n")
        print("  App answered:", raw.recv(200).split(b"\r\n")[0].decode())
        context = ssl.create_default_context()
        with context.wrap_socket(raw, server_hostname="www.youtube.com") as tls:
            issuer = dict(item[0] for item in tls.getpeercert()["issuer"])
            print("  Verified with Windows' certificates. Issuer:", issuer.get("commonName"))


def browser_checks(name, executable):
    print(f"\n--- {name}: real settings, no test flags ---")
    with Browser(executable=executable) as browser:
        print("  Sites the app filters:")
        for url in FILTERED_SITES:
            page, details = open_recording_issuer(browser, url)
            print(f"    {url[:42]:44}{details}")
            page.close()

        print("  Sites that must NOT go through the app:")
        for url in UNTOUCHED_SITES:
            page, details = open_recording_issuer(browser, url)
            flag = "THROUGH APP!" if ROOT_NAME in str(details.get("issuer")) else "direct"
            print(f"    {url[:42]:44}{flag:14}{details.get('issuer')}  {details.get('problem', '')}")
            page.close()

        print("  Ad-heavy sites:")
        for url in AD_SITES:
            page, details = open_recording_issuer(browser, url)
            time.sleep(8)
            result = page.eval(MEASURE)
            print(f"    {url[:42]:44}adFrames={result['adSizedFrames']} slots={result['adSlots']} "
                  f"text={result['textLength']} {details.get('problem', '')}")
            page.close()

    print("  YouTube videos, each in a fresh profile:")
    for video in VIDEOS:
        with Browser(executable=executable) as browser:
            page, details = open_recording_issuer(browser, f"https://www.youtube.com/watch?v={video}", 60)
            ad = prompt = error = False
            started = time.time()
            begun = None
            state = {"t": 0, "adData": None}
            while time.time() - started < 30:
                time.sleep(0.25)
                state = page.eval(PLAYER)
                ad, prompt, error = ad or state["ad"], prompt or state["prompt"], error or state["error"]
                if begun is None and state["t"] > 0.3 and not state["ad"]:
                    begun = round(time.time() - started - state["t"], 1)
            print(f"    {video} issuer={details.get('issuer')} adShown={ad} adData={state['adData']} "
                  f"startedAfter={begun} played={round(state['t'], 1)} warning={prompt} playerError={error} "
                  f"{details.get('problem', '')}", flush=True)
            page.close()


def main():
    system_checks()
    trust_check()
    browser_checks("Edge", EDGE)
    browser_checks("Chrome", CHROME)


if __name__ == "__main__":
    sys.exit(main())

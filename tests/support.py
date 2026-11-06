"""Shared setup for tests that load the real extension."""
import contextlib
import json
import pathlib
import re

from tests.harness.browser import Browser

REPO = pathlib.Path(__file__).resolve().parent.parent
EXTENSION = REPO / "extension"
HTML = {"Content-Type": "text/html"}
JS = {"Content-Type": "text/javascript", "Access-Control-Allow-Origin": "*"}
CORS_JSON = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}


@contextlib.contextmanager
def extension_browser():
    """Real Edge, temporary profile, real extension, with its scripts registered."""
    with Browser(extension_path=EXTENSION) as browser:
        browser.service_worker_wait_for(
            "chrome.scripting.getRegisteredContentScripts().then(s => s.length > 0)", timeout=15)
        yield browser


def page_with(browser, url, html, **fixtures):
    """Open a fake page at a real-looking URL. fixtures maps a regex to (body, headers)."""
    page = browser.new_page()
    for pattern, (body, headers) in fixtures.items():
        page.fixture(pattern, body, headers=headers)
    page.fixture("^" + re.escape(url) + "$", html, headers=HTML)
    page.goto(url)
    return page


def is_hidden(page, selector):
    return page.eval(f"""(() => {{
        const el = document.querySelector({json.dumps(selector)});
        if (!el) throw new Error('fixture element missing: ' + {json.dumps(selector)});
        return getComputedStyle(el).display === 'none';
    }})()""")


def send_message(browser, message):
    """Talk to the service worker the way the pop-up does."""
    page = browser.open_extension_page("popup/popup.html")
    try:
        return page.eval(f"chrome.runtime.sendMessage({json.dumps(message)})")
    finally:
        page.close()

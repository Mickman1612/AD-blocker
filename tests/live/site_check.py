"""Live check on real sites, with and without the extension, using temporary profiles.

Run: python -m tests.live.site_check [names...]
It looks for two things: ads still showing, and sites broken by blocking.
Results are evidence to read, not pass or fail, because real sites change constantly.
"""
import json
import sys
import time

from tests.harness.browser import Browser
from tests.support import EXTENSION

READY = "chrome.scripting.getRegisteredContentScripts().then(s => s.length > 0)"
SETTLE_SECONDS = 8

SITES = {
    "guardian": "https://www.theguardian.com/international",
    "cnn": "https://edition.cnn.com/",
    "forbes": "https://www.forbes.com/",
    "weather": "https://weather.com/",
    "abc-au": "https://www.abc.net.au/news",
    "news-au": "https://www.news.com.au/",
    "smh": "https://www.smh.com.au/",
    "wikipedia": "https://en.wikipedia.org/wiki/Advertising",
    "github": "https://github.com/explore",
    "stackoverflow": "https://stackoverflow.com/questions",
    "reddit": "https://www.reddit.com/r/technology/",
    "old-reddit": "https://old.reddit.com/r/technology/",
    "twitch": "https://www.twitch.tv/directory",
    "google": "https://www.google.com/search?q=buy+running+shoes+online",
    "bing": "https://www.bing.com/search?q=buy+running+shoes+online",
    "duckduckgo": "https://duckduckgo.com/?q=buy+running+shoes+online",
    "yahoo": "https://search.yahoo.com/search?p=buy+running+shoes+online",
    "amazon": "https://www.amazon.com.au/s?k=running+shoes",
    "ebay": "https://www.ebay.com.au/sch/i.html?_nkw=running+shoes",
    "youtube-home": "https://www.youtube.com/",
    "pinterest": "https://www.pinterest.com/ideas/",
}

MEASURE = r"""(() => {
  const AD_SIZES = new Set(['120x600','160x600','250x250','300x50','300x100','300x250','300x600','320x50','320x100','336x280','468x60','728x90','970x90','970x250']);
  const visible = (e) => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 1 && r.height > 1 && s.display !== 'none' && s.visibility !== 'hidden'; };
  const frames = [...document.querySelectorAll('iframe')].filter(visible);
  const adFrames = frames.filter((f) => { const r = f.getBoundingClientRect();
    return AD_SIZES.has(Math.round(r.width) + 'x' + Math.round(r.height)); });
  const AD_SELECTOR = '[id^="google_ads_iframe"],[id^="div-gpt-ad"],ins.adsbygoogle,.adsbygoogle,[data-ad-slot],[data-google-query-id],#tads,.b_ad,[data-testid="ad"],[data-layout="ad"],.AdHolder,[data-component-type="sp-sponsored-result"],shreddit-ad-post,.promotedlink,ytd-ad-slot-renderer,.searchCenterTopAds';
  const adSlots = [...document.querySelectorAll(AD_SELECTOR)].filter(visible);
  const labels = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const t = n.nodeValue.trim();
    if (/^(advertisement|sponsored|ad|ads|promoted|sponsored results?)$/i.test(t) && n.parentElement && visible(n.parentElement)) labels.push(t);
  }
  return {
    title: document.title.slice(0, 50),
    textLength: document.body.innerText.length,
    links: document.links.length,
    images: [...document.images].filter(visible).length,
    frames: frames.length,
    adSizedFrames: adFrames.length,
    adSlots: adSlots.length,
    adLabels: labels.length,
    samples: adSlots.slice(0, 3).map((e) => e.tagName.toLowerCase() + (e.id ? '#' + e.id.slice(0, 24) : '') + (e.className && e.className.baseVal === undefined ? '.' + String(e.className).slice(0, 30) : '')),
  };
})()"""


def visit(browser, url):
    page = browser.new_page(offline=False)
    errors = []
    page.cdp.on("Runtime.exceptionThrown", lambda _: errors.append(1), page.session_id)
    failure = None
    try:
        page.goto(url, timeout=45)
    except Exception as error:
        failure = str(error)[:80]
    time.sleep(SETTLE_SECONDS)
    try:
        page.eval("window.scrollTo(0, document.body.scrollHeight / 2)")
        time.sleep(2)
        result = page.eval(MEASURE)
    except Exception as error:
        result = {"measureError": str(error)[:80]}
    result["requests"] = len(page.requests())
    result["blocked"] = len(page.blocked_requests())
    result["jsErrors"] = len(errors)
    if failure:
        result["loadProblem"] = failure
    page.close()
    return result


def main():
    names = sys.argv[1:] or list(SITES)
    rows = {}
    for name in names:
        with Browser() as browser:
            control = visit(browser, SITES[name])
        with Browser(extension_path=EXTENSION) as browser:
            browser.service_worker_wait_for(READY, timeout=15)
            blocked = visit(browser, SITES[name])
        rows[name] = (control, blocked)
        print(name, "control", json.dumps(control), flush=True)
        print(name, "blocked", json.dumps(blocked), flush=True)

    print("\n--- Summary: control -> with extension ---")
    print(f"{'site':14}{'ad frames':12}{'ad slots':12}{'ad labels':12}{'text':16}{'links':13}{'js errors':11}{'blocked':8}")
    for name, (c, b) in rows.items():
        def pair(key):
            return f"{c.get(key, '?')}->{b.get(key, '?')}"
        print(f"{name:14}{pair('adSizedFrames'):12}{pair('adSlots'):12}{pair('adLabels'):12}"
              f"{pair('textLength'):16}{pair('links'):13}{pair('jsErrors'):11}{b.get('blocked', '?'):<8}")


if __name__ == "__main__":
    main()

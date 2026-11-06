"""Every other platform, tested offline with fake pages on the real hostnames."""
import json
import time
import unittest

from tests.support import CORS_JSON, JS, extension_browser, is_hidden, page_with
from tests.test_youtube import silent_wav


class PlatformTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = extension_browser()
        cls.browser = cls.context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)

    def open(self, url, html="<p>", **fixtures):
        page = page_with(self.browser, url, html, **fixtures)
        self.addCleanup(page.close)
        return page


# (name, url, page html). Elements with id "ad*" must be hidden, id "real*" must stay visible.
HIDING_CASES = [
    ("reddit new", "https://www.reddit.com/", """
        <shreddit-ad-post id=ad1></shreddit-ad-post>
        <shreddit-comments-page-ad id=ad2></shreddit-comments-page-ad>
        <shreddit-sidebar-ad id=ad3></shreddit-sidebar-ad>
        <shreddit-post id=real1>post</shreddit-post>"""),
    ("reddit old", "https://old.reddit.com/", """
        <div class="thing promotedlink" id=ad1>promoted</div>
        <div class="thing link" id=real1>post</div>"""),
    ("google search", "https://www.google.com/search?q=shoes", """
        <div id=tads>sponsored results</div>
        <div id=bottomads>sponsored results</div>
        <div class="commercial-unit-desktop-rhs" id=ad3>shopping</div>
        <div id=search><div id=real1>organic result</div></div>"""),
    ("google search in another country", "https://www.google.com.au/search?q=shoes", """
        <div id=tads>sponsored results</div>
        <div id=search><div id=real1>organic result</div></div>"""),
    ("bing", "https://www.bing.com/search?q=shoes", """
        <ol id=b_results><li class="b_ad" id=ad1>ad</li><li class="b_algo" id=real1>organic</li></ol>"""),
    ("duckduckgo", "https://duckduckgo.com/?q=shoes", """
        <li data-layout="ad" id=ad1>ad</li>
        <div data-testid="ad" id=ad2>ad</div>
        <article data-testid="result" id=real1>organic</article>"""),
    ("yahoo search", "https://search.yahoo.com/search?p=shoes", """
        <div class="searchCenterTopAds" id=ad1>ad</div>
        <div class="searchCenterBottomAds" id=ad2>ad</div>
        <div class="algo" id=real1>organic</div>"""),
    ("amazon", "https://www.amazon.com/s?k=shoes", """
        <div data-component-type="sp-sponsored-result" id=ad1>sponsored</div>
        <div class="AdHolder" id=ad2>sponsored</div>
        <div data-cel-widget="desktop-loom-adplacements_1" id=ad3>sponsored</div>
        <div data-component-type="s-search-result" id=real1>product</div>"""),
    ("amazon in another country", "https://www.amazon.co.uk/s?k=shoes", """
        <div class="AdHolder" id=ad1>sponsored</div>
        <div data-component-type="s-search-result" id=real1>product</div>"""),
    ("twitch", "https://www.twitch.tv/somechannel", """
        <div data-a-target="video-ad-label" id=ad1>Ad</div>
        <div data-test-selector="sad-overlay" id=ad2>overlay</div>
        <div data-a-target="video-player" id=real1>player</div>"""),
    ("linkedin", "https://www.linkedin.com/feed/", """
        <section class="ad-banner-container" id=ad1>banner</section>
        <div class="feed-shared-update-v2" id=real1>post</div>"""),
    ("x", "https://x.com/home", """
        <div data-testid="cellInnerDiv" id=ad1><article><div data-testid="placementTracking"></div>
          promoted post</article></div>
        <div data-testid="cellInnerDiv" id=real1><article>normal post</article></div>"""),
    ("spotify", "https://open.spotify.com/", """
        <div data-testid="hpto-container" id=ad1>takeover banner</div>
        <div data-testid="top-sellers" id=real1>music</div>"""),
]


class HidingTests(PlatformTestCase):
    def test_each_platform_hides_ads_and_keeps_content(self):
        for name, url, html in HIDING_CASES:
            with self.subTest(name):
                page = page_with(self.browser, url, html)
                try:
                    ids = page.eval("[...document.querySelectorAll('[id]')].map(e => e.id)")
                    ads = [i for i in ids if i.startswith("ad") or i in ("tads", "bottomads")]
                    real = [i for i in ids if i.startswith("real")]
                    self.assertTrue(ads and real, "fixture needs both")
                    page.wait_for(" && ".join(
                        f"getComputedStyle(document.getElementById('{i}')).display === 'none'" for i in ads),
                        timeout=3)
                    for element in real:
                        self.assertFalse(is_hidden(page, f"#{element}"), element)
                finally:
                    page.close()


# (name, url, ad item html, normal item html). Items are added after load, like a real feed.
FEED_CASES = [
    ("facebook", "https://www.facebook.com/",
     '<div role="article" class="i"><a href="/ads/about/?x=1" aria-label="Sponsored">Sponsored</a> buy this</div>',
     '<div role="article" class="i"><a href="/friend">Friend</a> posted a photo</div>'),
    ("instagram", "https://www.instagram.com/",
     '<article class="i"><header><span>brand</span><span>Sponsored</span></header><img></article>',
     '<article class="i"><header><span>friend</span></header><img></article>'),
    ("linkedin", "https://www.linkedin.com/feed/",
     '<div class="feed-shared-update-v2 i"><span class="update-components-actor__sub-description">Promoted</span>buy</div>',
     '<div class="feed-shared-update-v2 i"><span class="update-components-actor__sub-description">2h</span>news</div>'),
    ("pinterest", "https://www.pinterest.com/",
     '<div data-grid-item="true" class="i"><div>Promoted by</div><div>brand</div></div>',
     '<div data-grid-item="true" class="i"><div>recipe pin</div></div>'),
    ("tiktok", "https://www.tiktok.com/foryou",
     '<div data-e2e="recommend-list-item-container" class="i"><span>Sponsored</span>video</div>',
     '<div data-e2e="recommend-list-item-container" class="i"><span>creator</span>video</div>'),
    ("x", "https://x.com/home",
     '<div data-testid="cellInnerDiv" class="i"><article><span>Ad</span>brand post</article></div>',
     '<div data-testid="cellInnerDiv" class="i"><article><span>Add this to your day</span>a post</article></div>'),
    ("reddit", "https://www.reddit.com/",
     '<article class="i"><shreddit-ad-post></shreddit-ad-post></article>',
     '<article class="i"><shreddit-post>post</shreddit-post></article>'),
    ("ebay", "https://www.ebay.com/sch/i.html?_nkw=shoes",
     '<li class="s-item i"><span>Sponsored</span>listing</li>',
     '<li class="s-item i"><span>Buy it now</span>listing</li>'),
]


class FeedTests(PlatformTestCase):
    def test_each_feed_hides_ad_items_added_after_load_and_keeps_normal_ones(self):
        for name, url, ad_html, normal_html in FEED_CASES:
            with self.subTest(name):
                page = page_with(self.browser, url, '<main id="feed"></main>')
                try:
                    page.eval(f"""(() => {{
                        const feed = document.getElementById('feed');
                        feed.insertAdjacentHTML('beforeend', {json.dumps(normal_html)});
                        feed.insertAdjacentHTML('beforeend', {json.dumps(ad_html)});
                        feed.insertAdjacentHTML('beforeend', {json.dumps(normal_html)});
                    }})()""")
                    page.wait_for("getComputedStyle(document.querySelectorAll('.i')[1]).display === 'none'",
                                  timeout=3)
                    self.assertEqual(page.eval(
                        "[...document.querySelectorAll('.i')].map(e => getComputedStyle(e).display !== 'none')"),
                        [True, False, True])
                finally:
                    page.close()

    def test_an_item_whose_ad_marker_arrives_late_is_still_hidden(self):
        page = self.open("https://www.instagram.com/", '<main id="feed"></main>')
        page.eval("""(() => {
            const feed = document.getElementById('feed');
            feed.insertAdjacentHTML('beforeend', '<article class="i"><header id="h"></header></article>');
        })()""")
        time.sleep(0.5)
        self.assertFalse(is_hidden(page, ".i"))
        page.eval("document.getElementById('h').insertAdjacentHTML('beforeend', '<span>Sponsored</span>')")
        page.wait_for("getComputedStyle(document.querySelector('.i')).display === 'none'", timeout=3)


class SocialDataTests(PlatformTestCase):
    """Ad entries removed from data, before the site ever draws them."""

    def test_x_timeline_loses_promoted_entries(self):
        body = json.dumps({"data": {"home": {"instructions": [{"entries": [
            {"entryId": "tweet-1", "content": {"itemContent": {"tweet_results": {"id": 1}}}},
            {"entryId": "promoted-tweet-2", "content": {"itemContent": {"promotedMetadata": {"x": 1}}}},
            {"entryId": "tweet-3", "content": {"itemContent": {"tweet_results": {"id": 3}}}},
        ]}]}}})
        page = self.open("https://x.com/home", **{r"x\.com/i/api/graphql": (body, CORS_JSON)})
        data = page.eval("fetch('/i/api/graphql/abc/HomeTimeline').then(r => r.json())")
        ids = [e["entryId"] for e in data["data"]["home"]["instructions"][0]["entries"]]
        self.assertEqual(ids, ["tweet-1", "tweet-3"])

    def test_tiktok_feed_loses_ad_items(self):
        body = json.dumps({"itemList": [{"id": "1", "isAd": False}, {"id": "2", "isAd": True}, {"id": "3"}]})
        page = self.open("https://www.tiktok.com/foryou",
                         **{r"tiktok\.com/api/recommend/item_list": (body, CORS_JSON)})
        data = page.eval("fetch('/api/recommend/item_list/?x=1').then(r => r.json())")
        self.assertEqual([i["id"] for i in data["itemList"]], ["1", "3"])

    def test_instagram_feed_loses_ad_items(self):
        body = json.dumps({"data": {"feed": {"edges": [
            {"node": {"media": {"id": "1", "ad_id": None}}},
            {"node": {"media": {"id": "2", "ad_id": "999"}}},
            {"node": {"ad": {"id": "x"}}},
        ]}}})
        page = self.open("https://www.instagram.com/", **{r"instagram\.com/graphql/query": (body, CORS_JSON)})
        data = page.eval("fetch('/graphql/query').then(r => r.json())")
        self.assertEqual(len(data["data"]["feed"]["edges"]), 1)
        self.assertEqual(data["data"]["feed"]["edges"][0]["node"]["media"]["id"], "1")

    def test_facebook_parsed_data_loses_sponsored_items(self):
        page = self.open("https://www.facebook.com/")
        text = json.dumps({"edges": [{"node": {"id": "1", "category": "ORGANIC"}},
                                     {"node": {"id": "2", "category": "SPONSORED"}},
                                     {"node": {"id": "3", "sponsored_data": {"x": 1}}}]})
        data = page.eval(f"JSON.parse({json.dumps(text)})")
        self.assertEqual([e["node"]["id"] for e in data["edges"]], ["1"])


AD_PLAYLIST = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:6
#EXT-X-MEDIA-SEQUENCE:100
#EXT-X-DATERANGE:ID="stitched-ad-1",CLASS="twitch-stitched-ad",START-DATE="2026-01-01T00:00:00Z",DURATION=30
#EXTINF:2.000,Amazon|1234
https://video.ttvnw.net/ad-segment-1.ts
#EXTINF:2.000,Amazon|1235
https://video.ttvnw.net/ad-segment-2.ts
#EXT-X-DISCONTINUITY
#EXTINF:2.000,live
https://video.ttvnw.net/real-segment-1.ts
#EXTINF:2.000,live
https://video.ttvnw.net/real-segment-2.ts
"""
CLEAN_PLAYLIST = """#EXTM3U
#EXT-X-VERSION:3
#EXTINF:2.000,live
https://video.ttvnw.net/real-segment-1.ts
"""
WORKER_FETCH = """new Promise((resolve, reject) => {
    const source = `fetch('https://usher.ttvnw.net/playlist.m3u8').then(r => r.text()).then(t => postMessage(t), e => postMessage('error: ' + e));`;
    const worker = new Worker(URL.createObjectURL(new Blob([source], {type: 'text/javascript'})));
    worker.onmessage = (event) => resolve(event.data);
    worker.onerror = (event) => reject(new Error(event.message));
})"""
M3U8 = {"Content-Type": "application/vnd.apple.mpegurl", "Access-Control-Allow-Origin": "*"}


class TwitchStreamTests(PlatformTestCase):
    def test_page_level_playlist_loses_stitched_ad_segments(self):
        page = self.open("https://www.twitch.tv/x", **{r"playlist\.m3u8": (AD_PLAYLIST, M3U8)})
        text = page.eval("fetch('https://usher.ttvnw.net/playlist.m3u8').then(r => r.text())")
        self.assertNotIn("ad-segment", text)
        self.assertNotIn("twitch-stitched-ad", text)
        self.assertIn("real-segment-1.ts", text)
        self.assertIn("real-segment-2.ts", text)
        self.assertTrue(text.startswith("#EXTM3U"))

    def test_playlist_without_ads_is_unchanged(self):
        page = self.open("https://www.twitch.tv/x", **{r"playlist\.m3u8": (CLEAN_PLAYLIST, M3U8)})
        self.assertEqual(page.eval("fetch('https://usher.ttvnw.net/playlist.m3u8').then(r => r.text())"),
                         CLEAN_PLAYLIST)

    def test_player_worker_gets_the_cleaned_playlist_too(self):
        page = self.open("https://www.twitch.tv/x", **{r"playlist\.m3u8": (AD_PLAYLIST, M3U8)})
        text = page.eval(WORKER_FETCH)
        self.assertNotIn("ad-segment", text)
        self.assertIn("real-segment-1.ts", text)

    def test_ordinary_workers_still_run(self):
        page = self.open("https://www.twitch.tv/x")
        result = page.eval("""new Promise(resolve => {
            const source = "self.onmessage = (e) => postMessage(e.data + 1);";
            const worker = new Worker(URL.createObjectURL(new Blob([source], {type: 'text/javascript'})));
            worker.onmessage = (event) => resolve(event.data);
            worker.postMessage(41);
        })""")
        self.assertEqual(result, 42)


GUARD_PLAYER = """<div data-a-target="video-player" id=player>
    <video id=v src="https://{host}/fake.wav" autoplay></video></div>"""


class LiveAdGuardTests(PlatformTestCase):
    """Sites that must not be sped up or seeked, because that breaks their players."""

    CASES = [
        ("twitch", "www.twitch.tv", "/x", '<div data-a-target="video-ad-countdown" id=mark></div>'),
        ("netflix", "www.netflix.com", "/watch/1", '<div data-uia="ads-info-container" id=mark></div>'),
        ("prime", "www.primevideo.com", "/detail", '<div class="atvwebplayersdk-ad-timer" id=mark></div>'),
        ("hulu", "www.hulu.com", "/watch/1", '<div class="AdUnitView" id=mark></div>'),
    ]

    def test_ad_is_muted_and_hidden_without_seeking_and_restored_after(self):
        for name, host, path, marker in self.CASES:
            with self.subTest(name):
                page = page_with(self.browser, f"https://{host}{path}",
                                 GUARD_PLAYER.format(host=host) + '<div id=holder></div>',
                                 **{r"fake\.wav": (silent_wav(), {"Content-Type": "audio/wav"})})
                try:
                    page.wait_for("document.querySelector('#v').duration > 0")
                    page.eval(f"document.getElementById('holder').innerHTML = {json.dumps(marker)}")
                    page.wait_for("document.querySelector('#v').muted", timeout=3)
                    page.wait_for("document.querySelector('#v').style.opacity === '0'", timeout=3)
                    self.assertEqual(page.eval("document.querySelector('#v').playbackRate"), 1)
                    page.eval("document.getElementById('holder').innerHTML = ''")
                    page.wait_for("!document.querySelector('#v').muted", timeout=3)
                    self.assertEqual(page.eval("document.querySelector('#v').style.opacity"), "")
                finally:
                    page.close()


class ImaStandInTests(PlatformTestCase):
    """Many video players use Google's IMA library. They must resume the show, not stall."""

    PAGE = """
        <video id=v></video><div id=c></div>
        <script src="https://imasdk.googleapis.com/js/sdkloader/ima3.js"></script>
        <script>
          window.done = new Promise((resolve, reject) => {
            const ima = google.ima;
            const display = new ima.AdDisplayContainer(document.getElementById('c'), document.getElementById('v'));
            display.initialize();
            const loader = new ima.AdsLoader(display);
            loader.addEventListener(ima.AdsManagerLoadedEvent.Type.ADS_MANAGER_LOADED, (event) => {
              const manager = event.getAdsManager(document.getElementById('v'));
              manager.addEventListener(ima.AdEvent.Type.CONTENT_RESUME_REQUESTED, () => resolve('resumed'));
              manager.addEventListener(ima.AdEvent.Type.ALL_ADS_COMPLETED, () => {});
              manager.init(640, 360, ima.ViewMode.NORMAL);
              manager.start();
            }, false);
            loader.addEventListener(ima.AdErrorEvent.Type.AD_ERROR, () => resolve('error-path'), false);
            const request = new ima.AdsRequest();
            request.adTagUrl = 'https://ads.example.org/vast.xml';
            request.linearAdSlotWidth = 640;
            loader.requestAds(request);
          });
        </script>"""

    def test_player_is_told_there_are_no_ads_and_continues(self):
        page = self.open("https://news.example.test/video", self.PAGE)
        self.assertIn(page.eval("window.done"), ("resumed", "error-path"))

    def test_no_real_ad_request_is_made(self):
        page = self.open("https://news.example.test/video", self.PAGE)
        page.eval("window.done")
        self.assertFalse(any("vast.xml" in url for url in page.requests()))


if __name__ == "__main__":
    unittest.main()

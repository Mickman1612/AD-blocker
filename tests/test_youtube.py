"""YouTube, tested offline: fake responses on the real hostname, real extension in real Edge."""
import io
import json
import unittest
import wave

from tests.support import CORS_JSON, HTML, JS, extension_browser, is_hidden, page_with

WATCH = "https://www.youtube.com/watch?v=test"
PLAYER_RESPONSE = {
    "playabilityStatus": {"status": "OK"},
    "streamingData": {"formats": [{"itag": 18}]},
    "videoDetails": {"videoId": "test"},
    "adPlacements": [{"adPlacementRenderer": {}}],
    "adSlots": [{"adSlotRenderer": {}}],
    "playerAds": [{"playerLegacyDesktopWatchAdsRenderer": {}}],
    "adBreakHeartbeatParams": "abc",
    "auxiliaryUi": {"messageRenderers": {"bkaEnforcementMessageViewModel": {"x": 1}}},
}
AD_KEYS = ("adPlacements", "adSlots", "playerAds", "adBreakHeartbeatParams")
PLAYER_URL = r"youtube\.com/youtubei/v1/player"


def silent_wav(seconds=5):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(1)
        out.setframerate(8000)
        out.writeframes(b"\x80" * 8000 * seconds)
    return buffer.getvalue()


class YoutubeTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = extension_browser()
        cls.browser = cls.context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)

    def open(self, html="<p>", url=WATCH, **fixtures):
        page = page_with(self.browser, url, html, **fixtures)
        self.addCleanup(page.close)
        return page

    def assert_clean(self, data):
        for key in AD_KEYS:
            self.assertNotIn(key, data)
        self.assertEqual(data["streamingData"], PLAYER_RESPONSE["streamingData"])
        self.assertEqual(data["videoDetails"], PLAYER_RESPONSE["videoDetails"])


class ResponseScrubbingTests(YoutubeTestCase):
    def test_inline_player_response_loses_ad_data_and_keeps_the_video(self):
        page = self.open(f"<script>var ytInitialPlayerResponse = {json.dumps(PLAYER_RESPONSE)};</script>")
        self.assert_clean(page.eval("window.ytInitialPlayerResponse"))

    def test_inline_page_data_loses_ad_items_and_keeps_videos(self):
        data = {"contents": [{"adSlotRenderer": {}}, {"richItemRenderer": {"id": "v1"}},
                             {"promotedSparklesWebRenderer": {}}]}
        page = self.open(f"<script>var ytInitialData = {json.dumps(data)};</script>")
        self.assertEqual(page.eval("window.ytInitialData.contents"),
                         [{"richItemRenderer": {"id": "v1"}}])

    def test_fetch_response_loses_ad_data(self):
        page = self.open(**{PLAYER_URL: (json.dumps(PLAYER_RESPONSE), CORS_JSON)})
        self.assert_clean(page.eval("fetch('/youtubei/v1/player').then(r => r.json())"))

    def test_fetch_with_a_request_object_loses_ad_data(self):
        page = self.open(**{PLAYER_URL: (json.dumps(PLAYER_RESPONSE), CORS_JSON)})
        self.assert_clean(page.eval(
            "fetch(new Request('/youtubei/v1/player', {method: 'POST', body: '{}'})).then(r => r.json())"))

    def test_rewritten_response_still_looks_like_the_original(self):
        page = self.open(**{PLAYER_URL: (json.dumps(PLAYER_RESPONSE), CORS_JSON)})
        details = page.eval("""fetch('/youtubei/v1/player').then(r => ({
            url: r.url, status: r.status, ok: r.ok, type: r.type,
            contentType: r.headers.get('content-type')}))""")
        self.assertEqual(details, {
            "url": "https://www.youtube.com/youtubei/v1/player", "status": 200, "ok": True,
            "type": "basic", "contentType": "application/json"})

    def test_response_with_the_anti_xssi_prefix_keeps_it(self):
        body = ")]}'\n" + json.dumps(PLAYER_RESPONSE)
        page = self.open(**{PLAYER_URL: (body, CORS_JSON)})
        text = page.eval("fetch('/youtubei/v1/player').then(r => r.text())")
        self.assertTrue(text.startswith(")]}'"))
        self.assert_clean(json.loads(text[4:].strip()))

    def test_xhr_text_response_loses_ad_data(self):
        page = self.open(**{PLAYER_URL: (json.dumps(PLAYER_RESPONSE), CORS_JSON)})
        text = page.eval("""new Promise(resolve => {
            const x = new XMLHttpRequest();
            x.open('POST', '/youtubei/v1/player');
            x.onload = () => resolve(x.responseText);
            x.send('{}');
        })""")
        self.assert_clean(json.loads(text))

    def test_xhr_json_response_loses_ad_data(self):
        page = self.open(**{PLAYER_URL: (json.dumps(PLAYER_RESPONSE), CORS_JSON)})
        self.assert_clean(page.eval("""new Promise(resolve => {
            const x = new XMLHttpRequest();
            x.open('POST', '/youtubei/v1/player');
            x.responseType = 'json';
            x.onload = () => resolve(x.response);
            x.send('{}');
        })"""))

    def test_json_parse_removes_ad_data(self):
        page = self.open()
        self.assert_clean(page.eval(f"JSON.parse({json.dumps(json.dumps(PLAYER_RESPONSE))})"))

    def test_json_parse_leaves_other_data_untouched(self):
        page = self.open()
        self.assertEqual(page.eval("""JSON.parse('{"a":[1,{"b":2}],"headline":"adPlacements explained"}')"""),
                         {"a": [1, {"b": 2}], "headline": "adPlacements explained"})

    def test_json_parse_still_throws_on_bad_input(self):
        page = self.open()
        self.assertEqual(page.eval("(() => { try { JSON.parse('{bad'); } catch (e) { return e.name; } })()"),
                         "SyntaxError")

    def test_malformed_response_passes_through_unchanged(self):
        page = self.open(**{PLAYER_URL: ("not json, mentions adPlacements", CORS_JSON)})
        self.assertEqual(page.eval("fetch('/youtubei/v1/player').then(r => r.text())"),
                         "not json, mentions adPlacements")

    def test_other_urls_are_not_rewritten(self):
        body = json.dumps({"adPlacements": ["kept"]})
        page = self.open(**{r"youtube\.com/api/other": (body, CORS_JSON)})
        self.assertEqual(page.eval("fetch('/api/other').then(r => r.text())"), body)

    def test_anti_adblock_message_is_removed(self):
        page = self.open(f"<script>var ytInitialPlayerResponse = {json.dumps(PLAYER_RESPONSE)};</script>")
        self.assertNotIn("bkaEnforcementMessageViewModel", json.dumps(page.eval("window.ytInitialPlayerResponse")))

    def test_hooks_do_not_run_on_other_sites(self):
        page = self.open(url="https://www.example.test/")
        self.assertEqual(page.eval("JSON.parse('{\"adPlacements\":[1]}')"), {"adPlacements": [1]})


class YoutubeHidingTests(YoutubeTestCase):
    def test_hides_feed_and_page_ads_and_keeps_videos(self):
        page = self.open("""
            <ytd-ad-slot-renderer id=a></ytd-ad-slot-renderer>
            <ytd-in-feed-ad-layout-renderer id=b></ytd-in-feed-ad-layout-renderer>
            <div id=masthead-ad></div>
            <ytd-companion-slot-renderer id=c></ytd-companion-slot-renderer>
            <ytd-enforcement-message-view-model id=d></ytd-enforcement-message-view-model>
            <ytd-rich-item-renderer id=video>real video</ytd-rich-item-renderer>""")
        for selector in ("#a", "#b", "#masthead-ad", "#c", "#d"):
            self.assertTrue(is_hidden(page, selector), selector)
        self.assertFalse(is_hidden(page, "#video"))


class VideoGuardTests(YoutubeTestCase):
    PLAYER = """<div class="html5-video-player" id=player>
        <video id=v src="https://www.youtube.com/fake.wav" autoplay></video>
        <button class="ytp-skip-ad-button" id=skip onclick="window.skipped = true">Skip</button>
        </div>"""

    def open_player(self):
        page = self.open(self.PLAYER, **{r"fake\.wav": (silent_wav(), {"Content-Type": "audio/wav"})})
        page.wait_for("document.querySelector('#v').duration > 0")
        return page

    def test_ad_is_muted_skipped_and_fast_forwarded(self):
        page = self.open_player()
        page.eval("document.querySelector('#player').classList.add('ad-showing')")
        page.wait_for("document.querySelector('#v').muted")
        page.wait_for("window.skipped === true")
        page.wait_for("document.querySelector('#v').currentTime >= 4.9")

    def test_sound_and_speed_come_back_when_the_ad_ends(self):
        page = self.open_player()
        page.eval("document.querySelector('#player').classList.add('ad-showing')")
        page.wait_for("document.querySelector('#v').muted")
        page.eval("document.querySelector('#player').classList.remove('ad-showing')")
        page.wait_for("!document.querySelector('#v').muted")
        self.assertEqual(page.eval("document.querySelector('#v').playbackRate"), 1)

    def test_a_user_who_had_muted_stays_muted(self):
        page = self.open_player()
        page.eval("document.querySelector('#v').muted = true")
        page.eval("document.querySelector('#player').classList.add('ad-showing')")
        page.wait_for("window.skipped === true")
        page.eval("document.querySelector('#player').classList.remove('ad-showing')")
        page.wait_for("document.querySelector('#v').playbackRate === 1")
        self.assertTrue(page.eval("document.querySelector('#v').muted"))

    def test_normal_playback_is_left_alone(self):
        page = self.open_player()
        page.wait_for("document.querySelector('#v').currentTime > 0.2")
        self.assertFalse(page.eval("document.querySelector('#v').muted"))
        self.assertLess(page.eval("document.querySelector('#v').currentTime"), 4)
        self.assertFalse(page.eval("window.skipped === true"))


class AntiDetectionTests(YoutubeTestCase):
    def test_youtube_ad_status_check_gets_the_answer_it_expects(self):
        page = self.open('<script src="https://static.doubleclick.net/instream/ad_status.js"></script>')
        self.assertEqual(page.eval("window.google_ad_status"), 1)

    def test_country_specific_google_ad_paths_are_blocked(self):
        page = self.open()
        page.eval("fetch('https://www.google.com.au/pagead/1p-user-list/1', {mode: 'no-cors'}).catch(() => {})")
        page.wait_for_blocked("google.com.au/pagead")


if __name__ == "__main__":
    unittest.main()

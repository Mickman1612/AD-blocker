import time
import unittest

from tests.support import HTML, JS, extension_browser, is_hidden, page_with, send_message

ARTICLE = "https://news.example.test/"
FETCH_BOTH = """Promise.allSettled([
    fetch('https://securepubads.g.doubleclick.net/gampad/ads?x=1'),
    fetch('https://cdn.example.test/app.js')])"""


class NetworkBlockingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = extension_browser()
        cls.browser = cls.context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)

    def open(self, html="<p>article</p>", **fixtures):
        page = page_with(self.browser, ARTICLE, html, **fixtures)
        self.addCleanup(page.close)
        return page

    def test_blocks_ad_network_requests(self):
        page = self.open(**{r"cdn\.example\.test": ("1", JS)})
        page.eval(FETCH_BOTH)
        page.wait_for_blocked("doubleclick.net")

    def test_leaves_ordinary_requests_alone(self):
        page = self.open(**{r"cdn\.example\.test": ("1", JS)})
        result = page.eval("fetch('https://cdn.example.test/app.js').then(r => r.status)")
        self.assertEqual(result, 200)
        self.assertEqual(page.blocked_requests(), [])

    def test_a_page_the_user_opens_directly_is_not_blocked(self):
        page = page_with(self.browser, "https://www.doubleclick.net/", "<p id=x>direct</p>")
        self.addCleanup(page.close)
        self.assertEqual(page.eval("document.getElementById('x').textContent"), "direct")

    def test_blocks_youtube_ad_paths_but_not_the_rest_of_youtube(self):
        page = self.open(**{r"youtube\.com/api/stats/playback": ("{}", JS)})
        page.eval("""Promise.allSettled([
            fetch('https://www.youtube.com/pagead/viewthroughconversion/1'),
            fetch('https://www.youtube.com/api/stats/playback')])""")
        page.wait_for_blocked("youtube.com/pagead")
        self.assertFalse(any("stats/playback" in u for u in page.blocked_requests()))


class HidingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = extension_browser()
        cls.browser = cls.context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)

    def open(self, html, **fixtures):
        page = page_with(self.browser, ARTICLE, html, **fixtures)
        self.addCleanup(page.close)
        return page

    def test_hides_standard_ad_slots_and_keeps_content(self):
        page = self.open('<ins class="adsbygoogle" id=ad></ins><div class="article" id=body>hi</div>')
        self.assertTrue(is_hidden(page, "#ad"))
        self.assertFalse(is_hidden(page, "#body"))

    def test_hides_cross_origin_iframe_at_a_standard_ad_size(self):
        page = self.open('<iframe id=ad src="https://unknown-network.example.org/x" '
                         'width=300 height=250></iframe>',
                         **{r"unknown-network": ("<p>", HTML)})
        page.wait_for(f"getComputedStyle(document.querySelector('#ad')).display === 'none'")

    def test_keeps_same_origin_iframe_at_an_ad_size(self):
        page = self.open('<iframe id=f src="https://news.example.test/widget" '
                         'width=300 height=250></iframe>',
                         **{r"news\.example\.test/widget": ("<p>", HTML)})
        time.sleep(0.5)
        self.assertFalse(is_hidden(page, "#f"))

    def test_keeps_cross_origin_iframe_at_other_sizes(self):
        page = self.open('<iframe id=f src="https://embed.example.org/x" '
                         'width=640 height=360></iframe>',
                         **{r"embed\.example\.org": ("<p>", HTML)})
        time.sleep(0.5)
        self.assertFalse(is_hidden(page, "#f"))

    def test_keeps_known_video_embeds_at_an_ad_size(self):
        page = self.open('<iframe id=f src="https://www.youtube.com/embed/abc" '
                         'width=300 height=250></iframe>',
                         **{r"youtube\.com/embed": ("<p>", HTML)})
        time.sleep(0.5)
        self.assertFalse(is_hidden(page, "#f"))

    def test_catches_iframes_added_after_the_page_loads(self):
        page = self.open("<p>article</p>", **{r"late-network": ("<p>", HTML)})
        page.eval("""(() => {
            const f = document.createElement('iframe');
            f.id = 'late'; f.width = 728; f.height = 90;
            f.src = 'https://late-network.example.org/x';
            document.body.append(f);
        })()""")
        page.wait_for("getComputedStyle(document.querySelector('#late')).display === 'none'")

    def test_hides_a_box_holding_nothing_but_an_ad_label(self):
        page = self.open('<div id=box style="height:250px"><span>Advertisement</span></div>'
                         '<p id=body>article text</p>')
        page.wait_for("getComputedStyle(document.querySelector('#box')).display === 'none'")
        self.assertFalse(is_hidden(page, "#body"))

    def test_keeps_a_section_that_only_mentions_the_label_among_real_content(self):
        page = self.open('<div id=box><h2>Advertisement</h2>'
                         '<p>A long article about the history of advertising in newspapers, '
                         'which is real content that a reader came here for.</p></div>')
        time.sleep(0.5)
        self.assertFalse(is_hidden(page, "#box"))

    def test_collapses_the_empty_wrapper_left_behind_by_a_hidden_slot(self):
        page = self.open('<div id=wrap style="height:250px"><div id="div-gpt-ad-1"></div></div>')
        page.wait_for("getComputedStyle(document.querySelector('#wrap')).display === 'none'")

    def test_keeps_a_wrapper_that_still_has_content(self):
        page = self.open('<div id=wrap><div id="div-gpt-ad-1"></div><p>Real text here</p></div>')
        time.sleep(0.5)
        self.assertFalse(is_hidden(page, "#wrap"))


class SurrogateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = extension_browser()
        cls.browser = cls.context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)

    def open(self, html):
        page = page_with(self.browser, ARTICLE, html)
        self.addCleanup(page.close)
        return page

    def test_page_using_google_tag_still_runs_when_the_real_library_is_blocked(self):
        page = self.open("""
            <script>window.googletag = {cmd: [() => window.queued = true]};</script>
            <script src="https://securepubads.g.doubleclick.net/tag/js/gpt.js"></script>
            <script>
              googletag.cmd.push(() => {
                const slot = googletag.defineSlot('/1/x', [300, 250], 'd').addService(googletag.pubads());
                googletag.pubads().enableSingleRequest();
                googletag.enableServices();
                googletag.display('d');
                window.ran = slot ? 'yes' : 'no';
              });
            </script>""")
        self.assertEqual(page.eval("window.ran"), "yes")
        self.assertTrue(page.eval("window.queued"))

    def test_page_using_adsense_still_runs(self):
        page = self.open("""
            <script src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js"></script>
            <script>(window.adsbygoogle = window.adsbygoogle || []).push({}); window.ran = 'yes';</script>""")
        self.assertEqual(page.eval("window.ran"), "yes")

    def test_page_using_amazon_bids_gets_an_empty_answer(self):
        page = self.open("""
            <script src="https://c.amazon-adsystem.com/aax2/apstag.js"></script>
            <script>
              apstag.init({pubID: 'x'});
              window.bids = new Promise(r => apstag.fetchBids({slots: []}, r));
            </script>""")
        self.assertEqual(page.eval("window.bids"), [])


class PauseTests(unittest.TestCase):
    def test_pausing_a_site_turns_everything_off_there_and_resuming_restores_it(self):
        html = '<ins class="adsbygoogle" id=ad></ins>'
        ad_fetch = "fetch('https://ads.pubmatic.com/x').then(() => 'ok', () => 'failed')"
        with extension_browser() as browser:
            state = send_message(browser, {"type": "set-paused", "host": "news.example.test", "paused": True})
            self.assertEqual(state, {"paused": True})
            self.assertTrue(send_message(browser, {"type": "get-state", "host": "news.example.test"})["paused"])

            page = page_with(browser, ARTICLE, html)
            self.assertFalse(is_hidden(page, "#ad"))
            page.eval(ad_fetch)
            time.sleep(0.3)
            self.assertEqual(page.blocked_requests(), [])
            page.close()

            send_message(browser, {"type": "set-paused", "host": "news.example.test", "paused": False})
            page = page_with(browser, ARTICLE, html)
            self.assertTrue(is_hidden(page, "#ad"))
            page.eval(ad_fetch)
            page.wait_for_blocked("pubmatic.com")
            page.close()

    def test_pausing_one_site_leaves_others_protected(self):
        with extension_browser() as browser:
            send_message(browser, {"type": "set-paused", "host": "other.example.test", "paused": True})
            page = page_with(browser, ARTICLE, '<ins class="adsbygoogle" id=ad></ins>')
            self.assertTrue(is_hidden(page, "#ad"))
            page.close()

    def test_refuses_a_malformed_host(self):
        with extension_browser() as browser:
            result = send_message(browser, {"type": "set-paused", "host": "a/*,b", "paused": True})
            self.assertEqual(result, {"error": "bad host"})


if __name__ == "__main__":
    unittest.main()

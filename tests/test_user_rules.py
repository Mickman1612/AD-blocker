"""The pop-up, the click-to-hide picker and the rules it saves."""
import json
import time
import unittest

from tests.support import HTML, extension_browser, is_hidden, page_with, send_message

SITE = "https://shop.example.test/"
OTHER = "https://other.example.test/"
BODY = """<div id=banner style="height:90px">Buy things</div>
<div class="promo card" id=card style="height:50px">Offer</div>
<div class="promo card" id=card2 style="height:50px">Offer two</div>
<p id=article>Real article text</p>"""


def rule_host(url):
    return url.split("/")[2]


class SavedRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = extension_browser()
        cls.browser = cls.context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)

    def tearDown(self):
        send_message(self.browser, {"type": "clear-rules", "host": rule_host(SITE)})

    def open(self, url=SITE, html=BODY):
        page = page_with(self.browser, url, html)
        self.addCleanup(page.close)
        return page

    def test_saved_rule_hides_the_element_on_that_site(self):
        send_message(self.browser, {"type": "save-rule", "host": rule_host(SITE), "selector": "#banner"})
        page = self.open()
        page.wait_for("getComputedStyle(document.querySelector('#banner')).display === 'none'", timeout=3)
        self.assertFalse(is_hidden(page, "#article"))

    def test_saved_rule_does_not_apply_on_other_sites(self):
        send_message(self.browser, {"type": "save-rule", "host": rule_host(SITE), "selector": "#banner"})
        page = self.open(OTHER)
        time.sleep(0.5)
        self.assertFalse(is_hidden(page, "#banner"))

    def test_saved_rule_works_on_a_page_with_a_strict_security_policy(self):
        send_message(self.browser, {"type": "save-rule", "host": rule_host(SITE), "selector": "#banner"})
        page = self.browser.new_page()
        self.addCleanup(page.close)
        page.fixture(r"^https://shop\.example\.test/$", BODY, headers={
            **HTML, "Content-Security-Policy": "default-src 'none'"})
        page.goto(SITE)
        page.wait_for("getComputedStyle(document.querySelector('#banner')).display === 'none'", timeout=3)

    def test_clearing_rules_brings_the_element_back(self):
        send_message(self.browser, {"type": "save-rule", "host": rule_host(SITE), "selector": "#banner"})
        send_message(self.browser, {"type": "clear-rules", "host": rule_host(SITE)})
        page = self.open()
        time.sleep(0.5)
        self.assertFalse(is_hidden(page, "#banner"))

    def test_state_reports_how_many_rules_a_site_has(self):
        send_message(self.browser, {"type": "save-rule", "host": rule_host(SITE), "selector": "#a"})
        send_message(self.browser, {"type": "save-rule", "host": rule_host(SITE), "selector": "#b"})
        send_message(self.browser, {"type": "save-rule", "host": rule_host(SITE), "selector": "#a"})
        state = send_message(self.browser, {"type": "get-state", "host": rule_host(SITE)})
        self.assertEqual(state, {"paused": False, "ruleCount": 2})

    def test_refuses_a_selector_that_could_inject_styles(self):
        for bad in ("a{color:red}", "}", "<b>", "", "x" * 2000):
            with self.subTest(bad[:10]):
                result = send_message(self.browser, {"type": "save-rule", "host": rule_host(SITE), "selector": bad})
                self.assertEqual(result, {"error": "bad selector"})


class PickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = extension_browser()
        cls.browser = cls.context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)

    def tearDown(self):
        send_message(self.browser, {"type": "clear-rules", "host": rule_host(SITE)})

    def open_with_picker(self):
        page = page_with(self.browser, SITE, BODY)
        self.addCleanup(page.close)
        self.browser.cdp.send("Target.activateTarget", {"targetId": page.target_id})
        started = self.browser.service_worker_eval(f"""
            chrome.tabs.query({{url: {json.dumps(SITE)}}}).then(([tab]) =>
              chrome.scripting.executeScript({{target: {{tabId: tab.id}},
                files: ['content/isolated/picker.js']}})).then(() => true)""")
        self.assertTrue(started)
        return page

    def click(self, page, selector):
        box = page.eval(f"""(() => {{ const r = document.querySelector({json.dumps(selector)}).getBoundingClientRect();
            return {{x: r.x + r.width / 2, y: r.y + r.height / 2}}; }})()""")
        for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
            params = {"type": kind, "x": box["x"], "y": box["y"]}
            if kind != "mouseMoved":
                params.update(button="left", clickCount=1)
            page._send("Input.dispatchMouseEvent", params)

    def test_clicking_an_element_hides_it_and_saves_a_rule(self):
        page = self.open_with_picker()
        self.click(page, "#banner")
        page.wait_for("getComputedStyle(document.querySelector('#banner')).display === 'none'", timeout=3)
        state = send_message(self.browser, {"type": "get-state", "host": rule_host(SITE)})
        self.assertEqual(state["ruleCount"], 1)

    def test_rule_from_the_picker_survives_a_reload(self):
        page = self.open_with_picker()
        self.click(page, "#banner")
        page.wait_for("getComputedStyle(document.querySelector('#banner')).display === 'none'", timeout=3)
        time.sleep(0.2)
        page.reload()
        page.wait_for("getComputedStyle(document.querySelector('#banner')).display === 'none'", timeout=3)
        self.assertFalse(is_hidden(page, "#article"))

    def test_rule_targets_only_the_clicked_element_when_others_look_alike(self):
        page = self.open_with_picker()
        self.click(page, "#card")
        page.wait_for("getComputedStyle(document.querySelector('#card')).display === 'none'", timeout=3)
        self.assertFalse(is_hidden(page, "#card2"))

    def test_escape_cancels_without_saving(self):
        page = self.open_with_picker()
        page._send("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "code": "Escape",
                                              "windowsVirtualKeyCode": 27})
        page.wait_for("!document.querySelector('[data-local-ad-blocker-picker]')", timeout=3)
        self.click(page, "#banner")
        time.sleep(0.3)
        self.assertFalse(is_hidden(page, "#banner"))
        state = send_message(self.browser, {"type": "get-state", "host": rule_host(SITE)})
        self.assertEqual(state["ruleCount"], 0)

    def test_picking_does_not_trigger_the_pages_own_click(self):
        page = page_with(self.browser, SITE, '<a id=link href="#clicked" style="display:block;height:60px">Link</a>')
        self.addCleanup(page.close)
        self.browser.service_worker_eval(f"""
            chrome.tabs.query({{url: {json.dumps(SITE)}}}).then(([tab]) =>
              chrome.scripting.executeScript({{target: {{tabId: tab.id}},
                files: ['content/isolated/picker.js']}})).then(() => true)""")
        self.click(page, "#link")
        page.wait_for("getComputedStyle(document.querySelector('#link')).display === 'none'", timeout=3)
        self.assertEqual(page.eval("location.hash"), "")


class PopupTests(unittest.TestCase):
    """The pop-up page, with the active-tab lookup pointed at a chosen address."""

    @classmethod
    def setUpClass(cls):
        cls.context = extension_browser()
        cls.browser = cls.context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)

    def open_popup(self, url=SITE):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        page.add_init_script(f"""
            window.__opened = [];
            if (window.chrome && chrome.tabs) {{
              chrome.tabs.query = async () => [{{id: 12345, url: {json.dumps(url)}}}];
              chrome.tabs.reload = async () => window.__opened.push('reloaded');
            }}""")
        page.goto(f"chrome-extension://{self.browser.extension_id}/popup/popup.html")
        page.wait_for("document.body.dataset.ready === 'true'", timeout=5)
        return page

    def test_shows_the_current_site(self):
        page = self.open_popup()
        self.assertEqual(page.eval("document.getElementById('host').textContent"), "shop.example.test")

    def test_toggle_pauses_and_resumes_the_site_and_reloads_the_tab(self):
        page = self.open_popup()
        self.assertEqual(page.eval("document.getElementById('toggle').getAttribute('aria-checked')"), "true")
        page.eval("document.getElementById('toggle').click()")
        page.wait_for("document.getElementById('toggle').getAttribute('aria-checked') === 'false'", timeout=5)
        self.assertEqual(send_message(self.browser, {"type": "get-state", "host": "shop.example.test"})["paused"], True)
        page.wait_for("window.__opened.includes('reloaded')", timeout=3)
        page.eval("document.getElementById('toggle').click()")
        page.wait_for("document.getElementById('toggle').getAttribute('aria-checked') === 'true'", timeout=5)
        self.assertEqual(send_message(self.browser, {"type": "get-state", "host": "shop.example.test"})["paused"], False)

    def test_browser_pages_show_a_plain_message_and_no_controls(self):
        page = self.open_popup("edge://settings/")
        self.assertTrue(page.eval("document.getElementById('toggle').disabled"))
        self.assertTrue(page.eval("document.getElementById('pick').disabled"))
        self.assertIn("can't", page.eval("document.getElementById('host').textContent").lower())

    def test_clear_button_only_appears_when_there_are_rules(self):
        send_message(self.browser, {"type": "clear-rules", "host": "shop.example.test"})
        page = self.open_popup()
        self.assertTrue(page.eval("document.getElementById('clear').hidden"))
        send_message(self.browser, {"type": "save-rule", "host": "shop.example.test", "selector": "#x"})
        page.reload()
        page.wait_for("document.body.dataset.ready === 'true'", timeout=5)
        self.assertFalse(page.eval("document.getElementById('clear').hidden"))
        self.assertIn("1", page.eval("document.getElementById('clear').textContent"))
        send_message(self.browser, {"type": "clear-rules", "host": "shop.example.test"})


if __name__ == "__main__":
    unittest.main()

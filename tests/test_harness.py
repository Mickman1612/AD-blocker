"""The harness has to be trustworthy, because every browser test relies on it."""
import json
import pathlib
import tempfile
import unittest

from tests.harness.browser import Browser

HTML = {"Content-Type": "text/html"}


def make_blocking_extension(root: pathlib.Path) -> pathlib.Path:
    (root / "manifest.json").write_text(json.dumps({
        "manifest_version": 3,
        "name": "harness-fixture",
        "version": "1.0",
        "background": {"service_worker": "sw.js"},
        "permissions": ["declarativeNetRequest"],
        "host_permissions": ["<all_urls>"],
        "declarative_net_request": {"rule_resources": [
            {"id": "r", "enabled": True, "path": "rules.json"}]},
    }))
    (root / "sw.js").write_text("self.marker = 'alive';\n")
    (root / "rules.json").write_text(json.dumps([{
        "id": 1, "priority": 1, "action": {"type": "block"},
        "condition": {"requestDomains": ["ads.example.test"],
                      "resourceTypes": ["script", "image", "xmlhttprequest"]},
    }]))
    return root


class HarnessTest(unittest.TestCase):
    def test_fixture_is_served_on_a_fake_host(self):
        with Browser() as browser:
            page = browser.new_page()
            page.fixture(r"^https://www\.example\.test/$",
                         "<p id=x>ok</p>", headers=HTML)
            page.goto("https://www.example.test/")
            self.assertEqual(page.eval("document.getElementById('x').textContent"), "ok")

    def test_eval_awaits_promises_and_raises_page_errors(self):
        with Browser() as browser:
            page = browser.new_page()
            page.fixture(r"^https://www\.example\.test/$", "<p>", headers=HTML)
            page.goto("https://www.example.test/")
            self.assertEqual(page.eval("Promise.resolve(41 + 1)"), 42)
            with self.assertRaises(RuntimeError):
                page.eval("throw new Error('boom')")

    def test_unmatched_request_fails_instead_of_reaching_the_internet(self):
        with Browser() as browser:
            page = browser.new_page()
            page.fixture(r"^https://www\.example\.test/$", "<p>", headers=HTML)
            page.goto("https://www.example.test/")
            result = page.eval(
                "fetch('https://elsewhere.example.test/x').then(() => 'reached', () => 'failed')")
            self.assertEqual(result, "failed")

    def test_finds_the_extension_service_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            ext = make_blocking_extension(pathlib.Path(tmp))
            with Browser(extension_path=ext) as browser:
                self.assertRegex(browser.extension_id, r"^[a-p]{32}$")
                self.assertEqual(browser.service_worker_wait_for("self.marker"), "alive")

    def test_reports_requests_blocked_by_the_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            ext = make_blocking_extension(pathlib.Path(tmp))
            with Browser(extension_path=ext) as browser:
                page = browser.new_page()
                page.fixture(r"^https://www\.example\.test/$", "<p>", headers=HTML)
                page.fixture(r"^https://cdn\.example\.test/ok\.js$", "1", headers={
                    "Content-Type": "text/javascript", "Access-Control-Allow-Origin": "*"})
                page.goto("https://www.example.test/")
                page.eval("""Promise.allSettled([
                    fetch('https://ads.example.test/ad.js'),
                    fetch('https://cdn.example.test/ok.js')])""")
                page.wait_for_blocked("ads.example.test")
                blocked = page.blocked_requests()
                self.assertTrue(any("ads.example.test" in u for u in blocked), blocked)
                self.assertFalse(any("cdn.example.test" in u for u in blocked), blocked)


if __name__ == "__main__":
    unittest.main()

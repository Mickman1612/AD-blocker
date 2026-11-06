"""Proof of the core promise: the extension uses only our own files and sends nothing anywhere."""
import json
import pathlib
import re
import struct
import time
import unittest

from tests.harness.browser import Browser
from tests.support import EXTENSION, HTML, REPO, extension_browser, page_with

# Starts a connection, whatever the destination.
NETWORK_CALLS = re.compile(
    r"\bfetch\s*\(|new\s+XMLHttpRequest|\.sendBeacon\s*\(|new\s+WebSocket|new\s+EventSource"
    r"|new\s+RTCPeerConnection|\bimportScripts\s*\(|new\s+Image\s*\(")
EXTERNAL_URL = re.compile(r"(?:https?|wss?|ftp):/{2}", re.I)
# Providers we chose not to use. Their names shouldn't appear in anything we ship.
PROVIDER_NAMES = re.compile(
    r"easylist|easyprivacy|ublock|adguard|adblock\s*plus|peter\s*lowe|ghostery|fanboy|uassets", re.I)

# The only places allowed to mention these, and why.
ALLOWED_NETWORK_CALLS = {
    # Wraps calls the page itself makes. The worker bootstrap loads the page's own worker script.
    "content/main/net-hooks.js": {"fetch(", "importScripts("},
}


def strip_comments(source):
    return re.sub(r"(^|\s)//[^\n]*", r"\1", re.sub(r"/\*.*?\*/", "", source, flags=re.S))


def network_calls_in(source):
    return [match.group(0) for match in NETWORK_CALLS.finditer(strip_comments(source))]


def external_urls_in(source):
    return EXTERNAL_URL.findall(strip_comments(source))


class ScannerTests(unittest.TestCase):
    """If the scanner couldn't catch these, a clean scan would mean nothing."""

    def test_catches_each_way_of_starting_a_connection(self):
        for code in ("fetch('https://a.example')", "new XMLHttpRequest()", "navigator.sendBeacon('/x')",
                     "new WebSocket('wss://a')", "new EventSource('/x')", "importScripts('/x.js')",
                     "new Image().src = '/x'", "new RTCPeerConnection()"):
            with self.subTest(code):
                self.assertTrue(network_calls_in(code))

    def test_catches_external_addresses(self):
        for code in ("const a = 'https://a.example';", "x('http://a.example')", "x('wss://a.example')"):
            with self.subTest(code):
                self.assertTrue(external_urls_in(code))

    def test_ignores_comments(self):
        self.assertFalse(network_calls_in("// fetch('https://a.example')\n/* new WebSocket() */ const a = 1;"))


class SourceTests(unittest.TestCase):
    def sources(self, *suffixes):
        for path in EXTENSION.rglob("*"):
            if path.suffix in suffixes:
                yield path.relative_to(EXTENSION).as_posix(), path.read_text(encoding="utf-8")

    def test_extension_code_starts_no_connections_of_its_own(self):
        for name, source in self.sources(".js"):
            allowed = ALLOWED_NETWORK_CALLS.get(name, set())
            calls = [c for c in network_calls_in(source)
                     if not any(c.replace(" ", "") == a for a in allowed)]
            self.assertEqual(calls, [], name)

    def test_extension_contains_no_external_addresses(self):
        for name, source in self.sources(".js", ".html", ".css"):
            self.assertEqual(external_urls_in(source), [], name)

    def test_page_hooks_only_wrap_the_pages_own_requests(self):
        source = strip_comments((EXTENSION / "content/main/net-hooks.js").read_text(encoding="utf-8"))
        self.assertIn("nativeFetch.call(self, input, init)", source)
        self.assertEqual(len(re.findall(r"\bfetch\s*\(", source)), 1, "only the worker wrapper's own signature")
        self.assertEqual(len(re.findall(r"new\s+XMLHttpRequest", source)), 0)

    def test_style_sheets_load_nothing(self):
        for name, source in self.sources(".css"):
            self.assertNotRegex(source, r"@import|url\(", name)

    def test_nothing_shipped_comes_from_another_provider(self):
        roots = [REPO / "rules-src", EXTENSION]
        for root in roots:
            for path in root.rglob("*"):
                if path.suffix in (".js", ".json", ".txt", ".css", ".html"):
                    self.assertIsNone(PROVIDER_NAMES.search(path.read_text(encoding="utf-8")), path.name)


class ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))

    def test_extension_pages_cannot_connect_anywhere_else(self):
        policy = self.manifest["content_security_policy"]["extension_pages"]
        self.assertIn("connect-src 'self'", policy)
        self.assertIn("script-src 'self'", policy)

    def test_has_no_update_address(self):
        self.assertNotIn("update_url", self.manifest)

    def test_outside_sites_and_apps_cannot_talk_to_it(self):
        self.assertNotIn("externally_connectable", self.manifest)

    def test_asks_for_no_more_than_it_uses(self):
        self.assertEqual(set(self.manifest["permissions"]), {"declarativeNetRequest", "scripting", "storage"})

    def test_icons_are_real_images_of_the_right_size(self):
        for size, path in self.manifest["icons"].items():
            data = (EXTENSION / path).read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n", path)
            self.assertEqual(struct.unpack("!II", data[16:24]), (int(size), int(size)), path)


class RuntimeTests(unittest.TestCase):
    def test_service_worker_cannot_reach_the_network(self):
        # Real network here. The policy has to stop this before anything is sent.
        with Browser(extension_path=EXTENSION) as browser:
            browser.service_worker_wait_for("typeof chrome.scripting !== 'undefined'", timeout=15)
            result = browser.service_worker_eval(
                "fetch('https://example.org/').then(() => 'reached', (e) => 'refused: ' + e.message)")
            self.assertTrue(result.startswith("refused"), result)

    def test_pop_up_cannot_reach_the_network(self):
        with Browser(extension_path=EXTENSION) as browser:
            browser.service_worker_wait_for("typeof chrome.scripting !== 'undefined'", timeout=15)
            page = browser.open_extension_page("popup/popup.html", offline=False)
            result = page.eval("fetch('https://example.org/').then(() => 'reached', (e) => 'refused: ' + e.message)")
            self.assertTrue(result.startswith("refused"), result)
            page.close()

    def test_service_worker_sends_nothing_during_normal_use(self):
        with extension_browser() as browser:
            requests = []
            browser.cdp.on("Network.requestWillBeSent",
                           lambda params: requests.append(params["request"]["url"]),
                           browser._sw_session)
            browser.cdp.send("Network.enable", session_id=browser._sw_session)
            page = page_with(browser, "https://news.example.test/", '<ins class="adsbygoogle"></ins>')
            page.eval("fetch('https://ads.pubmatic.com/x').catch(() => {})")
            page.close()
            browser.service_worker_eval("chrome.storage.local.set({paused: []})")
            time.sleep(3)
            external = [url for url in requests if not url.startswith("chrome-extension://")]
            self.assertEqual(external, [])

    def test_saved_data_stays_in_local_storage_with_nothing_synced(self):
        with extension_browser() as browser:
            used = browser.service_worker_eval("chrome.storage.sync.get(null).then(d => Object.keys(d).length)")
            self.assertEqual(used, 0)
            source = (EXTENSION / "background.js").read_text(encoding="utf-8")
            self.assertNotIn("storage.sync", source)


if __name__ == "__main__":
    unittest.main()

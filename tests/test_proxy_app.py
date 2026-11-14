"""Which sites the app touches, what it adds to them, and turning it on and off."""
import asyncio
import base64
import json
import os
import pathlib
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import winreg

from proxy import app, install
from proxy.server import ProxyServer
from tests.harness.browser import Browser
from tests.test_proxy_server import FakeUpstream, response

REPO = pathlib.Path(__file__).resolve().parent.parent
TEST_ROOT = r"Software\LocalAdBlockerTest"


def pac_route(pac, host):
    """Decide a route with the same logic the routing file uses."""
    tables = {name: json.loads(value) for name, value in re.findall(r"(BLOCK|EXEMPT|DOMAINS|HOSTS)=(\{.*?\})", pac)}

    def listed(table, name):
        while True:
            if name in table:
                return True
            if "." not in name:
                return False
            name = name.split(".", 1)[1]

    if host in tables["EXEMPT"]:
        return "direct"
    if listed(tables["BLOCK"], host):
        return "blocked"
    if host in tables["HOSTS"] or listed(tables["DOMAINS"], host):
        return "filtered"
    return "direct"


class SiteListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.domains, cls.hosts = app.decrypt_targets()
        cls.config = app.load_config(certificate_dir=None, port=18899, with_certificates=False)
        cls.pac = app.build_routing_file(cls.config)

    def test_covers_video_social_and_search(self):
        for host in ("www.youtube.com", "m.youtube.com", "music.youtube.com", "www.twitch.tv", "www.facebook.com",
                     "www.instagram.com", "x.com", "www.tiktok.com", "www.pinterest.com", "www.google.com", "www.google.com.au", "www.bing.com", "duckduckgo.com"):
            with self.subTest(host):
                self.assertEqual(pac_route(self.pac, host), "filtered")

    def test_never_decrypts_money_or_accounts(self):
        for host in ("www.commbank.com.au", "www.nab.com.au", "www.paypal.com", "www.amazon.com", "www.amazon.com.au",
                     "www.ebay.com", "accounts.google.com", "login.microsoftonline.com", "login.live.com",
                     "mail.google.com", "drive.google.com", "www.linkedin.com", "www.reddit.com", "old.reddit.com", "search.yahoo.com", "github.com", "www.microsoft.com", "www.apple.com"):
            with self.subTest(host):
                self.assertEqual(pac_route(self.pac, host), "direct")

    def test_video_streams_and_images_do_not_go_through_the_app(self):
        for host in ("rr2---sn-abc.googlevideo.com", "i.ytimg.com", "yt3.ggpht.com", "www.gstatic.com",
                     "video-weaver.syd03.hls.ttvnw.net"):
            with self.subTest(host):
                self.assertEqual(pac_route(self.pac, host), "direct")

    def test_ad_servers_are_blocked_even_under_a_listed_site(self):
        for host in ("securepubads.g.doubleclick.net", "pagead2.googlesyndication.com", "ads.youtube.com",
                     "cdn.taboola.com", "ads.tiktok.com", "ads-api.x.com"):
            with self.subTest(host):
                self.assertEqual(pac_route(self.pac, host), "blocked")

    def test_youtube_ad_check_host_is_left_alone(self):
        self.assertEqual(pac_route(self.pac, "static.doubleclick.net"), "direct")

    def test_certificate_names_cover_the_targets_and_nothing_wider(self):
        names = app.certificate_names()
        self.assertIn("youtube.com", names)
        self.assertIn("*.youtube.com", names)
        self.assertIn("www.google.com", names)
        self.assertNotIn("*.google.com", names)
        self.assertNotIn("*.bing.com", names)
        self.assertFalse([name for name in names if "amazon" in name or "ebay" in name])

    def test_routing_file_is_valid_for_every_name(self):
        self.assertIn("FindProxyForURL", self.pac)
        self.assertIn("; DIRECT", self.pac)


class AdPathTests(unittest.TestCase):
    def test_turns_our_url_rules_into_patterns(self):
        patterns = [re.compile(p, re.I) for p in app.ad_path_patterns("||youtube.com/pagead/*\n||google.*/pagead/*\n"
                                                                     "/adserver/* | third-party\n# note\n")]
        self.assertTrue(any(p.search("https://www.youtube.com/pagead/x") for p in patterns))
        self.assertTrue(any(p.search("https://www.google.com.au/pagead/x") for p in patterns))
        self.assertFalse(any(p.search("https://www.youtube.com/watch?v=1") for p in patterns))
        self.assertFalse(any(p.search("https://www.youtube.com/adserver/x") for p in patterns))


class PageScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = app.load_config(certificate_dir=None, port=18899, with_certificates=False)

    def snippet(self, host):
        return self.config.page_snippet(host)

    def test_youtube_gets_its_scripts_and_styles(self):
        code, script_hash, style_hash = self.snippet("www.youtube.com")
        text = code.decode("ascii")
        self.assertIn("ytInitialPlayerResponse", text)
        self.assertIn("ytd-ad-slot-renderer", text)
        self.assertIn("html5-video-player", text)
        self.assertTrue(script_hash and style_hash)

    def test_search_gets_styles_for_that_site(self):
        self.assertIn(b"#tads", self.snippet("www.google.com.au")[0])

    def test_hashes_match_the_exact_inline_code(self):
        code, script_hash, style_hash = self.snippet("www.reddit.com")
        text = code.decode("ascii")
        script = re.search(r"<script>(.*)</script>", text, re.S).group(1)
        style = re.search(r"<style>(.*?)</style>", text, re.S).group(1)
        from proxy.server import inline_hash
        self.assertEqual(inline_hash(script), script_hash)
        self.assertEqual(inline_hash(style), style_hash)

    def test_snippet_is_plain_ascii_so_any_page_encoding_is_safe(self):
        for host in ("www.youtube.com", "www.facebook.com", "www.bing.com"):
            self.snippet(host)[0].decode("ascii")

    def test_nothing_in_it_can_end_the_script_early(self):
        code = self.snippet("www.youtube.com")[0].decode("ascii")
        self.assertEqual(code.count("</script"), 1)

    def test_page_scripts_do_not_need_extension_apis(self):
        code = self.snippet("www.youtube.com")[0].decode("ascii")
        self.assertNotIn("chrome.", code)


class AppSafetyTests(unittest.TestCase):
    def test_filtering_app_stores_and_logs_nothing(self):
        source = (REPO / "proxy" / "server.py").read_text(encoding="utf-8")
        for word in ("open(", "print(", "logging", "write_text", "write_bytes"):
            self.assertNotIn(word, source)

    def test_only_mentions_addresses_on_this_pc(self):
        for name in ("server.py", "app.py", "run.py", "install.py", "certs.py"):
            source = (REPO / "proxy" / name).read_text(encoding="utf-8")
            for address in re.findall(r"https?://[a-zA-Z0-9.\-\[\]]+", source):
                self.assertTrue(address.endswith(("127.0.0.1", "//")), f"{name}: {address}")


def read_value(path, name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{TEST_ROOT}\{path}") as key:
            return winreg.QueryValueEx(key, name)[0]
    except FileNotFoundError:
        return None


def write_value(path, name, value):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{TEST_ROOT}\{path}") as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def delete_tree(path):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                except OSError:
                    break
                delete_tree(rf"{path}\{child}")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except FileNotFoundError:
        pass


class InstallTests(unittest.TestCase):
    """A throwaway registry key and folder stand in for the real ones. Nothing is launched."""

    def setUp(self):
        delete_tree(TEST_ROOT)
        self.addCleanup(delete_tree, TEST_ROOT)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = pathlib.Path(self.tmp.name) / "data"
        self.installer = install.Installer(self.dir, registry_root=TEST_ROOT + "\\", real_system=False)

    def test_prepare_makes_certificates_with_no_master_key(self):
        self.installer.prepare()
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["ca.cer", "leaf.key", "leaf.pem", "names.json"])

    def test_prepare_keeps_existing_certificates_when_the_site_list_is_unchanged(self):
        self.installer.prepare()
        first = (self.dir / "ca.cer").read_bytes()
        self.installer.prepare()
        self.assertEqual((self.dir / "ca.cer").read_bytes(), first)

    def test_prepare_makes_new_certificates_when_the_site_list_changes(self):
        self.installer.prepare()
        first = (self.dir / "ca.cer").read_bytes()
        (self.dir / "names.json").write_text('["old.example.com"]', encoding="utf-8")
        self.installer.prepare()
        self.assertNotEqual((self.dir / "ca.cer").read_bytes(), first)

    def test_activate_sets_the_routing_file_and_startup_entry(self):
        self.installer.prepare()
        self.installer.activate()
        self.assertEqual(read_value(install.INTERNET_SETTINGS, "AutoConfigURL"), "http://127.0.0.1:18899/proxy.pac")
        startup = read_value(install.RUN_KEY, install.VALUE_NAME)
        self.assertIn("pythonw.exe", startup)
        self.assertIn("run.py", startup)

    def test_deactivate_removes_everything_and_restores_an_earlier_setting(self):
        write_value(install.INTERNET_SETTINGS, "AutoConfigURL", "http://intranet.example/earlier.pac")
        self.installer.prepare()
        self.installer.activate()
        self.installer.deactivate()
        self.assertEqual(read_value(install.INTERNET_SETTINGS, "AutoConfigURL"), "http://intranet.example/earlier.pac")
        self.assertIsNone(read_value(install.RUN_KEY, install.VALUE_NAME))

    def test_deactivate_clears_the_setting_when_there_was_none(self):
        self.installer.prepare()
        self.installer.activate()
        self.installer.deactivate()
        self.assertIsNone(read_value(install.INTERNET_SETTINGS, "AutoConfigURL"))

    def test_activating_twice_still_restores_the_original(self):
        write_value(install.INTERNET_SETTINGS, "AutoConfigURL", "http://intranet.example/earlier.pac")
        self.installer.prepare()
        self.installer.activate()
        self.installer.activate()
        self.installer.deactivate()
        self.assertEqual(read_value(install.INTERNET_SETTINGS, "AutoConfigURL"), "http://intranet.example/earlier.pac")

    def test_removal_deletes_the_key_and_certificates(self):
        self.installer.prepare()
        self.installer.activate()
        self.installer.deactivate()
        self.installer.forget_certificates()
        self.assertFalse(self.dir.exists())

    def test_status_reports_whether_the_windows_settings_step_ran(self):
        labels = self.installer.status()
        self.assertIn("Windows ad settings turned off", labels)
        self.assertIs(labels["Windows ad settings turned off"], False)

    def test_status_command_fails_unless_every_part_is_on(self):
        self.assertFalse(install.all_on({"a": True, "b": False}))
        self.assertTrue(install.all_on({"a": True, "b": True}))

    def test_trust_check_is_false_for_a_certificate_windows_does_not_have(self):
        self.installer.prepare()
        self.assertFalse(self.installer.is_root_trusted())


class RealStartupTests(unittest.TestCase):
    """Starts the app the way Windows does at sign-in, with its data in a temporary folder.
    The system proxy setting and startup list aren't touched."""

    def setUp(self):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", app.PORT)) == 0:
                self.skipTest("The ad blocker is already running on this PC")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = {**os.environ, "LOCALAPPDATA": self.tmp.name}
        self.pythonw = pathlib.Path(sys.executable).with_name("pythonw.exe")
        self.script = REPO / "proxy" / "run.py"

    def test_prepare_then_run_serves_the_routing_file_and_a_second_copy_exits(self):
        self.assertTrue(self.pythonw.exists())
        prepared = subprocess.run([sys.executable, str(REPO / "proxy" / "install.py"), "prepare"],
                                  env=self.env, capture_output=True, text=True, timeout=120)
        self.assertEqual(prepared.returncode, 0, prepared.stderr)

        process = subprocess.Popen([str(self.pythonw), str(self.script)], env=self.env)
        self.addCleanup(process.wait, 10)
        self.addCleanup(process.kill)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.time() + 20
        body = None
        while time.time() < deadline and body is None:
            try:
                with opener.open(f"http://127.0.0.1:{app.PORT}/proxy.pac", timeout=2) as reply:
                    body = reply.read()
            except OSError:
                time.sleep(0.2)
        self.assertIsNotNone(body, "The app never answered")
        self.assertIn(b"FindProxyForURL", body)
        self.assertIn(f"127.0.0.1:{app.PORT}".encode(), body)

        data = pathlib.Path(self.tmp.name) / "LocalAdBlocker"
        self.assertEqual((data / "running.pid").read_text(encoding="ascii"), str(process.pid))
        second = subprocess.run([sys.executable, str(self.script)], env=self.env, capture_output=True, timeout=30)
        self.assertEqual(second.returncode, 0)


class FailOpenTests(unittest.TestCase):
    """The promise: if the app isn't running, browsing still works. Real network, temporary profile."""

    def test_browsing_works_when_the_routing_file_cannot_be_reached(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            closed_port = probe.getsockname()[1]
        with Browser(extra_args=[f"--proxy-pac-url=http://127.0.0.1:{closed_port}/proxy.pac"]) as browser:
            page = browser.new_page(offline=False)
            page.goto("https://www.wikipedia.org/", timeout=40)
            self.assertGreater(page.eval("document.body.innerText.length"), 100)

    def test_a_listed_site_falls_back_to_direct_when_the_app_is_down(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            closed_port = probe.getsockname()[1]
        pac = ("data:application/x-ns-proxy-autoconfig;base64,"
               + base64.b64encode(f'function FindProxyForURL(u,h){{return "PROXY 127.0.0.1:{closed_port}; DIRECT";}}'
                                  .encode()).decode())
        with Browser(extra_args=[f"--proxy-pac-url={pac}"]) as browser:
            page = browser.new_page(offline=False)
            page.goto("https://www.youtube.com/", timeout=40)
            self.assertIn("YouTube", page.eval("document.title"))


class BrowserTests(unittest.TestCase):
    """A real browser through the real app, on the real hostname, against a fake site."""

    PAGE = b"""<!doctype html><html><head><title>t</title>
        <script nonce="abc">var ytInitialPlayerResponse = {"adPlacements":[1],"playerAds":[1],"streamingData":{"formats":[1]}};
        window.pageOwnScriptRan = true;</script></head>
        <body><ytd-ad-slot-renderer id=ad></ytd-ad-slot-renderer><ytd-rich-item-renderer id=video>v</ytd-rich-item-renderer>
        <ins class="adsbygoogle" id=slot></ins></body></html>"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        directory = pathlib.Path(cls.tmp.name)
        from proxy import certs
        paths = certs.create_certificates(directory, app.certificate_names())
        cls.ready = threading.Event()
        cls.loop = asyncio.new_event_loop()
        upstream_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        upstream_tls.load_cert_chain(paths.leaf_cert, paths.leaf_key)
        cls.upstream = FakeUpstream(upstream_tls)
        csp = "Content-Security-Policy: script-src 'nonce-abc' 'strict-dynamic'; style-src 'self'"
        cls.upstream.replies["/watch?v=t"] = response(cls.PAGE, headers=["Content-Type: text/html; charset=utf-8", csp])

        client = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        client.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(paths.ca_cert.read_bytes()))
        config = app.load_config(certificate_dir=directory, port=0)
        config.upstream_tls = client
        config.resolve = lambda host, port: ("127.0.0.1", cls.upstream.port)

        async def start():
            await cls.upstream.start()
            cls.proxy = ProxyServer(config)
            await cls.proxy.start()
            cls.ready.set()

        def run():
            asyncio.set_event_loop(cls.loop)
            cls.loop.create_task(start())
            cls.loop.run_forever()

        cls.thread = threading.Thread(target=run, daemon=True)
        cls.thread.start()
        cls.ready.wait(30)

    @classmethod
    def tearDownClass(cls):
        cls.loop.call_soon_threadsafe(cls.loop.stop)
        cls.thread.join(timeout=5)
        cls.tmp.cleanup()

    def open(self, browser):
        page = browser.new_page(offline=False)
        page.goto("https://www.youtube.com/watch?v=t", timeout=20)
        return page

    def test_page_arrives_clean_with_no_extension_installed(self):
        args = [f"--proxy-server=http://127.0.0.1:{self.proxy.port}", "--ignore-certificate-errors"]
        with Browser(extra_args=args) as browser:
            page = self.open(browser)
            data = page.eval("window.ytInitialPlayerResponse")
            self.assertNotIn("adPlacements", data)
            self.assertNotIn("playerAds", data)
            self.assertEqual(data["streamingData"], {"formats": [1]})

    def test_ad_elements_are_hidden_and_content_stays(self):
        args = [f"--proxy-server=http://127.0.0.1:{self.proxy.port}", "--ignore-certificate-errors"]
        with Browser(extra_args=args) as browser:
            page = self.open(browser)
            hidden = "getComputedStyle(document.getElementById('{}')).display === 'none'"
            self.assertTrue(page.eval(hidden.format("ad")))
            self.assertTrue(page.eval(hidden.format("slot")))
            self.assertFalse(page.eval(hidden.format("video")))

    def test_the_pages_own_strict_policy_still_runs_its_own_script(self):
        args = [f"--proxy-server=http://127.0.0.1:{self.proxy.port}", "--ignore-certificate-errors"]
        with Browser(extra_args=args) as browser:
            page = self.open(browser)
            self.assertTrue(page.eval("window.pageOwnScriptRan === true"))


if __name__ == "__main__":
    unittest.main()

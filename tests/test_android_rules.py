"""The phone's ad list, generated from the same hand-written rules as the PC version."""
import pathlib
import re
import unittest

from tools import build_rules as br

REPO = pathlib.Path(__file__).resolve().parent.parent
ASSETS = REPO / "android ad" / "app" / "assets"


class BlocklistTests(unittest.TestCase):
    def test_a_parent_domain_makes_its_subdomains_unnecessary(self):
        self.assertEqual(br.build_android_blocklist(["example.com"], ["ads.example.com", "a.b.example.com"]),
                         ["example.com"])

    def test_keeps_a_subdomain_when_its_parent_is_not_listed(self):
        self.assertEqual(br.build_android_blocklist([], ["adservice.google.com"]), ["adservice.google.com"])

    def test_output_is_sorted_with_no_duplicates(self):
        self.assertEqual(br.build_android_blocklist(["b.example.org", "a.example.org"], ["a.example.org"]),
                         ["a.example.org", "b.example.org"])

    def test_an_excluded_host_is_never_listed(self):
        self.assertEqual(br.build_android_blocklist(["static.doubleclick.net", "a.example.org"], []), ["a.example.org"])


class ShippedListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiled = br.compile_all(REPO / "rules-src", REPO / "extension" / "surrogates")
        cls.names = set(cls.compiled["android_blocklist"])

    def test_covers_the_big_networks_and_phone_makers(self):
        for name in ("doubleclick.net", "googlesyndication.com", "applovin.com", "unityads.unity3d.com",
                     "api.ad.xiaomi.com", "ads.samsung.com"):
            self.assertIn(name, self.names)

    def test_never_blocks_a_major_site_or_a_video_host(self):
        for name in ("google.com", "youtube.com", "googlevideo.com", "gstatic.com", "googleapis.com",
                     "facebook.com", "instagram.com", "tiktok.com", "spotify.com", "netflix.com",
                     "static.doubleclick.net", "imasdk.googleapis.com", "connect.facebook.net"):
            self.assertNotIn(name, self.names)

    def test_youtube_ad_check_host_is_on_the_allowlist(self):
        self.assertIn("static.doubleclick.net", self.compiled["android_allowlist"])

    def test_shipped_files_match_the_rule_sources(self):
        blocklist = (ASSETS / "blocklist.txt").read_text(encoding="ascii").split()
        allowlist = (ASSETS / "allowlist.txt").read_text(encoding="ascii").split()
        self.assertEqual(blocklist, self.compiled["android_blocklist"], "Run python tools/build_rules.py")
        self.assertEqual(allowlist, self.compiled["android_allowlist"], "Run python tools/build_rules.py")


class LocalOnlyTests(unittest.TestCase):
    """The phone app's promise: it talks to nothing except the phone's own DNS server."""

    SOURCE = REPO / "android ad" / "app" / "src"

    def code(self):
        return {path.name: path.read_text(encoding="utf-8") for path in self.SOURCE.rglob("*.java")}

    def test_starts_no_web_or_other_connections(self):
        for name, source in self.code().items():
            for word in ("HttpURLConnection", "java.net.URL", "java.net.Socket", "HttpClient", "WebView", "WebSocket"):
                self.assertNotIn(word, source, name)

    def test_only_the_filter_opens_a_network_socket(self):
        users = [name for name, source in self.code().items() if "DatagramSocket" in source]
        self.assertEqual(users, ["FilterVpnService.java"])

    def test_contains_no_outside_addresses(self):
        for name, source in self.code().items():
            self.assertNotRegex(source, r"https?://", name)
            addresses = re.findall(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", source)
            self.assertTrue(all(address.startswith("10.111.222.") for address in addresses), (name, addresses))

    def test_asks_for_no_more_permissions_than_it_needs(self):
        manifest = (REPO / "android ad" / "app" / "AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertEqual(sorted(re.findall(r'uses-permission android:name="android\.permission\.(\w+)"', manifest)), [
            "ACCESS_NETWORK_STATE", "FOREGROUND_SERVICE", "FOREGROUND_SERVICE_SYSTEM_EXEMPTED", "INTERNET",
            "RECEIVE_BOOT_COMPLETED"])

    def test_uses_no_outside_code_libraries(self):
        for name, source in self.code().items():
            for line in re.findall(r"^import (?:static )?([\w.]+);", source, re.M):
                self.assertTrue(line.startswith(("android.", "java.", "com.localadblocker.")), f"{name}: {line}")

    def test_shipped_app_exists_and_is_small(self):
        app = REPO / "android ad" / "LocalAdBlocker.apk"
        self.assertTrue(app.exists(), "Run python build.py apk")
        self.assertLess(app.stat().st_size, 1 << 20)


if __name__ == "__main__":
    unittest.main()

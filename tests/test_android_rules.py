"""The phone's ad list, generated from the same hand-written rules as the PC version."""
import pathlib
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


if __name__ == "__main__":
    unittest.main()

import json
import pathlib
import unittest

from tools import build_rules as br

REPO = pathlib.Path(__file__).resolve().parent.parent


class DomainTests(unittest.TestCase):
    def test_skips_comments_and_blank_lines(self):
        self.assertEqual(br.parse_domains("# note\n\nads.example.com  # inline\n"),
                         ["ads.example.com"])

    def test_lowercases_and_removes_duplicates(self):
        self.assertEqual(br.parse_domains("Ads.Example.com\nads.example.com\n"),
                         ["ads.example.com"])

    def test_rejects_malformed_domain_and_names_the_line(self):
        with self.assertRaisesRegex(br.RuleError, "line 2"):
            br.parse_domains("ok.example.com\nnot a domain\n")

    def test_rejects_domains_that_would_break_major_sites(self):
        for domain in ("google.com", "youtube.com", "googlevideo.com", "gstatic.com",
                       "googleapis.com", "facebook.com", "amazon.com", "twitch.tv"):
            with self.subTest(domain), self.assertRaisesRegex(br.RuleError, "protected"):
                br.parse_domains(domain)

    def test_allows_ad_subdomain_of_a_protected_domain(self):
        self.assertEqual(br.parse_domains("adservice.google.com"), ["adservice.google.com"])


class PatternTests(unittest.TestCase):
    def rule(self, line):
        return br.parse_url_patterns(line)[0]

    def test_plain_pattern_blocks_subresources_only(self):
        rule = self.rule("/pagead/*")
        self.assertEqual(rule["action"]["type"], "block")
        self.assertEqual(rule["condition"]["urlFilter"], "/pagead/*")
        self.assertNotIn("main_frame", rule["condition"]["resourceTypes"])

    def test_third_party_option(self):
        self.assertEqual(self.rule("/ads/* | third-party")["condition"]["domainType"], "thirdParty")

    def test_types_option_limits_resource_types(self):
        self.assertEqual(self.rule("/x | types=script,image")["condition"]["resourceTypes"],
                         ["script", "image"])

    def test_only_and_except_options_limit_initiators(self):
        rule = self.rule("/x | only=a.example.com,b.example.com | except=c.a.example.com")
        self.assertEqual(rule["condition"]["initiatorDomains"], ["a.example.com", "b.example.com"])
        self.assertEqual(rule["condition"]["excludedInitiatorDomains"], ["c.a.example.com"])

    def test_allow_prefix_outranks_blocking(self):
        rule = self.rule("@@||cdn.example.com/ads.css")
        self.assertEqual(rule["action"]["type"], "allow")
        self.assertGreater(rule["priority"], br.PRIORITY_BLOCK)
        self.assertEqual(rule["condition"]["urlFilter"], "||cdn.example.com/ads.css")

    def test_unknown_option_is_rejected(self):
        with self.assertRaisesRegex(br.RuleError, "line 1"):
            br.parse_url_patterns("/x | nonsense")

    def test_unknown_resource_type_is_rejected(self):
        with self.assertRaisesRegex(br.RuleError, "line 1"):
            br.parse_url_patterns("/x | types=scripty")


class SurrogateTests(unittest.TestCase):
    def test_redirects_to_local_file_and_outranks_blocking(self):
        rule = br.parse_surrogates("||ads.example.com/gpt.js -> gpt.js", {"gpt.js"})[0]
        self.assertEqual(rule["action"], {"type": "redirect",
                                          "redirect": {"extensionPath": "/surrogates/gpt.js"}})
        self.assertGreater(rule["priority"], br.PRIORITY_BLOCK)
        self.assertEqual(rule["condition"]["resourceTypes"], ["script"])

    def test_missing_surrogate_file_is_rejected(self):
        with self.assertRaisesRegex(br.RuleError, "missing.js"):
            br.parse_surrogates("||a.example.com/x.js -> missing.js", {"gpt.js"})


class NetworkRuleTests(unittest.TestCase):
    def test_merges_all_plain_domains_into_one_rule(self):
        rules = br.build_network_rules(["a.example.com", "b.example.com"], [], [])
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["condition"]["requestDomains"], ["a.example.com", "b.example.com"])

    def test_domain_rule_never_blocks_the_page_the_user_opened(self):
        rule = br.build_network_rules(["a.example.com"], [], [])[0]
        self.assertNotIn("main_frame", rule["condition"]["resourceTypes"])
        self.assertIn("sub_frame", rule["condition"]["resourceTypes"])

    def test_every_rule_gets_a_unique_positive_id(self):
        patterns = br.parse_url_patterns("/a\n/b\n")
        surrogates = br.parse_surrogates("||x.example.com/y.js -> y.js", {"y.js"})
        rules = br.build_network_rules(["a.example.com"], patterns, surrogates)
        ids = [r["id"] for r in rules]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(i > 0 for i in ids))


class SelectorTests(unittest.TestCase):
    def test_keeps_id_selectors_and_skips_bang_comments(self):
        self.assertEqual(br.parse_selectors("! note\n\n#ad-box\n.promo\n"), ["#ad-box", ".promo"])

    def test_rejects_rule_injection(self):
        for bad in (".a{color:red}", ".a}", "<script>"):
            with self.subTest(bad), self.assertRaisesRegex(br.RuleError, "line 1"):
                br.parse_selectors(bad)

    def test_css_has_one_rule_per_selector_so_a_bad_one_cannot_kill_the_rest(self):
        css = br.build_css(["#a", ".b"])
        self.assertEqual(css.strip().split("\n"),
                         ["#a{display:none!important}", ".b{display:none!important}"])


class SiteTableTests(unittest.TestCase):
    SITE = {"id": "demo", "matches": ["*://*.example.com/*"]}

    def test_accepts_valid_table(self):
        self.assertEqual(br.validate_sites([self.SITE], {"generic"})[0]["id"], "demo")

    def test_rejects_duplicate_ids(self):
        with self.assertRaisesRegex(br.RuleError, "duplicate"):
            br.validate_sites([self.SITE, self.SITE], set())

    def test_rejects_bad_match_pattern(self):
        with self.assertRaisesRegex(br.RuleError, "match pattern"):
            br.validate_sites([{"id": "x", "matches": ["example.com"]}], set())

    def test_rejects_css_with_no_source_file(self):
        with self.assertRaisesRegex(br.RuleError, "nope"):
            br.validate_sites([{"id": "x", "matches": ["*://*.example.com/*"], "css": "nope"}], set())


class RealRulesTests(unittest.TestCase):
    """Compile the rules that actually ship."""

    @classmethod
    def setUpClass(cls):
        cls.out = br.compile_all(REPO / "rules-src", REPO / "extension" / "surrogates")

    def test_ships_within_chromium_limits(self):
        self.assertLess(len(self.out["network"]), 30000)

    def test_rule_ids_are_unique(self):
        ids = [r["id"] for r in self.out["network"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_blocks_the_biggest_ad_networks(self):
        domains = self.out["network"][0]["condition"]["requestDomains"]
        for domain in ("doubleclick.net", "googlesyndication.com", "adnxs.com",
                       "amazon-adsystem.com", "taboola.com", "outbrain.com", "criteo.com"):
            self.assertIn(domain, domains)

    def test_generic_css_exists(self):
        self.assertIn("generic", self.out["css"])

    def test_generated_output_is_json_serialisable(self):
        json.dumps(self.out["network"])


if __name__ == "__main__":
    unittest.main()

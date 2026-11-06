"""The PC-wide layer: the hosts list, and the scripts the user runs to turn it on and off."""
import json
import pathlib
import subprocess
import tempfile
import unittest
import winreg

from tools import build_rules as br

REPO = pathlib.Path(__file__).resolve().parent.parent
PC_WIDE = REPO / "pc-wide"
HOSTS_SCRIPT = PC_WIDE / "hosts.ps1"
SETTINGS_SCRIPT = PC_WIDE / "windows-ads.ps1"
BEGIN = b"# BEGIN Local Ad Blocker"
END = b"# END Local Ad Blocker"
TEST_ROOT = r"Software\LocalAdBlockerTest"


def powershell(script, *args):
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args],
        capture_output=True, text=True, timeout=120)


class HostnameListTests(unittest.TestCase):
    def test_keeps_valid_names_and_skips_comments(self):
        self.assertEqual(br.parse_hostnames("# note\nads.example.com  # why\n\nAds.Example.com\n"),
                         ["ads.example.com"])

    def test_rejects_a_malformed_name_and_names_the_line(self):
        with self.assertRaisesRegex(br.RuleError, "line 2"):
            br.parse_hostnames("ok.example.com\nnot a host\n")

    def test_rejects_hosts_that_would_break_major_sites(self):
        for name in ("www.google.com", "www.youtube.com", "www.google.com.au", "connect.facebook.net",
                     "google.com", "youtube.com"):
            with self.subTest(name), self.assertRaises(br.RuleError):
                br.parse_hostnames(name)

    def test_rejects_the_host_youtube_uses_for_its_ad_check(self):
        with self.assertRaisesRegex(br.RuleError, "static.doubleclick.net"):
            br.parse_hostnames("static.doubleclick.net")


class HostsBlockTests(unittest.TestCase):
    def block(self, domains=("ads.example.com",), hostnames=()):
        return br.build_hosts_block(list(domains), list(hostnames))

    def lines(self, text):
        return [line for line in text.splitlines() if line and not line.startswith("#")]

    def test_is_wrapped_in_markers(self):
        lines = self.block().splitlines()
        self.assertEqual(lines[0], BEGIN.decode())
        self.assertEqual(lines[-1], END.decode())

    def test_points_names_nowhere_on_both_ip_versions(self):
        lines = self.lines(self.block())
        self.assertIn("0.0.0.0 ads.example.com", lines)
        self.assertIn(":: ads.example.com", lines)

    def test_adds_www_for_a_bare_domain_only(self):
        names = self.block(["example.com", "ads.example.org"]).split()
        self.assertIn("www.example.com", names)
        self.assertNotIn("www.ads.example.org", names)

    def test_windows_limit_of_names_per_line_is_respected(self):
        hostnames = [f"h{i}.example.com" for i in range(40)]
        for line in self.lines(self.block([], hostnames)):
            self.assertLessEqual(len(line.split()) - 1, br.HOSTS_NAMES_PER_LINE)

    def test_each_name_appears_once_per_ip_version(self):
        names = self.block(["a.example.com"], ["a.example.com", "b.example.com"]).split()
        self.assertEqual(names.count("a.example.com"), 2)

    def test_real_list_covers_what_real_pages_use_and_spares_what_it_must(self):
        compiled = br.compile_all(REPO / "rules-src", REPO / "extension" / "surrogates")
        names = set(compiled["hosts_block"].split())
        for name in ("doubleclick.net", "securepubads.g.doubleclick.net", "pagead2.googlesyndication.com",
                     "ib.adnxs.com", "cdn.taboola.com", "aax.amazon-adsystem.com", "www.googleadservices.com"):
            self.assertIn(name, names)
        for name in ("static.doubleclick.net", "www.google.com", "www.youtube.com", "googlevideo.com",
                     "imasdk.googleapis.com", "connect.facebook.net"):
            self.assertNotIn(name, names)


class ShippedListTests(unittest.TestCase):
    def test_shipped_list_matches_the_rule_sources(self):
        compiled = br.compile_all(REPO / "rules-src", REPO / "extension" / "surrogates")
        self.assertEqual((PC_WIDE / "hosts-block.txt").read_text(encoding="ascii"), compiled["hosts_block"],
                         "Run python tools/build_rules.py")

    def test_shipped_list_is_small_enough_not_to_slow_windows_name_lookups(self):
        self.assertLess(len((PC_WIDE / "hosts-block.txt").read_bytes()), 100_000)


class HostsScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.hosts = pathlib.Path(self.tmp.name) / "hosts"

    def run_script(self, *args):
        result = powershell(HOSTS_SCRIPT, "-HostsPath", str(self.hosts), "-NoFlush",
                            "-BackupPath", str(self.hosts) + ".original", *args)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_turning_on_adds_the_block_and_keeps_existing_entries(self):
        self.hosts.write_bytes(b"# my notes\r\n127.0.0.1 myserver\r\n")
        self.run_script()
        data = self.hosts.read_bytes()
        self.assertTrue(data.startswith(b"# my notes\r\n127.0.0.1 myserver\r\n"))
        self.assertIn(BEGIN, data)
        self.assertIn(b"0.0.0.0", data)

    def test_block_uses_windows_line_endings(self):
        self.hosts.write_bytes(b"# x\r\n")
        self.run_script()
        data = self.hosts.read_bytes()
        self.assertEqual(data.count(b"\n"), data.count(b"\r\n"))

    def test_running_it_twice_does_not_duplicate_the_block(self):
        self.hosts.write_bytes(b"# x\r\n")
        self.run_script()
        first = self.hosts.read_bytes()
        self.run_script()
        self.assertEqual(self.hosts.read_bytes(), first)

    def test_turning_off_restores_the_file_exactly(self):
        for original in (b"# notes\r\n127.0.0.1 myserver\r\n", b"# no newline at end", b"",
                         b"# caf\xe9 in a legacy encoding\r\n"):
            with self.subTest(original):
                self.hosts.write_bytes(original)
                self.run_script()
                self.run_script("-Off")
                self.assertEqual(self.hosts.read_bytes(), original)

    def test_turning_off_keeps_entries_added_while_it_was_on(self):
        self.hosts.write_bytes(b"# x\r\n")
        self.run_script()
        with self.hosts.open("ab") as file:
            file.write(b"127.0.0.1 added-later\r\n")
        self.run_script("-Off")
        self.assertEqual(self.hosts.read_bytes(), b"# x\r\n127.0.0.1 added-later\r\n")

    def test_turning_off_when_not_on_changes_nothing(self):
        self.hosts.write_bytes(b"# x\r\n")
        self.run_script("-Off")
        self.assertEqual(self.hosts.read_bytes(), b"# x\r\n")

    def test_keeps_a_backup_of_the_original_and_does_not_overwrite_it(self):
        self.hosts.write_bytes(b"# first\r\n")
        self.run_script()
        self.run_script()
        self.assertEqual(pathlib.Path(str(self.hosts) + ".original").read_bytes(), b"# first\r\n")

    def test_failure_is_reported_and_leaves_the_file_alone(self):
        self.hosts.write_bytes(b"# x\r\n")
        self.hosts.chmod(0o444)
        self.addCleanup(self.hosts.chmod, 0o666)
        result = powershell(HOSTS_SCRIPT, "-HostsPath", str(self.hosts), "-NoFlush",
                            "-BackupPath", str(self.hosts) + ".original")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.hosts.read_bytes(), b"# x\r\n")


def read_value(subkey, name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{TEST_ROOT}\{subkey}") as key:
            return winreg.QueryValueEx(key, name)[0]
    except FileNotFoundError:
        return None


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


class WindowsSettingsScriptTests(unittest.TestCase):
    """Runs under a throwaway registry key, so no real Windows setting changes."""

    CDM = r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager"
    ADVANCED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"

    def setUp(self):
        delete_tree(TEST_ROOT)
        self.addCleanup(delete_tree, TEST_ROOT)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.backup = pathlib.Path(self.tmp.name) / "backup.json"

    def run_script(self, *args):
        result = powershell(SETTINGS_SCRIPT, "-Root", rf"HKCU:\{TEST_ROOT}", "-BackupPath", str(self.backup), *args)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def set_value(self, subkey, name, value):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{TEST_ROOT}\{subkey}") as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)

    def test_turns_off_windows_ad_settings(self):
        self.run_script()
        self.assertEqual(read_value(self.CDM, "SubscribedContent-338388Enabled"), 0)
        self.assertEqual(read_value(self.CDM, "SilentInstalledAppsEnabled"), 0)
        self.assertEqual(read_value(self.ADVANCED, "ShowSyncProviderNotifications"), 0)
        self.assertEqual(read_value(r"Software\Microsoft\Windows\CurrentVersion\AdvertisingInfo", "Enabled"), 0)

    def test_undo_restores_earlier_values(self):
        self.set_value(self.CDM, "SubscribedContent-338388Enabled", 1)
        self.run_script()
        self.run_script("-Undo")
        self.assertEqual(read_value(self.CDM, "SubscribedContent-338388Enabled"), 1)

    def test_undo_removes_values_that_did_not_exist_before(self):
        self.run_script()
        self.run_script("-Undo")
        self.assertIsNone(read_value(self.CDM, "SilentInstalledAppsEnabled"))

    def test_running_it_twice_still_undoes_to_the_original(self):
        self.set_value(self.CDM, "SubscribedContent-338388Enabled", 1)
        self.run_script()
        self.run_script()
        self.run_script("-Undo")
        self.assertEqual(read_value(self.CDM, "SubscribedContent-338388Enabled"), 1)

    def test_backup_lists_what_was_changed(self):
        self.run_script()
        entries = json.loads(self.backup.read_text(encoding="utf-8-sig"))
        self.assertTrue(any(e["Name"] == "SilentInstalledAppsEnabled" for e in entries))

    def test_undo_without_a_backup_changes_nothing_and_says_so(self):
        result = powershell(SETTINGS_SCRIPT, "-Root", rf"HKCU:\{TEST_ROOT}", "-BackupPath", str(self.backup), "-Undo")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("nothing to undo", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()

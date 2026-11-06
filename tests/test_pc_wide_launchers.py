"""The double-click files. These never elevate or touch real settings: a copy runs with the
elevation swapped for printing, in a folder without the scripts, so only quoting is exercised."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
ON = REPO / "pc-wide" / "Turn on PC-wide blocking.cmd"
OFF = REPO / "pc-wide" / "Turn off PC-wide blocking.cmd"
LOAD = REPO / "Load extension in browsers.cmd"
GUIDE = REPO / "tools" / "load-extension.ps1"
ELEVATE = "Start-Process powershell -Verb RunAs -Wait -ArgumentList"


class LauncherTests(unittest.TestCase):
    def test_use_windows_line_endings(self):
        for path in (ON, OFF, LOAD):
            data = path.read_bytes()
            self.assertEqual(data.count(b"\n"), data.count(b"\r\n"), path.name)

    def test_only_the_hosts_step_asks_for_administrator_rights(self):
        for path in (ON, OFF):
            elevated = [line for line in path.read_text(encoding="ascii").splitlines() if "RunAs" in line]
            self.assertEqual(len(elevated), 1, path.name)
            self.assertIn("hosts.ps1", elevated[0])

    def elevated_arguments(self, launcher):
        """The arguments the elevated PowerShell would get when run from a folder with a space."""
        with tempfile.TemporaryDirectory(prefix="adb launcher ") as tmp:
            copy = pathlib.Path(tmp) / "launcher.cmd"
            text = launcher.read_text(encoding="ascii").replace(ELEVATE, "Write-Output").replace("pause", "rem")
            copy.write_bytes(text.encode("ascii"))
            result = subprocess.run(["cmd", "/c", str(copy)], capture_output=True, text=True, timeout=60)
            return result.stdout, tmp

    def test_turn_on_passes_the_script_path_intact(self):
        output, folder = self.elevated_arguments(ON)
        self.assertIn(f'-File "{folder}\\hosts.ps1"', output)

    def test_turn_off_passes_the_off_switch(self):
        output, folder = self.elevated_arguments(OFF)
        self.assertIn(f'-File "{folder}\\hosts.ps1" -Off', output)

    def test_scripts_the_launchers_call_exist(self):
        for name in ("hosts.ps1", "windows-ads.ps1", "hosts-block.txt"):
            self.assertTrue((REPO / "pc-wide" / name).exists(), name)

    def test_load_helper_runs_the_guided_script(self):
        self.assertIn('"%~dp0tools\\load-extension.ps1"', LOAD.read_text(encoding="ascii"))
        self.assertTrue(GUIDE.exists())


class GuidedLoadTests(unittest.TestCase):
    """Only the read-only status check runs here. It never opens a browser or touches the clipboard."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.edge = pathlib.Path(self.tmp.name) / "edge"
        self.chrome = pathlib.Path(self.tmp.name) / "chrome"
        self.edge.mkdir()
        self.chrome.mkdir()

    def status(self):
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(GUIDE), "-Status",
             "-EdgeProfile", str(self.edge), "-ChromeProfile", str(self.chrome)],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_reports_not_loaded_when_settings_do_not_mention_our_folder(self):
        (self.edge / "Secure Preferences").write_text('{"extensions":{"settings":{}}}', encoding="utf-8")
        output = self.status()
        self.assertIn("Edge: not loaded", output)
        self.assertIn("Chrome: not loaded", output)

    def test_reports_loaded_for_only_the_browser_that_has_it(self):
        (self.chrome / "Secure Preferences").write_text(
            '{"extensions":{"settings":{"x":{"path":"C:\\\\Ad blocker\\\\extension"}}}}', encoding="utf-8")
        output = self.status()
        self.assertIn("Chrome: loaded", output)
        self.assertIn("Edge: not loaded", output)

    def test_never_relies_on_a_browser_opening_its_extensions_page_from_a_command(self):
        source = GUIDE.read_text(encoding="utf-8")
        for line in source.splitlines():
            if "Start-Process" in line:
                self.assertNotIn("Address", line)
                self.assertNotIn("://extensions", line)

    def test_copies_the_page_address_and_the_folder_for_the_user_to_paste(self):
        source = GUIDE.read_text(encoding="utf-8")
        self.assertIn("Set-Clipboard $browser.Address", source)
        self.assertIn("Set-Clipboard $Folder", source)
        self.assertIn("chrome://extensions", source)
        self.assertIn("edge://extensions", source)


if __name__ == "__main__":
    unittest.main()

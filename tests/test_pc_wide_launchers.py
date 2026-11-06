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

    def test_load_helper_points_at_the_extension_folder(self):
        text = LOAD.read_text(encoding="ascii")
        self.assertIn("%~dp0extension", text)
        self.assertIn("chrome://extensions", text)
        self.assertIn("edge://extensions", text)
        self.assertTrue((REPO / "extension" / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()

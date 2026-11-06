"""The per-user part of turning the ad blocker on and off. The double-click files call this.

Usage: python install.py prepare | activate | deactivate | forget | status
"""
import ctypes
import json
import pathlib
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
import winreg

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from proxy import app, certs  # noqa: E402

INTERNET_SETTINGS = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "LocalAdBlocker"
HOSTS_FILE = pathlib.Path(r"C:\Windows\System32\drivers\etc\hosts")
HEALTH_WAIT_SECONDS = 20
WINDOWS_SETTINGS_BACKUP = pathlib.Path(__file__).resolve().parent.parent / "pc-wide" / "windows-settings.backup.json"


def all_on(checks):
    return all(checks.values())


class Installer:
    def __init__(self, directory=None, registry_root="", real_system=True):
        self.dir = pathlib.Path(directory or app.data_dir())
        self.root = registry_root
        self.real = real_system
        self.paths = certs.paths_in(self.dir)
        self.windows_backup = WINDOWS_SETTINGS_BACKUP if real_system else self.dir / "windows-settings.backup.json"
        self.port = app.PORT

    # --- Registry helpers ---

    def _read(self, path, name):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.root + path) as key:
                return winreg.QueryValueEx(key, name)[0]
        except FileNotFoundError:
            return None

    def _write(self, path, name, value):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.root + path) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    def _delete(self, path, name):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.root + path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass

    # --- Steps ---

    def prepare(self):
        """Make certificates, unless suitable ones already exist."""
        self.dir.mkdir(parents=True, exist_ok=True)
        names = app.certificate_names()
        record = self.dir / "names.json"
        current = json.loads(record.read_text(encoding="utf-8")) if record.exists() else None
        if current != names or not self.paths.ca_cert.exists():
            certs.create_certificates(self.dir, names)
            record.write_text(json.dumps(names), encoding="utf-8")

    def is_root_trusted(self):
        if not self.paths.ca_cert.exists():
            return False
        ours = self.paths.ca_cert.read_bytes()
        return any(certificate == ours for certificate, _, _ in ssl.enum_certificates("ROOT"))

    def _proxy_url(self):
        return f"http://127.0.0.1:{self.port}/proxy.pac"

    def activate(self):
        previous = self.dir / "previous-proxy.json"
        if not previous.exists():  # Only the first run sees the user's own setting.
            previous.write_text(json.dumps({"AutoConfigURL": self._read(INTERNET_SETTINGS, "AutoConfigURL")}),
                                encoding="utf-8")
        python = pathlib.Path(sys.executable).with_name("pythonw.exe")
        script = pathlib.Path(__file__).with_name("run.py")
        self._write(RUN_KEY, VALUE_NAME, f'"{python}" "{script}"')
        if self.real:
            self._stop_app()  # An older copy would keep the port and its old certificate.
            subprocess.Popen([str(python), str(script)], close_fds=True,
                             creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
            if not self._wait_until_running():
                return False
        # Only now, so browsing never points at something that isn't running.
        self._write(INTERNET_SETTINGS, "AutoConfigURL", self._proxy_url())
        self._notify()
        return True

    def deactivate(self):
        previous = self.dir / "previous-proxy.json"
        original = json.loads(previous.read_text(encoding="utf-8"))["AutoConfigURL"] if previous.exists() else None
        if original:
            self._write(INTERNET_SETTINGS, "AutoConfigURL", original)
        elif self._read(INTERNET_SETTINGS, "AutoConfigURL") == self._proxy_url():
            self._delete(INTERNET_SETTINGS, "AutoConfigURL")
        self._delete(RUN_KEY, VALUE_NAME)
        previous.unlink(missing_ok=True)
        self._notify()
        if self.real:
            self._stop_app()

    def forget_certificates(self):
        if self.dir.exists():
            shutil.rmtree(self.dir, ignore_errors=True)

    # --- The running app ---

    def _notify(self):
        if not self.real:
            return
        settings_changed, refresh = 39, 37
        wininet = ctypes.windll.wininet
        wininet.InternetSetOptionW(None, settings_changed, None, 0)
        wininet.InternetSetOptionW(None, refresh, None, 0)

    def is_running(self):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(f"http://127.0.0.1:{self.port}/healthz", timeout=2) as reply:
                return reply.read() == b"Local Ad Blocker"
        except (urllib.error.URLError, OSError):
            return False

    def _wait_until_running(self):
        deadline = time.time() + HEALTH_WAIT_SECONDS
        while time.time() < deadline:
            if self.is_running():
                return True
            time.sleep(0.5)
        return False

    def _stop_app(self):
        record = self.dir / "running.pid"
        if not record.exists():
            return
        pid = record.read_text(encoding="ascii").strip()
        listing = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                                 capture_output=True, text=True, timeout=30).stdout.lower()
        if "pythonw" in listing:  # Never stop a different program that reused this number.
            subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, timeout=30)
        record.unlink(missing_ok=True)

    def status(self):
        hosts = "BEGIN Local Ad Blocker" in HOSTS_FILE.read_text(encoding="latin-1")
        checks = {
            "Blocking ad servers for every app": hosts,
            "Certificate installed": self.is_root_trusted(),
            "Filtering app running": self.is_running(),
            "Starts automatically with your PC": self._read(RUN_KEY, VALUE_NAME) is not None,
            "Browsers using the filtering app": self._read(INTERNET_SETTINGS, "AutoConfigURL") == self._proxy_url(),
            "Windows ad settings turned off": self.windows_backup.exists(),
        }
        return checks


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    installer = Installer()
    if command == "prepare":
        installer.prepare()
    elif command == "activate":
        if not installer.is_root_trusted():
            print("Windows permission wasn't given, so the filtering app wasn't turned on.")
            return 3
        if not installer.activate():
            print("The filtering app didn't start. Browsing is unchanged.")
            return 4
    elif command == "deactivate":
        installer.deactivate()
    elif command == "forget":
        installer.forget_certificates()
    elif command == "status":
        checks = installer.status()
        for label, passed in checks.items():
            print(f"  [{'OK' if passed else '--'}] {label}")
        return 0 if all_on(checks) else 1
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Drive real Edge with a throwaway profile. The user's own profiles are never touched."""
import base64
import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import threading
import time

from .cdp import Cdp

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
BLOCKED_BY_CLIENT = "net::ERR_BLOCKED_BY_CLIENT"


class Browser:
    def __init__(self, extension_path=None, headless=True, extra_args=()):
        self.extension_path = pathlib.Path(extension_path) if extension_path else None
        self.headless = headless
        self.extra_args = list(extra_args)
        self.extension_id = None
        self.cdp = None
        self._proc = None
        self._profile = None
        self._sw_session = None
        self._sw_url_suffix = None

    def __enter__(self):
        self._profile = tempfile.mkdtemp(prefix="adb_test_")
        args = [
            EDGE, f"--user-data-dir={self._profile}", "--remote-debugging-port=0",
            "--no-first-run", "--no-default-browser-check", "--disable-sync",
            "--disable-component-update", "--disable-background-networking",
            "--autoplay-policy=no-user-gesture-required", *self.extra_args,
        ]
        if self.headless:
            args.append("--headless=new")
        if self.extension_path:
            args.append(f"--load-extension={self.extension_path}")
        args.append("about:blank")
        self._proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            self.cdp = Cdp(self._read_debugger_url())
            if self.extension_path:
                self._attach_service_worker()
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_):
        if self.cdp:
            try:
                self.cdp.send("Browser.close", timeout=5)
            except Exception:
                pass
            self.cdp.close()
        if self._proc:
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                subprocess.run(["taskkill", "/PID", str(self._proc.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._proc.wait(timeout=5)
        for _attempt in range(10):
            shutil.rmtree(self._profile, ignore_errors=True)
            if not pathlib.Path(self._profile).exists():
                break
            time.sleep(0.5)

    def _read_debugger_url(self):
        port_file = pathlib.Path(self._profile) / "DevToolsActivePort"
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                lines = port_file.read_text().split("\n")
                if len(lines) >= 2 and lines[1].strip():
                    return f"ws://127.0.0.1:{lines[0].strip()}{lines[1].strip()}"
            except OSError:  # Not written yet, or the browser is still holding it open.
                pass
            time.sleep(0.1)
        raise TimeoutError("Edge did not open a debugging port")

    def _attach_service_worker(self):
        manifest = json.loads((self.extension_path / "manifest.json").read_text(encoding="utf-8"))
        self._sw_url_suffix = "/" + manifest["background"]["service_worker"]
        deadline = time.time() + 20
        while time.time() < deadline:
            targets = self.cdp.send("Target.getTargets", {"filter": [{"type": "service_worker"}]})
            for info in targets["targetInfos"]:
                url = info["url"]
                if url.startswith("chrome-extension://") and url.endswith(self._sw_url_suffix):
                    self.extension_id = url.split("/")[2]
                    attached = self.cdp.send("Target.attachToTarget",
                                             {"targetId": info["targetId"], "flatten": True})
                    self._sw_session = attached["sessionId"]
                    self.cdp.send("Runtime.enable", session_id=self._sw_session)
                    return
            time.sleep(0.2)
        raise TimeoutError("The extension's service worker never started")

    def service_worker_eval(self, expression, timeout=30):
        return _evaluate(self.cdp, self._sw_session, expression, timeout)

    def service_worker_wait_for(self, expression, timeout=10):
        """The worker target appears before its script has finished running, so poll."""
        deadline = time.time() + timeout
        last_error = None
        while True:
            try:
                value = self.service_worker_eval(expression)
                if value:
                    return value
            except RuntimeError as error:  # Extension APIs appear shortly after the target does.
                last_error = error
            if time.time() > deadline:
                raise TimeoutError(f"Worker never satisfied: {expression} ({last_error})")
            time.sleep(0.05)

    def reattach_service_worker(self):
        """Call after something restarted the worker, such as chrome.runtime.reload()."""
        self._attach_service_worker()

    def new_page(self, offline=True):
        target = self.cdp.send("Target.createTarget", {"url": "about:blank"})
        attached = self.cdp.send("Target.attachToTarget",
                                 {"targetId": target["targetId"], "flatten": True})
        return Page(self.cdp, target["targetId"], attached["sessionId"], offline)

    def open_extension_page(self, path, offline=True):
        """Open a page inside the extension, such as popup/popup.html."""
        page = self.new_page(offline=offline)
        page.goto(f"chrome-extension://{self.extension_id}/{path}")
        return page


class Page:
    def __init__(self, cdp, target_id, session_id, offline):
        self.cdp = cdp
        self.target_id = target_id
        self.session_id = session_id
        self.offline = offline
        self._fixtures = []
        self._requests = {}
        self._failed = {}
        self._loaded = threading.Event()
        cdp.on("Page.loadEventFired", lambda _: self._loaded.set(), session_id)
        cdp.on("Network.requestWillBeSent", self._on_request, session_id)
        cdp.on("Network.loadingFailed", self._on_failed, session_id)
        self._send("Page.enable")
        self._send("Runtime.enable")
        self._send("Network.enable")
        if offline:
            cdp.on("Fetch.requestPaused", self._on_paused, session_id)
            self._send("Fetch.enable", {"patterns": [{"urlPattern": "*"}]})

    def _send(self, method, params=None, timeout=30):
        return self.cdp.send(method, params, self.session_id, timeout)

    def fixture(self, url_regex, body, status=200, headers=None):
        """Answer matching requests with this body. The first matching fixture wins."""
        data = body.encode("utf-8") if isinstance(body, str) else body
        self._fixtures.append((re.compile(url_regex), data, status, headers or {}))

    def _on_paused(self, params):
        try:
            self._answer_paused(params)
        except RuntimeError as error:
            closed = ("Session with given id not found", "connection closed")
            if not any(reason in str(error) for reason in closed):  # The page or browser has gone.
                raise

    def _answer_paused(self, params):
        url = params["request"]["url"]
        for pattern, data, status, headers in self._fixtures:
            if pattern.search(url):
                self._send("Fetch.fulfillRequest", {
                    "requestId": params["requestId"],
                    "responseCode": status,
                    "responseHeaders": [{"name": k, "value": v} for k, v in headers.items()],
                    "body": base64.b64encode(data).decode(),
                })
                return
        if url.startswith("chrome-extension://") or url.startswith("data:"):
            self._send("Fetch.continueRequest", {"requestId": params["requestId"]})
            return
        self._send("Fetch.failRequest", {"requestId": params["requestId"],
                                         "errorReason": "InternetDisconnected"})

    def _on_request(self, params):
        self._requests[params["requestId"]] = params["request"]

    def _on_failed(self, params):
        self._failed[params["requestId"]] = params.get("errorText", "")

    def requests(self):
        return [r["url"] for r in list(self._requests.values())]

    def request_details(self):
        return list(self._requests.values())

    def blocked_requests(self):
        return [self._requests[i]["url"] for i, error in list(self._failed.items())
                if error == BLOCKED_BY_CLIENT and i in self._requests]

    def add_init_script(self, source):
        self._send("Page.addScriptToEvaluateOnNewDocument", {"source": source})

    def goto(self, url, timeout=30):
        self._loaded.clear()
        result = self._send("Page.navigate", {"url": url})
        if result.get("errorText"):
            raise RuntimeError(f"Navigation to {url} failed: {result['errorText']}")
        if not self._loaded.wait(timeout):
            raise TimeoutError(f"{url} did not finish loading within {timeout}s")

    def reload(self, timeout=30):
        self._loaded.clear()
        self._send("Page.reload")
        if not self._loaded.wait(timeout):
            raise TimeoutError(f"Reload did not finish within {timeout}s")

    def eval(self, expression, timeout=30):
        return _evaluate(self.cdp, self.session_id, expression, timeout)

    def wait_for(self, expression, timeout=10, interval=0.1):
        deadline = time.time() + timeout
        while True:
            value = self.eval(expression)
            if value:
                return value
            if time.time() > deadline:
                raise TimeoutError(f"Never became true: {expression}")
            time.sleep(interval)

    def wait_for_blocked(self, substring, timeout=5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if any(substring in url for url in self.blocked_requests()):
                return
            time.sleep(0.05)
        raise TimeoutError(f"No blocked request containing {substring}: {self.requests()}")

    def close(self):
        self.cdp.send("Target.closeTarget", {"targetId": self.target_id})


def _evaluate(cdp, session_id, expression, timeout):
    result = cdp.send("Runtime.evaluate", {
        "expression": expression, "awaitPromise": True, "returnByValue": True,
    }, session_id, timeout)
    if "exceptionDetails" in result:
        details = result["exceptionDetails"]
        description = details.get("exception", {}).get("description") or details.get("text")
        raise RuntimeError(f"Page error: {description}")
    return result["result"].get("value")

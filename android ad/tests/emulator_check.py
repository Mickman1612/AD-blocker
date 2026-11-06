"""Test the real app on a simulated phone. Everything stays in .tools/, and your own phone isn't involved.

Run: python tests/emulator_check.py
Checks: blocked names fail, normal names resolve, the filter comes back after a restart, and turning it
off restores ad lookups.
"""
import os
import pathlib
import re
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent.parent
REAL_TOOLS = HERE / ".tools"
# The emulator breaks on spaces in its path, so it reaches the tools through a link in the temp folder.
TOOLS = pathlib.Path(os.environ["TEMP"]) / "adb_android_tools"
if not TOOLS.exists():
    subprocess.run(["cmd", "/c", "mklink", "/J", str(TOOLS), str(REAL_TOOLS)], check=True, capture_output=True)
SDK = TOOLS / "sdk"
HOME = TOOLS / "avd-home"
ADB = SDK / "platform-tools" / "adb.exe"
EMULATOR = SDK / "emulator" / "emulator.exe"
APK = HERE / "LocalAdBlocker.apk"
AVD = "adblocker_test"
PACKAGE = "com.localadblocker"
IMAGE = "system-images;android-36;google_apis;x86_64"
# Fresh names for each stage, because Android remembers lookups and could hide a failure.
CONTROL_ADS = ["googleads.g.doubleclick.net", "pagead2.googlesyndication.com"]
BLOCKED = ["securepubads.g.doubleclick.net", "tpc.googlesyndication.com", "ib.adnxs.com", "cdn.taboola.com",
           "ads.tiktok.com", "auction.unityads.unity3d.com"]
ALLOWED_ON = ["www.wikipedia.org", "www.bbc.com", "www.mozilla.org", "static.doubleclick.net"]
ALLOWED_AFTER_RESTART = ["www.reuters.com", "www.github.com", "www.python.org", "www.youtube.com"]
SWITCH = re.compile(r'resource-id="com\.localadblocker:id/toggle"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
results = []


def environment():
    java = next((TOOLS / "jdk").glob("*/bin/javac.exe")).parent.parent
    return {**os.environ, "JAVA_HOME": str(java), "ANDROID_SDK_ROOT": str(SDK), "ANDROID_AVD_HOME": str(HOME / "avd"),
            "ANDROID_USER_HOME": str(HOME), "ANDROID_EMULATOR_HOME": str(HOME)}


def adb(*arguments, timeout=60):
    result = subprocess.run([str(ADB), *arguments], capture_output=True, text=True, errors="replace",
                            env=environment(), timeout=timeout)
    return (result.stdout + result.stderr).strip()


def shell(command, timeout=60):
    return adb("shell", command, timeout=timeout)


def check(name, passed, detail=""):
    results.append(bool(passed))
    print(f"[{'OK' if passed else 'FAILED'}] {name}" + (f"  ({detail})" if detail else ""), flush=True)


def create_device():
    (HOME / "avd").mkdir(parents=True, exist_ok=True)
    if (HOME / "avd" / f"{AVD}.ini").exists():
        return
    manager = SDK / "cmdline-tools" / "latest" / "bin" / "avdmanager.bat"
    # The .bat treats ";" as a separator, so this runs through cmd with the name quoted.
    command = f'cmd /c ""{manager}" create avd --force --name {AVD} --package "{IMAGE}" --device "pixel_6""'
    result = subprocess.run(command, input="no\n", capture_output=True, text=True, env=environment())
    if not (HOME / "avd" / f"{AVD}.ini").exists():
        raise SystemExit("Couldn't create the test phone:\n" + (result.stdout + result.stderr)[-1500:])


def start_emulator(extra=()):
    log = (HOME / "emulator.log").open("w")
    return subprocess.Popen([str(EMULATOR), "-avd", AVD, "-no-window", "-no-audio", "-no-boot-anim", "-no-snapshot",
                             "-netdelay", "none", "-netspeed", "full", *extra],
                            stdout=log, stderr=subprocess.STDOUT, env=environment())


def wait_for_boot(minutes=20):
    adb("wait-for-device", timeout=minutes * 60)
    deadline = time.time() + minutes * 60
    while time.time() < deadline:
        if shell("getprop sys.boot_completed").strip() == "1":
            return True
        time.sleep(3)
    return False


def resolves(name):
    """Asks through the phone's normal name lookup, the same route apps use."""
    output = shell(f"ping -c 1 -W 3 {name}", timeout=30)
    if "unknown host" in output.lower() or "bad address" in output.lower():
        return False
    return "PING" in output


def filter_active():
    return "VPN CONNECTED" in shell("dumpsys connectivity | grep -F 'ni{VPN'", timeout=30)


def wait_for(condition, seconds=30):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(1)
    return False


def tap_switch():
    """Taps the real switch on screen, the way a person would."""
    shell("uiautomator dump /sdcard/ui.xml", timeout=60)
    found = SWITCH.search(shell("cat /sdcard/ui.xml", timeout=30))
    if not found:
        raise SystemExit("Couldn't find the switch on screen.")
    left, top, right, bottom = (int(value) for value in found.groups())
    shell(f"input tap {(left + right) // 2} {(top + bottom) // 2}")


def open_app():
    shell(f"am start -n {PACKAGE}/.MainActivity")
    time.sleep(3)


def turn_on():
    # Stands in for the one tap on Android's VPN prompt, which an automated test can't reach.
    shell(f"appops set {PACKAGE} ACTIVATE_VPN allow")
    open_app()
    tap_switch()
    return wait_for(filter_active)


def check_names(label, allowed):
    for name in BLOCKED:
        check(f"{label}: {name} is blocked", not resolves(name))
    for name in allowed:
        check(f"{label}: {name} still resolves", wait_for(lambda n=name: resolves(n), 15))


def crash_lines():
    return shell(f"logcat -d -b crash | grep -c {PACKAGE}", timeout=30).strip()


def main():
    if not APK.exists():
        raise SystemExit("Build the app first: python build.py apk")
    create_device()
    emulator = start_emulator()
    try:
        if not wait_for_boot():
            raise SystemExit("The test phone didn't start. See .tools/avd-home/emulator.log")
        print("Android version:", shell("getprop ro.build.version.release"), "| API", shell("getprop ro.build.version.sdk"), flush=True)
        check("network works before the app", wait_for(lambda: resolves("www.google.com"), 120))
        for name in CONTROL_ADS:
            check(f"control: {name} resolves before the app", resolves(name))

        installed = adb("install", "-r", str(APK), timeout=180)
        check("app installs", "Success" in installed)
        shell("logcat -c")
        check("filter turns on", turn_on())
        time.sleep(2)
        check_names("while on", ALLOWED_ON)
        check("no crashes", crash_lines() in ("0", ""))

        print("Restarting the test phone...", flush=True)
        adb("reboot")
        time.sleep(10)
        check("phone restarts", wait_for_boot())
        check("filter comes back by itself after a restart", wait_for(filter_active, 90))
        time.sleep(3)
        check_names("after restart", ALLOWED_AFTER_RESTART)

        open_app()
        tap_switch()
        check("filter turns off", wait_for(lambda: not filter_active(), 30))
        check("turning it off restores ad lookups", wait_for(lambda: resolves("cdn.taboola.com"), 20))
        check("no crashes overall", crash_lines() in ("0", ""))
    finally:
        adb("emu", "kill")
        try:
            emulator.wait(timeout=30)
        except subprocess.TimeoutExpired:
            emulator.kill()
    print(f"\n{sum(results)} of {len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())

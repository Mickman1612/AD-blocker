"""Test the real app on a simulated phone. Everything stays in .tools/, and your own phone isn't involved.

Run: python tests/emulator_check.py
Checks: blocked names fail, normal names resolve, the network still works, the filter comes back after a
restart, turning it off restores ad lookups, and Android's own warnings stay clean.
"""
import os
import pathlib
import re
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent.parent
SDK = HERE / ".tools" / "sdk"
HOME = HERE / ".tools" / "avd-home"
ADB = SDK / "platform-tools" / "adb.exe"
EMULATOR = SDK / "emulator" / "emulator.exe"
APK = HERE / "dist" / "LocalAdBlocker.apk"
AVD = "adblocker_test"
PACKAGE = "com.localadblocker"
IMAGE = "system-images;android-36;google_apis;x86_64"
BLOCKED = ["securepubads.g.doubleclick.net", "doubleclick.net", "ads.tiktok.com", "unityads.unity3d.com", "api.ad.xiaomi.com"]
ALLOWED = ["www.google.com", "www.youtube.com", "www.wikipedia.org", "static.doubleclick.net"]
results = []


def environment():
    java = next((HERE / ".tools" / "jdk").glob("*/bin/javac.exe")).parent.parent
    return {**os.environ, "JAVA_HOME": str(java), "ANDROID_SDK_ROOT": str(SDK), "ANDROID_AVD_HOME": str(HOME / "avd"),
            "ANDROID_USER_HOME": str(HOME), "ANDROID_EMULATOR_HOME": str(HOME)}


def adb(*arguments, timeout=60):
    result = subprocess.run([str(ADB), *arguments], capture_output=True, text=True, errors="replace",
                            env=environment(), timeout=timeout)
    return (result.stdout + result.stderr).strip()


def shell(command, timeout=60):
    return adb("shell", command, timeout=timeout)


def check(name, passed, detail=""):
    results.append(passed)
    print(f"[{'OK' if passed else 'FAILED'}] {name}" + (f"  ({detail})" if detail else ""), flush=True)


def create_device():
    (HOME / "avd").mkdir(parents=True, exist_ok=True)
    if (HOME / "avd" / f"{AVD}.ini").exists():
        return
    manager = SDK / "cmdline-tools" / "latest" / "bin" / "avdmanager.bat"
    # The .bat treats ";" as a separator, so this runs through cmd with the name quoted.
    command = f'"{manager}" create avd --force --name {AVD} --package "{IMAGE}" --device "pixel_6"'
    result = subprocess.run(["cmd", "/c", f'"{command}"'], input="no\n", capture_output=True, text=True, env=environment())
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
    return "tun" in shell("ip link show") and PACKAGE in shell("dumpsys activity services " + PACKAGE, timeout=30)


def wait_for(condition, seconds=30):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(1)
    return False


def turn_on():
    # Stands in for the user's one tap on Android's VPN prompt, which only exists on screen.
    shell(f"appops set {PACKAGE} ACTIVATE_VPN allow")
    shell(f"am start -n {PACKAGE}/.MainActivity")
    time.sleep(2)
    shell(f"am start-foreground-service -n {PACKAGE}/.FilterVpnService")
    return wait_for(filter_active)


def check_names(label):
    for name in BLOCKED:
        check(f"{label}: {name} is blocked", wait_for(lambda n=name: not resolves(n), 10))
    for name in ALLOWED:
        check(f"{label}: {name} still resolves", wait_for(lambda n=name: resolves(n), 15))


def main():
    if not APK.exists():
        raise SystemExit("Build the app first: python build.py apk")
    create_device()
    emulator = start_emulator()
    try:
        if not wait_for_boot():
            raise SystemExit("The test phone didn't start. See .tools/avd-home/emulator.log")
        print("Android version:", shell("getprop ro.build.version.release"), "| API", shell("getprop ro.build.version.sdk"), flush=True)
        check("network works before the app", resolves("www.google.com"))
        check("ad names resolve before the app", resolves("securepubads.g.doubleclick.net"), "the control for the blocked checks")

        installed = adb("install", "-r", str(APK), timeout=180)
        check("app installs", "Success" in installed, installed[-120:])
        shell("logcat -c")
        check("filter turns on", turn_on())
        check_names("while on")

        crashes = shell(f"logcat -d -b crash | grep -c {PACKAGE}", timeout=30).strip()
        check("no crashes", crashes in ("0", ""), f"{crashes} crash lines")
        check("filter keeps running in the background", wait_for(filter_active, 5))

        print("Restarting the test phone...", flush=True)
        adb("reboot")
        time.sleep(10)
        check("phone restarts", wait_for_boot())
        check("filter comes back by itself after a restart", wait_for(filter_active, 90))
        check_names("after restart")

        shell(f"am start-foreground-service -n {PACKAGE}/.FilterVpnService -a com.localadblocker.STOP")
        check("filter turns off", wait_for(lambda: not filter_active(), 30))
        check("turning it off restores ad lookups", wait_for(lambda: resolves("securepubads.g.doubleclick.net"), 20))
        check("no crashes overall", shell(f"logcat -d -b crash | grep -c {PACKAGE}", timeout=30).strip() in ("0", ""))
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

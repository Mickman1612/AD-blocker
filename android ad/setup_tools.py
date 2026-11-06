"""Download the tools needed to build the Android app, into android ad/.tools only.

Run: python setup_tools.py
Installs nothing into Windows. Delete the .tools folder to remove everything.
Running this accepts Google's Android SDK licence.
"""
import hashlib
import pathlib
import re
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
TOOLS = HERE / ".tools"
DOWNLOADS = TOOLS / "downloads"
JDK_DIR = TOOLS / "jdk"
SDK_DIR = TOOLS / "sdk"
REPOSITORY = "https://dl.google.com/android/repository/"
JDK_URL = "https://aka.ms/download-jdk/microsoft-jdk-21-windows-x64.zip"
PLATFORM = "platforms;android-36"
SYSTEM_IMAGE = "system-images;android-36;google_apis;x86_64"
USER_AGENT = {"User-Agent": "local-build-setup"}


def fetch(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=USER_AGENT), timeout=120)


def download(url, target, expected=None, algorithm="sha1"):
    """Save a file, checking it against its published checksum."""
    digest = hashlib.new(algorithm)
    if target.exists() and expected:
        with target.open("rb") as existing:
            for chunk in iter(lambda: existing.read(1 << 20), b""):
                digest.update(chunk)
        if digest.hexdigest() == expected:
            print(f"Already have {target.name}", flush=True)
            return
        digest = hashlib.new(algorithm)
    print(f"Downloading {target.name}", flush=True)
    with fetch(url) as reply, target.open("wb") as out:
        for chunk in iter(lambda: reply.read(1 << 20), b""):
            digest.update(chunk)
            out.write(chunk)
    if expected and digest.hexdigest() != expected:
        target.unlink()
        raise SystemExit(f"{target.name} failed its checksum, so it was deleted.")
    print(f"  OK: {target.stat().st_size // 1048576} MB, {algorithm} {'checked' if expected else 'not published'}", flush=True)


def extract(archive, destination):
    """Unpack, refusing any entry that would land outside the destination."""
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.namelist():
            if not (destination / member).resolve().is_relative_to(destination):
                raise SystemExit(f"{archive.name} has an unsafe path: {member}")
        bundle.extractall(destination)


def install_jdk():
    if list(JDK_DIR.glob("*/bin/javac.exe")):
        return
    with fetch(JDK_URL) as reply:
        final = reply.geturl()
    name = final.rsplit("/", 1)[1]
    expected = None
    try:
        with fetch(final + ".sha256sum.txt") as reply:
            expected = reply.read().decode().split()[0].lower()
    except OSError:
        print("Microsoft's checksum file wasn't available.", flush=True)
    target = DOWNLOADS / name
    download(final, target, expected, "sha256")
    extract(target, JDK_DIR)


def latest_packages():
    root = ET.fromstring(fetch(REPOSITORY + "repository2-3.xml").read())
    stable = {}
    for package in root.iter():
        if not package.tag.endswith("remotePackage"):
            continue
        channel = package.find("channelRef")
        if channel is None or channel.get("ref") != "channel-0":
            continue
        for archive in package.iter("archive"):
            host = archive.find("host-os")
            if host is None or host.text == "windows":
                complete = archive.find("complete")
                stable[package.get("path")] = (complete.find("url").text, complete.find("checksum").text)
    return stable


def numbers(name):
    return [int(part) for part in re.findall(r"\d+", name)]


def install_command_line_tools(stable):
    target_dir = SDK_DIR / "cmdline-tools" / "latest"
    if (target_dir / "bin" / "sdkmanager.bat").exists():
        return
    newest = sorted((n for n in stable if n.startswith("cmdline-tools;")), key=numbers)[-1]
    url, checksum = stable[newest]
    archive = DOWNLOADS / url
    download(REPOSITORY + url, archive, checksum)
    unpack = SDK_DIR / "cmdline-tools" / "_unpack"
    extract(archive, unpack)
    (unpack / "cmdline-tools").rename(target_dir)
    unpack.rmdir()


def run_sdkmanager(env, *arguments, stdin=None):
    manager = SDK_DIR / "cmdline-tools" / "latest" / "bin" / "sdkmanager.bat"
    result = subprocess.run([str(manager), f"--sdk_root={SDK_DIR}", *arguments], env=env, input=stdin,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    if result.returncode != 0:
        print(result.stdout[-2000:], flush=True)
        raise SystemExit(f"sdkmanager failed: {arguments}")
    return result.stdout


def main():
    import os
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    install_jdk()
    java_home = next(JDK_DIR.glob("*/bin/javac.exe")).parent.parent
    print(f"Java: {java_home.name}", flush=True)

    stable = latest_packages()
    install_command_line_tools(stable)

    env = {**os.environ, "JAVA_HOME": str(java_home), "ANDROID_SDK_ROOT": str(SDK_DIR)}
    run_sdkmanager(env, "--licenses", stdin="y\n" * 30)
    print("Android SDK licence accepted", flush=True)

    candidates = [n for n in stable if re.fullmatch(r"build-tools;\d+\.\d+\.\d+", n)]
    build_tools = sorted(candidates, key=numbers)[-1]
    packages = ["platform-tools", build_tools, PLATFORM, "emulator", SYSTEM_IMAGE]
    for package in packages:
        print(f"Installing {package}", flush=True)
        # A file, because a Windows .bat treats the ";" in these names as a separator.
        package_file = DOWNLOADS / "package.txt"
        package_file.write_text(package + "\n", encoding="ascii")
        run_sdkmanager(env, f"--package_file={package_file}", stdin="y\n" * 5)
        if not (SDK_DIR / package.replace(";", "/")).exists():
            raise SystemExit(f"{package} wasn't installed.")
        print("  done", flush=True)

    (TOOLS / "versions.txt").write_text(f"java_home={java_home}\nbuild_tools={build_tools.split(';')[1]}\n", encoding="ascii")
    print("All tools ready.", flush=True)


if __name__ == "__main__":
    sys.exit(main())

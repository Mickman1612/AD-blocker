"""Build and test the Android app using only Python and the tools in .tools/. No Gradle.

python build.py test   Run the packet logic tests on this PC
python build.py apk    Build the installable file at dist/LocalAdBlocker.apk
"""
import os
import pathlib
import secrets
import shutil
import subprocess
import sys
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
APP = HERE / "app"
SOURCE = APP / "src"
CORE = SOURCE / "com" / "localadblocker" / "core"
BUILD = HERE / "build"
DIST = HERE / "dist"
KEYS = HERE / ".keys"
SDK = HERE / ".tools" / "sdk"
PLATFORM_JAR = SDK / "platforms" / "android-36" / "android.jar"
MIN_SDK = "26"
TARGET_SDK = "36"
VERSION_CODE = "1"
VERSION_NAME = "1.0"


def versions():
    lines = (HERE / ".tools" / "versions.txt").read_text(encoding="ascii").splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line)


def jdk_home():
    found = sorted((HERE / ".tools" / "jdk").glob("*/bin/javac.exe"))
    if not found:
        raise SystemExit("Java isn't set up yet. Run: python setup_tools.py")
    return found[0].parent.parent


def tool_environment():
    return {**os.environ, "JAVA_HOME": str(jdk_home())}


def run(*command):
    result = subprocess.run([str(part) for part in command], env=tool_environment(), capture_output=True, text=True, errors="replace")
    if result.returncode != 0:
        print(result.stdout[-6000:])
        print(result.stderr[-6000:])
        raise SystemExit(f"Failed: {pathlib.Path(str(command[0])).name}")
    return result.stdout


def java_files(folder):
    return sorted(str(path) for path in pathlib.Path(folder).rglob("*.java"))


def clean(folder):
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)


def test():
    bin_dir = jdk_home() / "bin"
    classes = BUILD / "test-classes"
    clean(classes)
    run(bin_dir / "javac.exe", "--release", "11", "-Xlint:all", "-Werror", "-d", classes,
        *java_files(CORE), *java_files(HERE / "tests"))
    output = run(bin_dir / "java.exe", "-cp", classes, "CoreTests")
    print(output.strip())


def signing_key():
    KEYS.mkdir(exist_ok=True)
    store = KEYS / "release.jks"
    password_file = KEYS / "password.txt"
    if not store.exists():
        password = secrets.token_urlsafe(24)
        password_file.write_text(password, encoding="ascii")
        run(jdk_home() / "bin" / "keytool.exe", "-genkeypair", "-keystore", store, "-storepass", password,
            "-keypass", password, "-alias", "app", "-keyalg", "RSA", "-keysize", "3072", "-validity", "10000",
            "-dname", "CN=Local Ad Blocker")
    return store, password_file.read_text(encoding="ascii").strip()


def apk():
    build_tools = SDK / "build-tools" / versions()["build_tools"]
    clean(BUILD / "gen")
    clean(BUILD / "classes")
    clean(BUILD / "dex")
    DIST.mkdir(exist_ok=True)

    resources = BUILD / "resources.zip"
    run(build_tools / "aapt2.exe", "compile", "--dir", APP / "res", "-o", resources)
    base = BUILD / "base.apk"
    run(build_tools / "aapt2.exe", "link", "-o", base, "-I", PLATFORM_JAR,
        "--manifest", APP / "AndroidManifest.xml", "--java", BUILD / "gen", "-A", APP / "assets",
        "--min-sdk-version", MIN_SDK, "--target-sdk-version", TARGET_SDK,
        "--version-code", VERSION_CODE, "--version-name", VERSION_NAME, resources)

    run(jdk_home() / "bin" / "javac.exe", "--release", "11", "-Xlint:-options", "-classpath", PLATFORM_JAR,
        "-d", BUILD / "classes", *java_files(SOURCE), *java_files(BUILD / "gen"))
    class_files = sorted(str(path) for path in (BUILD / "classes").rglob("*.class"))
    run(build_tools / "d8.bat", "--release", "--min-api", MIN_SDK, "--lib", PLATFORM_JAR,
        "--output", BUILD / "dex", *class_files)

    with zipfile.ZipFile(base, "a", zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(BUILD / "dex" / "classes.dex", "classes.dex")

    aligned = BUILD / "aligned.apk"
    run(build_tools / "zipalign.exe", "-f", "-p", "4", base, aligned)
    store, password = signing_key()
    final = DIST / "LocalAdBlocker.apk"
    run(build_tools / "apksigner.bat", "sign", "--ks", store, "--ks-pass", f"pass:{password}",
        "--key-pass", f"pass:{password}", "--out", final, aligned)
    print(run(build_tools / "apksigner.bat", "verify", "--print-certs", final).splitlines()[0])
    print(f"Built {final} ({final.stat().st_size // 1024} KB)")


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "apk"
    if action == "test":
        test()
    elif action == "apk":
        test()
        apk()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Decides what the filtering app touches and what it adds to pages, from our own rule files."""
import json
import os
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from proxy import certs  # noqa: E402
from proxy.server import ProxyConfig, build_pac, inline_hash, matches_domain  # noqa: E402
from tools import build_rules  # noqa: E402

PORT = 18899

# The only sites ever decrypted. Shopping, banking, email and account sign-in are left out on purpose,
# and they connect directly without passing through the app at all.
DECRYPT_SITES = ("youtube", "twitch", "facebook", "instagram", "x", "tiktok", "reddit", "linkedin", "pinterest",
                 "google", "duckduckgo", "yahoo")
EXTRA_HOSTS = ("www.bing.com",)  # Exact name only: other Bing hosts serve Windows itself.

# YouTube checks this host to see whether ads can load. Leaving it alone avoids its warning prompt.
EXEMPT_HOSTS = {"static.doubleclick.net"}

EXTENSION = REPO / "extension"
SCRIPTS = {
    "hooks": "content/main/net-hooks.js",
    "guard": "content/isolated/video-guard.js",
    "feed": "content/isolated/feed.js",
}
GENERIC_SCRIPT = "content/isolated/generic.js"


def data_dir():
    return pathlib.Path(os.environ["LOCALAPPDATA"]) / "LocalAdBlocker"


def _sites():
    return json.loads((REPO / "rules-src" / "sites.json").read_text(encoding="utf-8"))


def _pattern_host(pattern):
    return pattern.split("://", 1)[1].split("/", 1)[0]


def decrypt_targets():
    """Returns (domains including their subdomains, exact hosts)."""
    domains, hosts = set(), set(EXTRA_HOSTS)
    for site in _sites():
        if site["id"] not in DECRYPT_SITES:
            continue
        for pattern in site["matches"]:
            host = _pattern_host(pattern)
            if host.startswith("*."):
                domains.add(host[2:])
            else:
                hosts.add(host)
    return domains, hosts


def certificate_names():
    domains, hosts = decrypt_targets()
    names = set(hosts)
    for domain in domains:
        names.update((domain, f"*.{domain}"))
    return sorted(names)


def ad_path_patterns(text):
    """Turn our host-and-path URL rules into patterns. Rules with options need a browser's context."""
    patterns = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("||") or " | " in line:
            continue
        host, _, path = line[2:].rstrip("*").partition("/")
        host_part = re.escape(host).replace(r"\*", "[^/]*")
        path_part = re.escape(path).replace(r"\*", "[^ ]*")
        patterns.append(rf"^https?://([^/]*\.)?{host_part}/{path_part}")
    return patterns


def _ascii_only(text):
    """Escaped so it means the same whatever encoding the page uses."""
    return "".join(c if ord(c) < 128 else f"\\u{ord(c):04x}" for c in text)


class PageAssets:
    """The extension's own scripts and styles, ready to place inside a page."""

    def __init__(self):
        self._cache = {}
        self._sites = [site for site in _sites() if site["id"] in DECRYPT_SITES or site["id"] == "bing"]

    def _site_for(self, host):
        for site in self._sites:
            for pattern in site["matches"]:
                name = _pattern_host(pattern)
                if (name.startswith("*.") and matches_domain(host, {name[2:]})) or name == host:
                    return site
        return {"id": "generic-only"}

    def _read(self, relative):
        return (EXTENSION / relative).read_text(encoding="utf-8")

    def _build(self, site):
        styles = [self._read("generated/css/generic.css")]
        if site.get("css"):
            styles.append(self._read(f"generated/css/{site['css']}.css"))
        # Page hooks go first, so they are in place before anything else on the page runs.
        scripts = [self._read(path) for flag, path in SCRIPTS.items() if site.get(flag)]
        scripts.append(self._read(GENERIC_SCRIPT))
        style = _ascii_only("".join(styles)).replace("</style", "<\\/style")
        script = _ascii_only("\n".join(scripts)).replace("</script", "<\\/script")
        code = f"<style>{style}</style><script>{script}</script>".encode("ascii")
        return code, inline_hash(script), inline_hash(style)

    def snippet(self, host):
        site = self._site_for(host)
        if site["id"] not in self._cache:
            self._cache[site["id"]] = self._build(site)
        return self._cache[site["id"]]


def load_config(certificate_dir=None, port=PORT, with_certificates=True):
    domains, hosts = decrypt_targets()
    source = REPO / "rules-src"
    paths = certs.paths_in(certificate_dir or data_dir())
    return ProxyConfig(
        port=port,
        cert_file=str(paths.leaf_cert) if with_certificates else "",
        key_file=str(paths.leaf_key) if with_certificates else "",
        decrypt_domains=domains,
        decrypt_hosts=hosts,
        block_domains=set(build_rules.parse_domains((source / "ad-domains.txt").read_text(encoding="utf-8"))),
        exempt_hosts=set(EXEMPT_HOSTS),
        ad_path_patterns=ad_path_patterns((source / "url-patterns.txt").read_text(encoding="utf-8")),
        page_snippet=PageAssets().snippet,
    )


def build_routing_file(config):
    return build_pac(config.port, config.block_domains, config.exempt_hosts, config.decrypt_domains, config.decrypt_hosts)

"""Compile our hand-written rules in rules-src/ into extension/generated/.

Run: python tools/build_rules.py
Nothing is downloaded. Everything comes from files in this project.
"""
import json
import pathlib
import re
import shutil
import sys

PRIORITY_BLOCK = 1
PRIORITY_ALLOW = 2
PRIORITY_REDIRECT = 3

SUBRESOURCE_TYPES = [
    "sub_frame", "stylesheet", "script", "image", "font", "object", "xmlhttprequest",
    "ping", "csp_report", "media", "websocket", "webtransport", "webbundle", "other",
]

# Listing one of these as an ad domain would break a major site. Ad-only subdomains
# such as adservice.google.com are fine, so only an exact match is refused.
PROTECTED_DOMAINS = {
    "akamaihd.net", "akamaized.net", "amazon.com", "amazonaws.com", "apple.com", "bing.com",
    "cdninstagram.com", "cloudflare.com", "cloudfront.net", "ebay.com", "ebaystatic.com",
    "facebook.com", "fbcdn.net", "ggpht.com", "google.com", "googleapis.com",
    "googleusercontent.com", "googlevideo.com", "gstatic.com", "instagram.com", "jtvnw.net",
    "licdn.com", "linkedin.com", "microsoft.com", "msn.com", "netflix.com", "nflxvideo.net",
    "pinimg.com", "pinterest.com", "redd.it", "reddit.com", "redditmedia.com",
    "redditstatic.com", "scdn.co", "spotify.com", "spotifycdn.com", "tiktok.com", "ttvnw.net",
    "twimg.com", "twitch.tv", "twitter.com", "x.com", "yahoo.com", "yimg.com", "youtube.com",
    "ytimg.com",
}

DOMAIN_RE = re.compile(r"^(?!-)[a-z0-9-]+(\.[a-z0-9-]+)+$")
MATCH_RE = re.compile(r"^(\*|https?)://(\*|(\*\.)?[^/*]+)/.*$")
SITE_ID_RE = re.compile(r"^[a-z0-9-]+$")


class RuleError(ValueError):
    """A rule source is wrong. The build stops rather than ship a bad rule."""


def _lines(text, comment):
    """Yield (line_number, content) for each meaningful line."""
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith(comment):
            continue
        yield number, line


def parse_domains(text):
    domains = {}
    for number, line in _lines(text, "#"):
        domain = line.split("#", 1)[0].strip().lower()
        if not DOMAIN_RE.match(domain):
            raise RuleError(f"line {number}: not a domain: {line!r}")
        if domain in PROTECTED_DOMAINS:
            raise RuleError(f"line {number}: {domain} is protected, list an ad subdomain instead")
        domains[domain] = True
    return list(domains)


def parse_url_patterns(text):
    rules = []
    for number, line in _lines(text, "#"):
        pattern, *options = [part.strip() for part in line.split(" | ")]
        allow = pattern.startswith("@@")
        condition = {
            "urlFilter": pattern[2:] if allow else pattern,
            "resourceTypes": list(SUBRESOURCE_TYPES),
        }
        for option in options:
            name, _, value = option.partition("=")
            if name == "third-party" and not value:
                condition["domainType"] = "thirdParty"
            elif name == "first-party" and not value:
                condition["domainType"] = "firstParty"
            elif name == "types" and value:
                types = value.split(",")
                unknown = [t for t in types if t not in SUBRESOURCE_TYPES]
                if unknown:
                    raise RuleError(f"line {number}: unknown resource type {unknown}")
                condition["resourceTypes"] = types
            elif name == "only" and value:
                condition["initiatorDomains"] = value.split(",")
            elif name == "except" and value:
                condition["excludedInitiatorDomains"] = value.split(",")
            else:
                raise RuleError(f"line {number}: unknown option {option!r}")
        rules.append({
            "priority": PRIORITY_ALLOW if allow else PRIORITY_BLOCK,
            "action": {"type": "allow" if allow else "block"},
            "condition": condition,
        })
    return rules


def parse_surrogates(text, available):
    rules = []
    for number, line in _lines(text, "#"):
        pattern, separator, filename = [part.strip() for part in line.partition(" -> ")]
        if not separator:
            raise RuleError(f"line {number}: expected 'pattern -> file'")
        if filename not in available:
            raise RuleError(f"line {number}: surrogate file {filename} doesn't exist")
        rules.append({
            "priority": PRIORITY_REDIRECT,
            "action": {"type": "redirect", "redirect": {"extensionPath": f"/surrogates/{filename}"}},
            "condition": {"urlFilter": pattern, "resourceTypes": ["script"]},
        })
    return rules


def build_network_rules(domains, patterns, surrogates):
    rules = []
    if domains:
        rules.append({
            "priority": PRIORITY_BLOCK,
            "action": {"type": "block"},
            "condition": {"requestDomains": domains, "resourceTypes": list(SUBRESOURCE_TYPES)},
        })
    rules.extend(patterns)
    rules.extend(surrogates)
    return [{"id": index, **rule} for index, rule in enumerate(rules, start=1)]


def parse_selectors(text):
    selectors = {}
    for number, line in _lines(text, "!"):
        if any(character in line for character in "{}<"):
            raise RuleError(f"line {number}: unsafe selector: {line!r}")
        selectors[line] = True
    return list(selectors)


def build_css(selectors):
    # One rule per selector: browsers drop a whole rule if any selector in it is invalid.
    return "".join(f"{selector}{{display:none!important}}\n" for selector in selectors)


def validate_sites(sites, css_names):
    seen = set()
    for site in sites:
        site_id = site.get("id", "")
        if not SITE_ID_RE.match(site_id):
            raise RuleError(f"bad site id: {site_id!r}")
        if site_id in seen:
            raise RuleError(f"duplicate site id: {site_id}")
        seen.add(site_id)
        for pattern in site.get("matches", []):
            if pattern != "<all_urls>" and not MATCH_RE.match(pattern):
                raise RuleError(f"{site_id}: bad match pattern: {pattern}")
        if not site.get("matches"):
            raise RuleError(f"{site_id}: no match pattern")
        css = site.get("css")
        if css and css not in css_names:
            raise RuleError(f"{site_id}: no cosmetic source named {css}")
    return sites


def compile_all(source_dir, surrogate_dir):
    source_dir = pathlib.Path(source_dir)
    surrogate_dir = pathlib.Path(surrogate_dir)
    read = lambda name: (source_dir / name).read_text(encoding="utf-8")
    available = {p.name for p in surrogate_dir.glob("*.js")} if surrogate_dir.exists() else set()
    network = build_network_rules(
        parse_domains(read("ad-domains.txt")),
        parse_url_patterns(read("url-patterns.txt")),
        parse_surrogates(read("surrogates.txt"), available),
    )
    css = {}
    for path in sorted((source_dir / "cosmetic").glob("*.txt")):
        try:
            css[path.stem] = build_css(parse_selectors(path.read_text(encoding="utf-8")))
        except RuleError as error:
            raise RuleError(f"{path.name}: {error}") from None
    sites = validate_sites(json.loads(read("sites.json")), set(css))
    return {"network": network, "css": css, "sites": sites}


def write_output(compiled, target_dir):
    target_dir = pathlib.Path(target_dir)
    if target_dir.exists():
        shutil.rmtree(target_dir)
    (target_dir / "css").mkdir(parents=True)
    (target_dir / "network.json").write_text(json.dumps(compiled["network"], indent=0), encoding="utf-8")
    for name, css in compiled["css"].items():
        (target_dir / "css" / f"{name}.css").write_text(css, encoding="utf-8")
    (target_dir / "sites.js").write_text(
        "// Generated by tools/build_rules.py. Edit rules-src/sites.json instead.\n"
        f"export const SITES = {json.dumps(compiled['sites'], indent=2)};\n", encoding="utf-8")


def main():
    repo = pathlib.Path(__file__).resolve().parent.parent
    try:
        compiled = compile_all(repo / "rules-src", repo / "extension" / "surrogates")
    except RuleError as error:
        print(f"Build failed, nothing was changed: {error}", file=sys.stderr)
        return 1
    write_output(compiled, repo / "extension" / "generated")
    domains = len(compiled["network"][0]["condition"]["requestDomains"])
    print(f"Built {len(compiled['network'])} network rules covering {domains} ad domains, "
          f"{len(compiled['css'])} style sheets, {len(compiled['sites'])} site entries.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

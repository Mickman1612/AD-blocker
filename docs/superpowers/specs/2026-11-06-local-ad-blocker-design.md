# Local Ad Blocker: Design

**Date:** 2026-11-06
**Status:** Approved direction. The user asked for no further questions on design choices.

## Goal

No ads of any type while browsing on this one PC, on YouTube and every other platform, without paying anyone.

## Hard constraints

These come from the user and override any coverage gain:

1. **Only us.** Every rule and script is written in this project. No filter lists, no code and no services from other providers.
2. **Nothing leaves the PC.** The extension makes no network requests of its own: no updater, no telemetry, no remote config.
3. **No cost.** No paid tools or subscriptions.
4. **No third-party dependencies.** Python standard library only for tools and tests. No Node, no pip packages.

## Scope

- **In:** every app on this PC through the hosts file, Windows' own ad settings, and page-level blocking in Edge, Chrome and any other Chromium browser through the extension.
- **Out:** Firefox's extension, because it isn't installed and has different sideloading rules. The hosts file would still cover it.
- **Ads only.** This doesn't bypass paywalls, DRM or subscription content.

## PC-wide layer (added 2026-11-06)

The user widened the goal from browsers to the entire PC.

| Option | Reaches | Removes YouTube ads | Risk | Decision |
|---|---|---|---|---|
| Hosts file | Every app using Windows name lookups | No | Low. Nothing runs, nothing is decrypted, and it undoes cleanly | **Use** |
| Windows ad settings | Start menu, lock screen, File Explorer, tips | No | Low. Per-user and undoable | **Use** |
| Extension | Browsers it's loaded in | Yes | Low | **Keep** |
| Local DNS server | Every app using Windows DNS | No | Medium. Lookups depend on a running process and the upstream setting goes stale across networks | No |
| Root-certificate proxy | Apps honouring the proxy setting | Yes | High. A leaked key could impersonate any site, and pinned apps break | No |

**Hosts file details:**
- The hosts file matches exact names only, so the list holds our ad domains plus specific hostnames in `rules-src/pc-hostnames.txt`, gathered from what real pages request and from what we know.
- `static.doubleclick.net` is excluded on purpose. YouTube loads `ad_status.js` from it, and the extension answers that request locally. Blocking it for browsers without the extension could invite YouTube's ad-blocker warning.
- The extension's rules run before name lookup, so its local stand-ins still work with the hosts file in place.
- Both scripts are run by the user. This session has no admin rights and doesn't change system settings itself.
- A marked block is added to the hosts file, and turning it off removes only that block.

**Known cost:** the hosts file can't tell an ad from the page you asked for, so clicking a sponsored link that goes through a blocked ad domain fails, which the extension's rules would otherwise allow.

## Why an extension built by us

Domain blocking can't remove YouTube ads, which come from the same servers as the videos. A local proxy needs a root certificate on the PC. An MV3 extension needs neither, and it can't take the internet down if it fails.

Community lists have far more rules than we can write, so we replace coverage by count with coverage by technique:

| Layer | What it does | Covers |
|---|---|---|
| Network rules | Block our own list of ad-network domains and ad URL patterns | Most display and video ads on any site |
| Surrogates | Serve harmless local stand-ins for ad libraries (GPT, AdSense, IMA, APS) | Sites and players that stall when an ad library is missing |
| Generic hiding | Our own selectors for standard ad slots | Leftover boxes on any site |
| Heuristics | Hide cross-origin iframes at standard ad sizes, and empty boxes labelled as ads | Long-tail ad networks missing from our list |
| Response scrubbing | Remove ad data from JSON before the page reads it | YouTube, X, TikTok, Reddit and similar |
| Feed hiding | Hide feed items carrying an ad marker | Facebook, Instagram, LinkedIn, Pinterest and similar |
| Video guard | While a player reports an ad, mute it, hide it, skip or fast-forward | Ads that get through, including ones stitched into the stream |
| Picker | The user clicks anything on a page to hide it there permanently, stored locally | Whatever the layers above miss |

## Units

| Unit | Path | Purpose |
|---|---|---|
| Rule sources | `rules-src/` | Hand-written domains, URL patterns, selectors and the site table |
| Compiler | `tools/build_rules.py` | Validates sources and generates everything in `extension/generated/` |
| Service worker | `extension/background.js` | Registers content scripts, handles pause-per-site and the badge |
| Response hooks | `extension/content/main/net-hooks.js` | Page-world scrubbing with a per-site config table |
| Generic layer | `extension/content/isolated/generic.js` | Heuristics on every page |
| Feed hider | `extension/content/isolated/feed.js` | Per-site feed item detection |
| Video guard | `extension/content/isolated/video-guard.js` | Per-site ad-playing detection and handling |
| User rules | `extension/content/isolated/user-rules.js` | Applies rules saved by the picker |
| Picker | `extension/content/isolated/picker.js` | Injected on request to choose an element |
| Surrogates | `extension/surrogates/` | Local no-op ad libraries |
| Pop-up | `extension/popup/` | Pause on this site, hide something, clear this site's rules |
| Test harness | `tests/harness/` | Drives real Edge over the DevTools protocol, standard library only |

## Key decisions

- **Scripts register dynamically** with `chrome.scripting.registerContentScripts`, so pausing a site can use `excludeMatches`. This covers page-world scripts, which can't read extension storage.
- **Rules are static files** that only change when we rebuild and reload.
- **The extension CSP sets `connect-src 'self'`**, so extension pages can't reach the network even by mistake.
- **Hooks never start requests.** They only rewrite responses the page already asked for.
- **Failure leaves the page alone.** Any hook error returns the original data, so a bad rule can't break a site.

## Platform coverage

| Group | Platforms | Main layers |
|---|---|---|
| Video | YouTube, YouTube Music, Twitch, Dailymotion | Scrubbing, video guard, hiding |
| Social | Facebook, Instagram, X, Reddit, TikTok, LinkedIn, Pinterest | Scrubbing or feed hiding |
| Audio | Spotify web, SoundCloud | Network rules, video guard for audio, hiding |
| Search | Google, Bing, DuckDuckGo, Yahoo | Site hiding |
| Shopping | Amazon, eBay | Site hiding, feed hiding |
| Paid and free streaming | Hulu, Peacock, Tubi, Pluto TV, Crunchyroll, Prime Video, Netflix, Max | Network rules, surrogates, video guard |
| Everything else | Any site | Network rules, surrogates, generic hiding, heuristics, picker |

## Known limits

- **YouTube's wait.** When an ad is due and doesn't play, YouTube's streaming server holds the video back for roughly the ad's length, using a countdown it enforces itself. The user sees a loading spinner instead of the ad. Requesting no-ad playback, hiding the inline response, removing the back-off and running the ad hidden were all tested on 2026-11-06, and none removed the wait.
- **Upkeep is ours.** With no updater, ads can return when a platform changes until we fix the rules here.
- **Smaller long-tail coverage** than community lists. The heuristics and the picker partly make up for that.
- **Stitched ads** are part of the video stream. The video guard can hide and mute them or speed past them, but on live streams the wait may remain.
- **Anti-adblock walls:** without community lists, some sites may refuse to load content. Pause-per-site is the way out.
- **Sponsor segments** that creators build into their videos can't be detected without an outside data service.

## Testing

1. **Compiler unit tests** with Python `unittest`.
2. **Hermetic browser tests** in real Edge with a temporary profile and a real extension load. The DevTools `Fetch` domain fakes responses on real hostnames, so they run offline and need no accounts.
3. **Live checks** of YouTube with and without the extension on the same videos. "No ads" only counts if the control run showed ads.
4. **Live breakage checks** on popular sites.
5. **Local-only checks:** a static scan of extension source, plus a runtime capture showing the service worker makes no network requests.

Chrome 156 ignores `--load-extension`, so automated tests run in Edge and Chrome is checked after the user loads the extension. Platforms that need a login can only be verified in the user's real profile, and the final report has to say which platforms were verified and how.

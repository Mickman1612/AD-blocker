# Local Ad Blocker

An ad blocker for this one PC, for Edge, Chrome and other Chromium browsers. Every rule and script here was written for this project. It uses no outside lists or services and makes no network requests of its own.

## Install

Do this once in each browser:

1. Open `edge://extensions` in Edge or `chrome://extensions` in Chrome.
2. Turn on **Developer mode**.
3. Click **Load unpacked** and choose `C:\Ad blocker\extension`.

Keep the folder where it is, because the browser reads the extension from it. If Edge asks at startup whether to turn off developer-mode extensions, decline.

## Using it

Click the toolbar icon on any site:

- **Block ads on this site:** turn this off if a site breaks or refuses to load.
- **Hide something on this page:** click anything on the page to hide it there from then on. Press Esc to cancel.
- **Show the items you hid:** undoes those choices for that site.

The number on the icon counts what was blocked on the current page.

## What it can't do

- **YouTube's wait:** when an ad is due, YouTube's server holds the video back for about the ad's length. You see a loading spinner rather than the ad.
- **No automatic updates:** this follows from using nothing external. When a platform changes how it serves ads, some can return until the rules here are updated.
- **Less long-tail coverage** than community lists. Use the picker for anything that gets through.
- **Stream-stitched ads:** on some streaming services, ads are part of the video. Where we can detect one, the player is muted and hidden until it ends, so the wait remains.
- **Sponsor segments** that creators build into their videos, and ads in apps outside the browser.

## Changing the rules

The rules are in `rules-src/`. After editing them, rebuild, then click the reload icon on the extension's card in the browser's extensions page:

```bash
python tools/build_rules.py
```

| File | Purpose |
|---|---|
| `rules-src/ad-domains.txt` | Ad network domains to block |
| `rules-src/url-patterns.txt` | Ad URL patterns |
| `rules-src/surrogates.txt` | Ad libraries to replace with harmless local stand-ins |
| `rules-src/cosmetic/*.txt` | Page elements to hide, one file per site |
| `rules-src/sites.json` | Which scripts and styles apply to which sites |

Per-site logic is in `extension/content/`: `main/net-hooks.js` removes ad data from responses, `isolated/feed.js` hides feed items, and `isolated/video-guard.js` handles video ads that get through.

## Tests

Needs only Python and Edge. Browser tests use a temporary profile, so your own profile is never touched.

```bash
python -m unittest discover -s tests -t .
```

Live checks visit real sites, with and without the extension:

```bash
python -m tests.live.youtube_compare
```

```bash
python -m tests.live.site_check
```

```bash
python -m tests.live.twitch_check
```

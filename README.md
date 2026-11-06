# Local Ad Blocker

An ad blocker for this one PC. Every rule and script here was written for this project. It uses no outside lists or services and makes no network requests of its own.

It has three parts, because no single method can remove every kind of ad:

| Part | Reaches | Removes |
|---|---|---|
| Hosts list | Every app that uses Windows name lookups | Ads from known ad servers |
| Windows settings | Windows itself | Promotions in Start, File Explorer, the lock screen and tips |
| Browser extension | Edge, Chrome and other Chromium browsers it's loaded in | YouTube ads, feed ads and empty ad boxes |

## Turn on PC-wide blocking

Double-click `pc-wide\Turn on PC-wide blocking.cmd` and click **Yes** when Windows asks. Then close and reopen your browsers and other apps.

- The Windows settings change without asking for administrator rights. The hosts file step is the one that asks.
- Some security software warns about hosts file changes, because malware also edits that file. This change only adds a marked block of ad servers.
- To undo everything, double-click `pc-wide\Turn off PC-wide blocking.cmd`. It removes only our block and restores your earlier Windows settings. The original hosts file is also saved as `pc-wide\hosts.original`.

## Install the browser extension

Double-click `Load extension in browsers.cmd`. It walks you through each browser, puts the text you need on the clipboard at each step, and tells you when it worked. Browsers don't let a program press these buttons for you, so these clicks are yours:

1. Open `edge://extensions` in Edge or `chrome://extensions` in Chrome.
2. Turn on **Developer mode**.
3. Click **Load unpacked** and choose `C:\Ad blocker\extension`.

Keep the folder where it is, because the browser reads the extension from it. If Edge asks at startup whether to turn off developer-mode extensions, decline.

## Using the extension

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
- **Sponsor segments** that creators build into their videos.
- **Ads an app serves from its own servers:** the hosts list can't separate these from the app's real content.
- **Sponsored links** that go through a blocked ad server won't open while PC-wide blocking is on.

## Changing the rules

The rules are in `rules-src/`. After editing them, rebuild, then click the reload icon on the extension's card in the browser's extensions page:

```bash
python tools/build_rules.py
```

| File | Purpose |
|---|---|
| `rules-src/ad-domains.txt` | Ad network domains to block |
| `rules-src/pc-hostnames.txt` | Exact ad hostnames for the hosts file, which can't match subdomains |
| `rules-src/url-patterns.txt` | Ad URL patterns |
| `rules-src/surrogates.txt` | Ad libraries to replace with harmless local stand-ins |
| `rules-src/cosmetic/*.txt` | Page elements to hide, one file per site |
| `rules-src/sites.json` | Which scripts and styles apply to which sites |

After changing the hostnames, run the Turn on file again to update the hosts file. To find new hostnames, run `python -m tests.live.harvest_hostnames`.

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

```bash
python -m tests.live.pc_wide_check
```

With PC-wide blocking on, the "without the extension" side of these checks is also blocked, so turn it off first for a true comparison.

# Local Ad Blocker

An ad blocker for this one PC. Every rule and script here was written for this project. It uses no outside lists or services, and nothing is sent anywhere.

## Turn it on

Double-click **Turn ON ad blocker**. Then:

1. Click **Yes** when Windows asks.
2. Follow the short steps it shows to add the blocker to each browser you use. You only do this once per browser.

After that, it works by itself every time you turn on your PC.

To remove it, double-click **Turn OFF ad blocker**, then remove **Local Ad Blocker** from each browser's extensions page.

## What it does

| Part | Reaches | Removes |
|---|---|---|
| Browser blocker | Edge, Chrome and other Chromium browsers it's added to | Ads on websites, YouTube ads, ads in social feeds and search results, and empty ad boxes |
| Ad server list | Every app on the PC | Ads from known ad servers, in apps as well as browsers |
| Windows settings | Windows itself | Promotions in Start, File Explorer, the lock screen and tips |

The browser blocker works inside the browser, the way Brave's blocking does, so pages load quickly. In tests it loaded CNN in about 1.4 seconds, compared with 8 seconds or more without blocking.

## What it can't do

- **YouTube's wait:** when YouTube decides to show an ad, it holds the video back for roughly that ad's length even if the ad is blocked. In tests that meant 8–16 seconds, compared with about 20 seconds when the ad plays. YouTube does this on purpose, and Brave users report the same wait.
- **Ads an app serves from its own servers,** because the ad server list can't separate those from the app's content.
- **Sponsored links** that go through a blocked ad server won't open.
- **Sponsor segments** that creators build into their videos.
- **Stream-stitched ads** on some streaming services are part of the video itself.
- **No automatic updates:** this follows from using nothing external. When a platform changes how it serves ads, some can return until the rules here are updated.

Some security software warns about hosts file changes, because malware also edits that file. This change only adds a marked block of ad servers.

## Using the browser blocker

Click its toolbar icon on any site:

- **Block ads on this site:** turn this off if a site breaks.
- **Hide something on this page:** click anything to hide it there from then on. Press Esc to cancel.
- **Show the items you hid:** undoes those choices for that site.

If Edge asks at startup whether to turn off developer-mode extensions, decline.

## The retired filtering app

An earlier version ran a local filtering app in `proxy/` instead of the browser blocker. It needed a trusted certificate and made YouTube slower, so Turn ON no longer uses it. Its code stays here only so that Turn OFF can remove it from PCs that still have it.

## Changing the rules

The rules are in `rules-src/`. After editing them, run the command below, then click the reload icon on the extension's card in each browser. Run **Turn ON** again to update the ad server list.

```bash
python tools/build_rules.py
```

| File | Purpose |
|---|---|
| `rules-src/ad-domains.txt` | Ad network domains to block |
| `rules-src/pc-hostnames.txt` | Exact ad hostnames for the PC-wide list, which can't match subdomains |
| `rules-src/android-domains.txt` | Extra ad domains for the Android app |
| `rules-src/url-patterns.txt` | Ad URL patterns |
| `rules-src/surrogates.txt` | Harmless local stand-ins for ad libraries |
| `rules-src/cosmetic/*.txt` | Page elements to hide, one file per site |
| `rules-src/sites.json` | Which scripts and styles apply to which sites |

## Tests

These need only Python and Edge. Browser tests use a temporary profile, so your own profile is never touched.

```bash
python -m unittest discover -s tests -t .
```

The live checks below visit real sites. For a true "without blocking" comparison, turn the ad blocker off first.

```bash
python -m tests.live.speed_check
```

```bash
python -m tests.live.youtube_compare
```

```bash
python -m tests.live.site_check
```

The Android version is in `android ad/`, with its own README.

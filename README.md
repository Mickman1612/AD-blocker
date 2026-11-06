# Local Ad Blocker

An ad blocker for this one PC. Every rule and script here was written for this project. It uses no outside lists or services, and nothing is sent anywhere.

## Turn it on

Double-click **Turn ON ad blocker** and click **Yes** when Windows asks. Then close and reopen your browsers.

That's all. It starts by itself every time you turn on your PC.

To remove it completely, double-click **Turn OFF ad blocker**. Python must stay installed, and this folder must stay where it is, because the app runs from here.

## What it does

No single method removes every kind of ad, so it combines three:

| Part | Reaches | Removes |
|---|---|---|
| Hosts list | Every app that uses Windows name lookups | Ads from known ad servers |
| Windows settings | Windows itself | Promotions in Start, File Explorer, the lock screen and tips |
| Filtering app | Browsers and apps that follow the Windows proxy setting | YouTube ads, ads in social feeds and search results |

## How your security is protected

The filtering app needs a certificate that Windows trusts, which is the risky part of any tool like this. Here's how that risk is limited:

- **Nothing new can be issued.** The certificate's private key is destroyed during setup, after signing one certificate for the listed sites. Even with full access to this PC, nobody could use it to create a certificate for your bank.
- **Only listed sites are read.** That's YouTube, Twitch, Facebook, Instagram, X, TikTok, Pinterest, and Google, Bing and DuckDuckGo search. LinkedIn, Reddit and Yahoo reject the app's connection, so they connect directly and only their ad servers are blocked. On those sites, passwords and messages pass through the app on this PC.
- **Everything else goes straight to the internet.** Banks, shopping, email and account sign-in pages never touch the app. The full rules are in `proxy/app.py`.
- **Nothing is kept.** The app stores and logs nothing, and it only accepts connections from this PC.
- **If it stops, browsing carries on.** Listed sites connect directly, so ads may return but sites keep working.

## What it can't do

- **YouTube's wait:** when an ad is due, YouTube's server can hold the video back for about the ad's length. You may see a spinner rather than the ad.
- **Ads an app serves from its own servers,** when that app ignores the proxy setting.
- **Empty ad boxes** on sites outside the list. The ad itself is gone but its space may remain. The optional browser extension hides these.
- **Sponsored links** that go through a blocked ad server won't open.
- **Stream-stitched ads** on some streaming services are part of the video.
- **Sponsor segments** that creators build into their videos.
- **No automatic updates:** this follows from using nothing external. When a platform changes how it serves ads, some can return until the rules here are updated.

Some security software warns about the hosts file or certificate changes, because malware makes similar changes. These only come from running the Turn ON file.

## Optional: the browser extension

You don't need this. It adds a pop-up with a per-site off switch, click-to-hide, and hiding of empty ad boxes on every site. To add it, double-click `optional\Load extension in browsers.cmd`, which walks you through the steps.

## Changing the rules

The rules are in `rules-src/`. After editing them, rebuild, then run **Turn ON ad blocker** again:

```bash
python tools/build_rules.py
```

| File | Purpose |
|---|---|
| `rules-src/ad-domains.txt` | Ad network domains to block |
| `rules-src/pc-hostnames.txt` | Exact ad hostnames for the hosts file, which can't match subdomains |
| `rules-src/url-patterns.txt` | Ad URL patterns |
| `rules-src/surrogates.txt` | Harmless local stand-ins for ad libraries, used by the extension |
| `rules-src/cosmetic/*.txt` | Page elements to hide, one file per site |
| `rules-src/sites.json` | Which scripts and styles apply to which sites |

Per-site page logic is in `extension/content/`, and the filtering app uses those same files. To find new ad hostnames, run `python -m tests.live.harvest_hostnames`.

## Tests

Needs only Python and Edge. Browser tests use a temporary profile, so your own profile is never touched.

```bash
python -m unittest discover -s tests -t .
```

Live checks visit real sites, with and without blocking:

```bash
python -m tests.live.proxy_check
```

```bash
python -m tests.live.youtube_compare
```

```bash
python -m tests.live.site_check
```

```bash
python -m tests.live.pc_wide_check
```

Turn the ad blocker off first for a true comparison, because the "normal" side of these checks would otherwise be blocked too.

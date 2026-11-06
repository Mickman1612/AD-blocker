# Local Ad Blocker for Android

Blocks ad servers across your phone's apps and browsers. It needs no root, costs nothing, and starts again by itself when the phone restarts. Everything in it was written for this project, using no outside lists, libraries or services.

## Install

1. Copy `LocalAdBlocker.apk` to your phone, using a USB cable or any way you like to send yourself a file.
2. Tap the file on your phone. If Android asks, allow installing from that app. If it warns about an unknown app, choose **Install anyway**.
3. Open **Local Ad Blocker**, turn the switch on and tap **OK** on Android's prompt.

Android shows a small key icon while it's on. That's just how Android labels this kind of filter.

## What it blocks

It stops apps from finding known ad servers, so ads from those servers never load. This works in most free apps, games and websites.

## What it can't block

**Ads that come from the same servers as the content.** This includes the YouTube app, YouTube in a browser, Instagram, Facebook and TikTok. No app can remove those on a normal, unrooted phone.

You may also see:

- Empty boxes on websites where an ad would have been.
- Sponsored links that don't open, if they go through a blocked ad server.

## If something goes wrong

- **A site or app breaks:** turn the switch off and try again. If that fixes it, tell Claude which one so it can be excluded.
- **It stops after a while or after a restart:** some phones close background apps to save battery. Allow unrestricted battery use for the app, or use the **Keep it on** button to turn on Always-on VPN.
- **The app warns about Private DNS:** a Private DNS provider can send lookups around the filter. In Settings, search for Private DNS and choose **Automatic**.
- **You use another VPN:** Android allows only one at a time, so starting it turns this filter off.
- **Internet stops working:** turn the switch off. The app has no way to change anything once it's off or uninstalled.

## Privacy

The app has no analytics, account, or updates. It sends nothing of its own. Lookups that aren't blocked go to your phone's normal DNS server, the same one it would use without the app, and normal traffic never enters the app at all. The app stores only whether the switch is on.

## For building and changing it

The ad list is generated from `rules-src/` at the top of this project. Extra phone-only domains go in `rules-src/android-domains.txt`. Run these from this folder:

```bash
python ../tools/build_rules.py
```

```bash
python build.py apk
```

```bash
python tests/emulator_check.py
```

- `python setup_tools.py` downloads the build tools into `.tools/` (about 11 GB once the test phone has run, and this accepts Google's Android SDK licence). Nothing is installed into Windows, and you can delete that folder to get the space back.
- `.keys/` holds the app's signing key. An updated app only installs over the old one if it's signed with this key, so keep that folder. Without it, you'd have to uninstall the app first.
- `tests/CoreTests.java` covers the packet logic and runs as part of `build.py`. `tests/emulator_check.py` runs the real app on a simulated phone.

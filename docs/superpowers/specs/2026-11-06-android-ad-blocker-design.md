# Android Ad Blocker: Design

**Date:** 2026-11-06
**Location:** `android ad/`
**Status:** The user asked for an Android version and for decisions to follow recommendations. Needs one approval: downloading the build tools.

## Goal

Block ads across the user's Android phone, using the same "only us" rules as the PC version, with as few steps as possible and automatic start after a restart.

## Constraints

The PC version's rules still apply:

1. **Only us.** Rules and code are written in this project. No filter lists, code libraries or services from other providers.
2. **Nothing leaves the phone that wouldn't anyway.** The app sends no data of its own, with no analytics, updates or account. Name lookups that aren't blocked go to the phone's existing DNS server, the same one it would use without the app. It never adds a public DNS provider.
3. **No cost, no root.**
4. **Build tools are the one exception.** Android apps can't be compiled without Google's SDK and a Java compiler. They run only on the PC while building, and none of their code libraries end up in the app beyond Android itself.

## What Android allows

| Method | Reaches | Removes YouTube app ads | Steps for the user | Decision |
|---|---|---|---|---|
| Local DNS filter using Android's VPN permission | Every app and browser | No | Install, tap once | **Build** |
| Private DNS setting | Every app | No | Needs an outside server | No, breaks "only us" |
| Local decrypting proxy | Browsers only: apps ignore user-installed certificates on Android 7 and later | Only YouTube in a browser | Manual certificate install in Settings, with warnings | Not now |
| Browser extension | Few browsers | Only YouTube in that browser | Chrome has no extensions, and Firefox needs its store's signature | No |
| Modifying other apps or root access | One app, or everything | Possibly | Unsafe and invasive | No |

**The honest limit:** ads that an app serves from the same servers as its content can't be blocked this way. That includes the YouTube app, Instagram, Facebook and TikTok. No app can remove those on a normal, unrooted phone.

## How it works

The app uses Android's `VpnService`, but only as a local filter. **It's not a real VPN.** No traffic goes to any outside VPN server, and only name lookups pass through it.

1. The app creates a local tunnel with a fake DNS server address, and routes only that address into the tunnel. All other traffic, including video and web pages, goes straight to the network as normal.
2. Every app's name lookups arrive at the app as packets.
3. If the name or a parent domain is on the blocklist and not on the allowlist, the app answers "no such name".
4. Otherwise it forwards the lookup to the phone's real DNS server through a socket excluded from the tunnel, and passes the answer back.

**Automatic start:** after a restart, a boot receiver starts the filter again without asking, because Android remembers the VPN permission. The app also offers a shortcut to Android's "Always-on VPN" setting.

## Units

| Unit | Path | Purpose |
|---|---|---|
| Ad list | `rules-src/android-domains.txt` plus existing lists | Generated into `android ad/app/assets/` by `tools/build_rules.py` |
| Packet logic | `app/src/.../core/` | Plain Java, no Android classes, so it can be tested on the PC |
| Filter service | `FilterVpnService.java` | The tunnel, forwarding and foreground notification |
| Screen | `MainActivity.java` | One on/off switch, a blocked count and a link to Always-on VPN |
| Boot receiver | `BootReceiver.java` | Restarts the filter after a phone restart |
| Build script | `android ad/build.py` | Python standard library only, calling the SDK tools directly with no Gradle |
| Tool setup | `android ad/setup_tools.py` | Installs the tools inside `android ad/.tools/`, with nothing installed on Windows |

## Failure handling

- **Filter crashes:** Android removes the tunnel, so lookups return to the phone's normal DNS. Ads come back but the internet keeps working.
- **No real DNS server can be found:** lookups aren't answered until the network returns. There's no fallback to a public provider.
- **Network changes:** the real DNS server is looked up again on each change, such as moving from Wi-Fi to mobile data.
- **Private DNS set to a specific provider:** lookups can bypass the filter, so the app detects this and tells the user.
- **Another VPN:** Android allows only one at a time. Starting a different VPN turns this filter off.

## Testing

1. Python tests for generating the ad list.
2. Plain Java tests on the PC for packet parsing, matching and building answers.
3. An emulator test of the real app: blocked names fail, normal names resolve, pages still load, and the filter comes back after a restart.
4. A final check on the user's phone.

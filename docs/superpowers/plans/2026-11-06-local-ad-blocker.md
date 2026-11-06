# Local Ad Blocker Implementation Plan

> Executed inline in the session that wrote it, per the user's instruction to proceed on recommendations. Tasks therefore fix files, interfaces and test cases rather than repeating full source here; the code lands in each task's commit. Platform tasks start with a live probe because current page structures can't be known in advance.

**Goal:** A Manifest V3 extension for Edge and Chrome, built only from our own rules and code, that removes ads on YouTube and other platforms with no network use of its own.

**Architecture:** Hand-written rule sources compile into static `declarativeNetRequest` rules and CSS. Dynamically registered content scripts add response scrubbing, feed hiding and a video guard per site.

**Tech Stack:** Chromium MV3, plain JavaScript, Python 3.12 standard library.

**Spec:** `docs/superpowers/specs/2026-11-06-local-ad-blocker-design.md`

## Global Constraints

- No third-party lists, code, services or pip/npm packages.
- The extension makes no network requests of its own; extension CSP includes `connect-src 'self'`.
- Hooks return original data on any error.
- `python` is the interpreter name on this machine, and paths contain a space, so quote them.

---

### Task 1: Test harness

**Files:** Create `tests/harness/cdp.py`, `tests/harness/browser.py`, `tests/harness/__init__.py`, `tests/test_harness.py`

**Produces:**
- `Browser(extension_path=None, headless=True)` context manager launching Edge on a temp profile, with `new_page() -> Page`, `extension_id`, `service_worker_eval(js)`.
- `Page.fixture(url_regex, body, status=200, headers=None)`, `Page.goto(url)`, `Page.eval(js)`, `Page.wait_for(js, timeout)`, `Page.blocked_requests()`, `Page.requests()`.

**Tests:** fake `https://www.example.test` page is served and evaluated; extension service worker is detected; a DNR-blocked request is reported as blocked by client.

### Task 2: Rule compiler and our rule sources

**Files:** Create `tools/build_rules.py`, `rules-src/ad-domains.txt`, `rules-src/url-patterns.txt`, `rules-src/surrogates.txt`, `rules-src/cosmetic/generic.txt`, `rules-src/sites.json`, `tests/test_build_rules.py`

**Produces:** `extension/generated/network.json`, `extension/generated/css/*.css`, `extension/generated/sites.js`.

**Tests:** comments and blanks skipped; duplicates removed; invalid domains and URL hosts rejected; plain domains merge into one `requestDomains` rule; main frames are never blocked; third-party option maps to `domainType`; surrogate rules outrank block rules; rule IDs are unique; unsafe selectors containing `{` or `}` are rejected; first-party critical domains (google.com, youtube.com, googlevideo.com and similar) can't be listed.

### Task 3: Extension core

**Files:** Create `extension/manifest.json`, `extension/background.js`, `extension/content/isolated/generic.js`, `extension/surrogates/*.js`, `tests/test_blocking.py`

**Tests (hermetic):** ad-domain request blocked; ordinary request not blocked; generic selector hidden; IAB-sized cross-origin iframe hidden, same-origin iframe not; surrogate served for `gpt.js` so `googletag.cmd.push` runs; pausing a host disables blocking and content scripts there, resuming restores them.

### Task 4: Pop-up, picker and user rules

**Files:** Create `extension/popup/popup.html`, `popup.css`, `popup.js`, `extension/content/isolated/picker.js`, `extension/content/isolated/user-rules.js`, `tests/test_user_rules.py`

**Design:** use the `ui-ux-pro-max` skill before styling.

**Tests (hermetic):** saved rule hides its element on reload for that host only; clearing removes it; picker selector resolves to the clicked element; pop-up toggle changes pause state.

### Task 5: YouTube

**Files:** Create `extension/content/main/net-hooks.js`, `extension/content/isolated/video-guard.js`, `rules-src/cosmetic/youtube.txt`, `tests/test_youtube.py`, `tests/live/youtube_compare.py`

**Probe first:** capture player response keys and ad markers on the live site in a temp profile.

**Tests (hermetic):** inline `ytInitialPlayerResponse`, `fetch` and XHR player responses arrive with no ad keys and with video data intact; malformed JSON passes through untouched; response `url` and `status` are preserved; simulated `.ad-showing` player is muted and skipped, then unmuted.

**Live:** same videos with and without the extension; report ad state seen, playback progress and any enforcement dialog.

### Task 6: Twitch and video sites

**Files:** Modify `net-hooks.js`, `video-guard.js`; create `rules-src/cosmetic/twitch.txt`, `tests/test_twitch.py`

**Tests:** playlist with stitched-ad segments loses those segments; playlist with no ads passes through unchanged; ad label on the page mutes and hides the player, and its removal restores it.

### Task 7: Social feeds

**Files:** Create `extension/content/isolated/feed.js`, `rules-src/cosmetic/{facebook,instagram,x,reddit,tiktok,linkedin,pinterest}.txt`, `tests/test_feeds.py`; modify `net-hooks.js`

**Tests:** per platform, a fixture with one ad and one normal item hides or removes only the ad, including items added after load.

### Task 8: Search, shopping, audio and streaming

**Files:** Create `rules-src/cosmetic/{google,bing,duckduckgo,yahoo,amazon,ebay,spotify,soundcloud,dailymotion}.txt`, `extension/surrogates/ima3.js`, `tests/test_sites.py`; modify `rules-src/sites.json`, `video-guard.js`

**Tests:** per site, fixture ad hidden and organic result visible; IMA surrogate resumes content without an ad.

### Task 9: Local-only proof, docs and live breakage check

**Files:** Create `tests/test_local_only.py`, `tests/live/breakage_check.py`, `README.md`

**Tests:** manifest has CSP and no `update_url`; extension source starts no network requests outside the hooks' pass-through; no external script URLs; runtime capture of the service worker shows no requests; rule sources contain no provider attributions or imports.

### Task 10: Install and verify

User loads `extension/` in Edge and Chrome (Developer mode, Load unpacked). Verify on real profiles and report per-platform results, including what couldn't be verified.

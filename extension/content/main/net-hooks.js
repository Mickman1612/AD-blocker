// Removes ad data from responses the page already requested, before the page reads them.
// This runs in the page and never starts a request of its own. Any error returns the
// original data, so a bad rule can't break a site.
(() => {
  'use strict';

  const SITES = [
    {
      domains: ['youtube.com', 'youtube-nocookie.com', 'youtubekids.com'],
      urls: /\/youtubei\/v1\/|\/watch\?|\/playlist\?|\/shorts\//,
      globals: ['ytInitialPlayerResponse', 'ytInitialData', 'ytInitialReelWatchSequenceResponse'],
      // The "ad blockers aren't allowed" message stays in the data: without it, YouTube's player
      // refuses to play for flagged accounts ("Something went wrong", 282054944).
      dropKeys: ['adPlacements', 'adSlots', 'playerAds', 'adBreakHeartbeatParams'],
      dropItemKeys: [
        'adSlotRenderer', 'promotedSparklesWebRenderer', 'promotedVideoRenderer',
        'compactPromotedVideoRenderer', 'displayAdRenderer', 'inFeedAdLayoutRenderer',
        'searchPyvRenderer', 'bannerPromoRenderer', 'statementBannerRenderer',
      ],
      // Feed entries wrap the ad one level down.
      dropItem: (item) => {
        const content = item.richItemRenderer?.content ?? item.richSectionRenderer?.content;
        return Boolean(content?.adSlotRenderer || content?.statementBannerRenderer);
      },
    },
    {
      domains: ['x.com', 'twitter.com'],
      urls: /\/i\/api\/(graphql|2)\//,
      markers: ['promotedMetadata', 'promoted-tweet', 'promotedTweet'],
      dropItem: (item) => (typeof item.entryId === 'string' && item.entryId.startsWith('promoted'))
        || Boolean(item.content?.itemContent?.promotedMetadata
          || item.content?.promotedMetadata
          || item.item?.itemContent?.promotedMetadata),
    },
    {
      domains: ['tiktok.com'],
      urls: /\/api\/(recommend|explore|post|search)\//,
      markers: ['"isAd"'],
      dropItem: (item) => item.isAd === true,
    },
    {
      domains: ['instagram.com'],
      urls: /\/graphql\/query|\/api\/graphql|\/api\/v1\/feed\//,
      markers: ['"ad_id"', '"ad"'],
      dropItem: (item) => Boolean(item.ad || item.ad_id || item.media?.ad_id
        || item.node?.ad || item.node?.ad_id || item.node?.media?.ad_id),
    },
    {
      domains: ['facebook.com'],
      markers: ['SPONSORED', 'sponsored_data'],
      dropItem: (item) => item.category === 'SPONSORED' || item.node?.category === 'SPONSORED'
        || Boolean(item.sponsored_data || item.node?.sponsored_data),
    },
    {
      domains: ['twitch.tv'],
      urls: /\.m3u8/,
      rewrite: cleanPlaylist,
      workers: true,
    },
  ];

  // Twitch stitches ads into the stream playlist. Removing their segments means the
  // player never downloads them. This is passed to workers as source text, so it can't
  // use anything from the surrounding code.
  function cleanPlaylist(text) {
    if (!text.includes('#EXTM3U') || !/stitched-ad|X-TV-TWITCH-AD|,Amazon/i.test(text)) return text;
    const kept = [];
    const lines = text.split('\n');
    for (let index = 0; index < lines.length; index += 1) {
      const line = lines[index];
      if (line.startsWith('#EXT-X-DATERANGE') && /stitched-ad|twitch-ad/i.test(line)) continue;
      if (line.startsWith('#EXTINF') && !/,\s*live\s*$/i.test(line)) {
        if (kept.at(-1)?.startsWith('#EXT-X-PROGRAM-DATE-TIME')) kept.pop();
        index += 1; // The segment's address is on the next line.
        continue;
      }
      kept.push(line);
    }
    return kept.join('\n');
  }

  // Runs first inside each worker. Twitch's video player lives in one.
  function workerPrelude(clean) {
    const nativeFetch = self.fetch;
    self.fetch = async function fetch(input, init) {
      const response = await nativeFetch.call(self, input, init);
      const url = typeof input === 'string' ? input : input?.url ?? String(input);
      if (!/\.m3u8/.test(url)) return response;
      try {
        const text = await response.clone().text();
        const cleaned = clean(text);
        if (cleaned === text) return response;
        const replacement = new Response(cleaned, {
          status: response.status,
          statusText: response.statusText,
          headers: response.headers,
        });
        Object.defineProperty(replacement, 'url', { value: response.url });
        return replacement;
      } catch {
        return response;
      }
    };
  }

  const MAX_DEPTH = 64;
  const hostname = location.hostname.toLowerCase();
  const site = SITES.find(({ domains }) =>
    domains.some((domain) => hostname === domain || hostname.endsWith(`.${domain}`)));
  if (!site) return;

  const dropKeys = new Set(site.dropKeys ?? []);
  const dropItemKeys = site.dropItemKeys ?? [];
  const markers = [...dropKeys, ...dropItemKeys, ...(site.markers ?? [])];
  const nativeParse = JSON.parse;
  const nativeStringify = JSON.stringify;

  const hasMarker = (text) => markers.some((marker) => text.includes(marker));

  function isAdItem(item) {
    if (item === null || typeof item !== 'object') return false;
    if (dropItemKeys.some((key) => key in item)) return true;
    return site.dropItem ? site.dropItem(item) : false;
  }

  function scrub(value, depth = 0) {
    if (value === null || typeof value !== 'object' || depth > MAX_DEPTH) return value;
    if (Array.isArray(value)) {
      for (let index = value.length - 1; index >= 0; index -= 1) {
        if (isAdItem(value[index])) value.splice(index, 1);
        else scrub(value[index], depth + 1);
      }
      return value;
    }
    for (const key of Object.keys(value)) {
      if (dropKeys.has(key)) delete value[key];
      else scrub(value[key], depth + 1);
    }
    return value;
  }

  function scrubSafely(value) {
    try {
      return scrub(value);
    } catch {
      return value;
    }
  }

  // Some endpoints start the body with a prefix that has to survive the rewrite.
  function rewriteText(text) {
    if (site.rewrite) return site.rewrite(text);
    if (!hasMarker(text)) return text;
    const prefix = text.match(/^\)\]\}'\s*/)?.[0] ?? '';
    try {
      return prefix + nativeStringify(scrub(nativeParse(text.slice(prefix.length))));
    } catch {
      return text;
    }
  }

  function urlOf(input) {
    try {
      return new URL(input instanceof Request ? input.url : String(input), location.href).href;
    } catch {
      return '';
    }
  }

  const watched = (url) => site.urls?.test(url) ?? false;

  // --- JSON.parse ---
  JSON.parse = new Proxy(nativeParse, {
    apply(target, thisArg, args) {
      const result = Reflect.apply(target, thisArg, args);
      if (typeof args[0] === 'string' && hasMarker(args[0])) scrubSafely(result);
      return result;
    },
  });

  // --- fetch ---
  const nativeClone = Response.prototype.clone;

  // A new Response loses these, and pages sometimes check them.
  function dress(replacement, original) {
    Object.defineProperties(replacement, {
      url: { value: original.url },
      type: { value: original.type },
      redirected: { value: original.redirected },
      clone: { value: () => dress(nativeClone.call(replacement), original) },
    });
    return replacement;
  }

  async function rewriteResponse(response) {
    try {
      const text = await nativeClone.call(response).text();
      const rewritten = rewriteText(text);
      if (rewritten === text) return response;
      return dress(new Response(rewritten, {
        status: response.status,
        statusText: response.statusText,
        headers: response.headers,
      }), response);
    } catch {
      return response;
    }
  }

  if (site.urls) {
    window.fetch = new Proxy(window.fetch, {
      apply(target, thisArg, args) {
        const pending = Reflect.apply(target, thisArg, args);
        return watched(urlOf(args[0])) ? pending.then(rewriteResponse) : pending;
      },
    });

    // --- XMLHttpRequest ---
    const proto = XMLHttpRequest.prototype;
    const urls = new WeakMap();
    const rewrites = new WeakMap();
    const nativeOpen = proto.open;
    proto.open = new Proxy(nativeOpen, {
      apply(target, thisArg, args) {
        urls.set(thisArg, urlOf(args[1]));
        rewrites.delete(thisArg);
        return Reflect.apply(target, thisArg, args);
      },
    });

    const wrapGetter = (name) => {
      const descriptor = Object.getOwnPropertyDescriptor(proto, name);
      Object.defineProperty(proto, name, {
        ...descriptor,
        get() {
          const value = descriptor.get.call(this);
          if (this.readyState !== 4 || !watched(urls.get(this) ?? '')) return value;
          if (rewrites.has(this)) return rewrites.get(this);
          let result = value;
          if (typeof value === 'string') result = rewriteText(value);
          else if (value !== null && typeof value === 'object' && this.responseType === 'json') {
            result = scrubSafely(value);
          }
          rewrites.set(this, result);
          return result;
        },
      });
    };
    wrapGetter('response');
    wrapGetter('responseText');
  }

  // --- Workers ---
  if (site.workers) {
    const bootstrap = `(${workerPrelude})(${cleanPlaylist});`;
    window.Worker = new Proxy(window.Worker, {
      construct(target, args, newTarget) {
        try {
          if (args[1]?.type !== 'module') {
            const original = new URL(String(args[0]), location.href).href;
            const source = `${bootstrap}\nimportScripts(${nativeStringify(original)});`;
            const wrapped = URL.createObjectURL(new Blob([source], { type: 'text/javascript' }));
            return Reflect.construct(target, [wrapped, ...args.slice(1)], newTarget);
          }
        } catch {
          // Fall through and start the worker the page asked for.
        }
        return Reflect.construct(target, args, newTarget);
      },
    });
  }

  // --- Data the page writes inline, such as var ytInitialPlayerResponse = {...} ---
  for (const name of site.globals ?? []) {
    let stored = window[name];
    Object.defineProperty(window, name, {
      configurable: true,
      enumerable: true,
      get: () => stored,
      set(value) {
        stored = scrubSafely(value);
      },
    });
  }
})();

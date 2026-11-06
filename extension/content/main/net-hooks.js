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
      dropKeys: [
        'adPlacements', 'adSlots', 'playerAds', 'adBreakHeartbeatParams',
        'bkaEnforcementMessageViewModel', 'enforcementMessageViewModel',
      ],
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
  ];

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

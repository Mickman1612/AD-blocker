// Our stand-in for the Google Publisher Tag library. Accepts every call and shows no ads.
(() => {
  'use strict';
  const noop = () => {};
  // Unknown methods return this, so long call chains keep working.
  const chain = new Proxy(noop, {
    get: (_, key) => (key === 'then' || typeof key === 'symbol' ? undefined : chain),
    apply: () => chain,
  });
  const withChain = (known) => new Proxy(known, {
    get: (target, key) => (key in target ? target[key] : (key === 'then' || typeof key === 'symbol' ? undefined : chain)),
  });

  const pubads = withChain({
    getSlots: () => [],
    getTargeting: () => [],
    getTargetingKeys: () => [],
    addEventListener: () => pubads,
    removeEventListener: () => true,
  });
  const makeSlot = (path, sizes, id) => withChain({
    getSlotElementId: () => id ?? '',
    getAdUnitPath: () => path ?? '',
    getSizes: () => [],
    getTargeting: () => [],
    getTargetingKeys: () => [],
    getResponseInformation: () => null,
  });

  const queued = window.googletag?.cmd;
  const googletag = window.googletag ?? {};
  Object.assign(googletag, {
    apiReady: true,
    pubadsReady: true,
    pubads: () => pubads,
    companionAds: () => chain,
    content: () => chain,
    defineSlot: makeSlot,
    defineOutOfPageSlot: makeSlot,
    destroySlots: () => true,
    display: noop,
    enableServices: noop,
    getVersion: () => '',
    sizeMapping: () => chain,
    setConfig: noop,
    cmd: {
      push(...commands) {
        for (const command of commands) {
          try {
            command();
          } catch (error) {
            console.error(error);
          }
        }
        return commands.length;
      },
    },
  });
  window.googletag = googletag;
  if (Array.isArray(queued)) googletag.cmd.push(...queued);
})();

// Our stand-in for Amazon's bid library. Answers every bid request with no bids.
(() => {
  'use strict';
  const fetchBids = (_config, callback) => {
    if (typeof callback === 'function') setTimeout(() => callback([]), 0);
  };
  const queued = window.apstag?._Q;
  window.apstag = {
    init() {},
    fetchBids,
    setDisplayBids() {},
    targetingKeys: () => [],
    renderImp() {},
    _Q: [],
  };
  if (Array.isArray(queued)) {
    for (const [method, args] of queued) {
      if (method === 'f') fetchBids(...args);
    }
  }
})();

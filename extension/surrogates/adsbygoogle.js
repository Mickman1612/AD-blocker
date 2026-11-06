// Our stand-in for the AdSense loader. Accepts pushes and marks slots as finished.
(() => {
  'use strict';
  const finishSlots = () => {
    for (const slot of document.querySelectorAll('ins.adsbygoogle:not([data-adsbygoogle-status])')) {
      slot.setAttribute('data-adsbygoogle-status', 'done');
    }
  };
  window.adsbygoogle = {
    loaded: true,
    push() {
      finishSlots();
      return 1;
    },
  };
  finishSlots();
})();

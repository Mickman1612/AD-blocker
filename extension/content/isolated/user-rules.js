// Applies what the user chose to hide on this site. The service worker inserts the
// styles, because a page's security policy can block styles added from here.
(async () => {
  'use strict';
  const host = location.hostname.toLowerCase().replace(/^www\./, '');
  if (!host) return;
  const { userRules = {} } = await chrome.storage.local.get('userRules');
  if (userRules[host]?.length) {
    await chrome.runtime.sendMessage({ type: 'apply-rules', host });
  }
})();

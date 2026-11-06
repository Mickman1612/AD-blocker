// Hides feed items that carry an ad marker or label. Feeds load as you scroll and
// items fill in late, so this re-checks whenever the page changes.
(() => {
  'use strict';

  const SITES = [
    {
      host: /(^|\.)facebook\.com$/,
      items: '[role="article"],[data-pagelet^="FeedUnit"]',
      markers: 'a[href^="/ads/"],a[href*="/ads/about"],a[aria-label="Sponsored"]',
      labels: ['Sponsored'],
    },
    { host: /(^|\.)instagram\.com$/, items: 'article', labels: ['Sponsored'] },
    {
      host: /(^|\.)linkedin\.com$/,
      items: '.feed-shared-update-v2,[data-id^="urn:li:activity"],[data-urn^="urn:li:activity"]',
      labels: ['Promoted', 'Sponsored'],
    },
    {
      host: /(^|\.)pinterest\.[a-z.]+$/,
      items: '[data-grid-item]',
      markers: '[data-test-id*="promoted" i]',
      labels: ['Promoted by', 'Promoted', 'Sponsored'],
    },
    {
      host: /(^|\.)tiktok\.com$/,
      items: '[data-e2e="recommend-list-item-container"],article',
      labels: ['Sponsored', 'Ad'],
    },
    {
      host: /(^|\.)(x|twitter)\.com$/,
      items: '[data-testid="cellInnerDiv"]',
      markers: '[data-testid="placementTracking"]',
      labels: ['Ad', 'Promoted'],
    },
    { host: /(^|\.)reddit\.com$/, items: 'article', markers: 'shreddit-ad-post,shreddit-dynamic-ad-link' },
    { host: /(^|\.)ebay\.[a-z.]+$/, items: '.s-item,.s-card', labels: ['Sponsored'] },
    {
      host: /(^|\.)amazon\.[a-z.]+$/,
      items: '[data-component-type="s-search-result"]',
      labels: ['Sponsored'],
    },
  ];

  const MAX_LABEL_LENGTH = 24;
  const CHECK_DELAY_MS = 150;
  const site = SITES.find(({ host }) => host.test(location.hostname.toLowerCase()));
  if (!site) return;

  const labels = new Set(site.labels ?? []);

  function hasLabel(item) {
    if (!labels.size) return false;
    for (const element of item.querySelectorAll('span,a,div,small,p')) {
      const text = element.textContent;
      if (text.length <= MAX_LABEL_LENGTH && labels.has(text.trim())) return true;
    }
    return false;
  }

  function check() {
    for (const item of document.querySelectorAll(site.items)) {
      if (item.style.display === 'none') continue;
      if ((site.markers && item.querySelector(site.markers)) || hasLabel(item)) {
        item.style.setProperty('display', 'none', 'important');
      }
    }
  }

  let timer = null;
  function schedule() {
    if (timer === null) {
      timer = setTimeout(() => {
        timer = null;
        check();
      }, CHECK_DELAY_MS);
    }
  }

  function start() {
    schedule();
    new MutationObserver(schedule).observe(document.documentElement, { childList: true, subtree: true });
  }

  if (document.documentElement) start();
  else document.addEventListener('readystatechange', start, { once: true });
})();

// Heuristics that catch ads from networks missing from our rules. Runs on every page.
(() => {
  'use strict';

  const AD_SIZES = new Set([
    '120x600', '125x125', '160x600', '180x150', '200x200', '234x60', '250x250', '300x50',
    '300x100', '300x250', '300x600', '320x50', '320x100', '336x280', '468x60', '728x90',
    '970x90', '970x250',
  ]);

  // Embeds people want, which can sit at an ad size. Compared against the end of the hostname.
  const SAFE_EMBEDS = [
    'youtube.com', 'youtube-nocookie.com', 'vimeo.com', 'dailymotion.com', 'twitch.tv',
    'spotify.com', 'soundcloud.com', 'google.com', 'recaptcha.net', 'hcaptcha.com',
    'cloudflare.com', 'stripe.com', 'paypal.com', 'twitter.com', 'x.com', 'facebook.com',
    'instagram.com', 'tiktok.com', 'reddit.com', 'linkedin.com', 'github.com',
  ];

  const AD_LABELS = new Set([
    'advertisement', 'advertisements', 'advertising', 'advert', 'adverts', 'ad', 'ads',
    'sponsored', 'sponsored ad', 'sponsored ads', 'sponsored content', 'promoted',
    'anzeige', 'werbung', 'publicité', 'publicidad', 'anuncio', 'pubblicità', 'विज्ञापन',
  ]);

  // Ad slots that our style sheet hides. Their wrappers are often left as empty gaps.
  const SLOT_SELECTOR = 'ins.adsbygoogle,[id^="div-gpt-ad"],[id^="google_ads_iframe"],[data-ad-slot],amp-ad';
  const MAX_COLLAPSE_LEVELS = 3;
  const MAX_LABEL_BOX_TEXT = 40;
  const STOP_TAGS = new Set(['BODY', 'HTML', 'MAIN', 'ARTICLE', 'NAV', 'HEADER', 'FOOTER']);
  const MEDIA_SELECTOR = 'img,video,audio,canvas,svg,picture,iframe,object,embed,input,button,textarea,select';

  const hide = (element) => element.style.setProperty('display', 'none', 'important');
  const isHidden = (element) => getComputedStyle(element).display === 'none';

  function hostOf(url) {
    try {
      return new URL(url, location.href).hostname.toLowerCase();
    } catch {
      return '';
    }
  }

  const endsWithDomain = (host, domain) => host === domain || host.endsWith(`.${domain}`);

  // Close enough to a registrable domain for telling first-party from third-party.
  function siteOf(host) {
    const parts = host.split('.');
    const shortSecond = parts.length > 2 && parts.at(-2).length <= 3 && parts.at(-1).length === 2;
    return parts.slice(shortSecond ? -3 : -2).join('.');
  }

  function sizeOf(frame) {
    const attrWidth = parseInt(frame.getAttribute('width'), 10);
    const attrHeight = parseInt(frame.getAttribute('height'), 10);
    if (attrWidth && attrHeight) return `${attrWidth}x${attrHeight}`;
    const box = frame.getBoundingClientRect();
    return `${Math.round(box.width)}x${Math.round(box.height)}`;
  }

  function looksLikeAdFrame(frame) {
    if (!AD_SIZES.has(sizeOf(frame))) return false;
    const src = frame.getAttribute('src');
    if (!src || src === 'about:blank') {
      // Ad scripts often fill a source-less frame. Editors and widgets rarely turn off scrolling.
      return frame.getAttribute('scrolling') === 'no' || frame.hasAttribute('marginwidth');
    }
    const host = hostOf(src);
    if (!host || siteOf(host) === siteOf(location.hostname)) return false;
    return !SAFE_EMBEDS.some((domain) => endsWithDomain(host, domain));
  }

  function hasVisibleContent(element) {
    for (const child of element.querySelectorAll(MEDIA_SELECTOR)) {
      if (!isHidden(child)) return true;
    }
    return element.textContent.trim().length > 0 && hasVisibleText(element);
  }

  function hasVisibleText(element) {
    for (const node of element.childNodes) {
      if (node.nodeType === Node.TEXT_NODE && node.nodeValue.trim()) return true;
      if (node.nodeType === Node.ELEMENT_NODE && !isHidden(node) && hasVisibleText(node)) return true;
    }
    return false;
  }

  function collapseWrappers(element) {
    let current = element.parentElement;
    for (let level = 0; current && level < MAX_COLLAPSE_LEVELS; level += 1) {
      if (STOP_TAGS.has(current.tagName) || hasVisibleContent(current)) return;
      hide(current);
      current = current.parentElement;
    }
  }

  function checkFrames(root) {
    for (const frame of root.querySelectorAll('iframe')) {
      if (!isHidden(frame) && looksLikeAdFrame(frame)) {
        hide(frame);
        collapseWrappers(frame);
      }
    }
  }

  function checkSlots(root) {
    for (const slot of root.querySelectorAll(SLOT_SELECTOR)) {
      if (isHidden(slot)) collapseWrappers(slot);
    }
  }

  function checkLabels(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const labels = [];
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const text = node.nodeValue.trim().toLowerCase();
      if (text.length <= 20 && AD_LABELS.has(text)) labels.push(node.parentElement);
    }
    for (const label of labels) {
      if (!label) continue;
      const box = findLabelBox(label);
      if (box) {
        hide(box);
        collapseWrappers(box);
      }
    }
  }

  // The nearest container holding only the label and nothing a reader would want.
  function findLabelBox(label) {
    let best = null;
    let current = label;
    for (let level = 0; current && level < MAX_COLLAPSE_LEVELS; level += 1) {
      if (STOP_TAGS.has(current.tagName)) break;
      if (current.textContent.trim().length > MAX_LABEL_BOX_TEXT) break;
      if ([...current.querySelectorAll(MEDIA_SELECTOR)].some((el) => !isHidden(el))) break;
      best = current;
      current = current.parentElement;
    }
    return best;
  }

  function scan(root) {
    checkFrames(root);
    checkSlots(root);
    checkLabels(root);
  }

  let pending = new Set();
  let scheduled = false;

  function flush() {
    scheduled = false;
    const roots = pending;
    pending = new Set();
    for (const root of roots) {
      if (root.isConnected) scan(root);
    }
  }

  function schedule(root) {
    pending.add(root);
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => setTimeout(flush, 0));
  }

  function start() {
    schedule(document.documentElement);
    new MutationObserver((records) => {
      for (const record of records) {
        for (const node of record.addedNodes) {
          if (node.nodeType === Node.ELEMENT_NODE) schedule(node.parentElement ?? node);
        }
      }
    }).observe(document.documentElement, { childList: true, subtree: true });
    // Frames and slots often get their final size only after the page has loaded.
    addEventListener('load', () => schedule(document.documentElement), { once: true });
  }

  if (document.documentElement) start();
  else document.addEventListener('readystatechange', start, { once: true });
})();

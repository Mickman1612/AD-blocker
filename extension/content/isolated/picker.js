// Injected when the user chooses "Hide something on this page": highlight what's under
// the pointer, hide what they click, and remember it for this site.
(() => {
  'use strict';
  if (document.querySelector('[data-local-ad-blocker-picker]')) return;

  const TOP_LAYER = '2147483647';
  const host = document.createElement('div');
  host.setAttribute('data-local-ad-blocker-picker', '');
  Object.assign(host.style, { position: 'fixed', inset: '0', pointerEvents: 'none', zIndex: TOP_LAYER });
  const shadow = host.attachShadow({ mode: 'closed' });

  const highlight = document.createElement('div');
  Object.assign(highlight.style, {
    position: 'fixed',
    display: 'none',
    outline: '2px solid #dc2626',
    background: 'rgba(220, 38, 38, 0.2)',
    pointerEvents: 'none',
  });

  const hint = document.createElement('div');
  hint.textContent = 'Click what you want to hide. Press Esc to cancel.';
  hint.setAttribute('role', 'status');
  Object.assign(hint.style, {
    position: 'fixed',
    top: '12px',
    left: '50%',
    transform: 'translateX(-50%)',
    padding: '8px 14px',
    borderRadius: '8px',
    background: '#0f172a',
    color: '#f1f5f9',
    font: '14px/1.4 "Segoe UI", system-ui, sans-serif',
    pointerEvents: 'none',
  });

  shadow.append(highlight, hint);
  document.documentElement.append(host);

  // Class names that look generated change on every build, so a rule using them wouldn't last.
  const isStable = (token) => /^[A-Za-z_-][\w-]*$/.test(token) && token.length < 40 && !/\d{4,}/.test(token);

  function describe(element) {
    if (element.id && isStable(element.id)) return `#${CSS.escape(element.id)}`;
    const classes = [...element.classList].filter(isStable).slice(0, 2)
      .map((name) => `.${CSS.escape(name)}`).join('');
    const base = element.localName + classes;
    const parent = element.parentElement;
    if (!parent) return base;
    if ([...parent.children].filter((child) => child.matches(base)).length === 1) return base;
    const sameTag = [...parent.children].filter((child) => child.localName === element.localName);
    return `${base}:nth-of-type(${sameTag.indexOf(element) + 1})`;
  }

  // The shortest path up the page that points at this element and nothing else.
  function selectorFor(element) {
    const parts = [];
    for (let current = element; current && current !== document.documentElement; current = current.parentElement) {
      parts.unshift(describe(current));
      const selector = parts.join(' > ');
      const matches = document.querySelectorAll(selector);
      if (matches.length === 1 && matches[0] === element) return selector;
    }
    return parts.join(' > ');
  }

  function show(event) {
    const target = event.target;
    if (!(target instanceof Element) || target === host) return;
    const box = target.getBoundingClientRect();
    Object.assign(highlight.style, {
      display: 'block',
      left: `${box.left}px`,
      top: `${box.top}px`,
      width: `${box.width}px`,
      height: `${box.height}px`,
    });
  }

  function swallow(event) {
    event.preventDefault();
    event.stopImmediatePropagation();
  }

  function finish() {
    removeEventListener('mousemove', show, true);
    removeEventListener('keydown', onKey, true);
    for (const type of ['mousedown', 'mouseup', 'pointerdown', 'pointerup', 'auxclick']) {
      removeEventListener(type, swallow, true);
    }
    // The click that picked something has to be absorbed too, so this one goes last.
    removeEventListener('click', onClick, true);
    host.remove();
  }

  function onKey(event) {
    if (event.key === 'Escape') {
      swallow(event);
      finish();
    }
  }

  function onClick(event) {
    swallow(event);
    const target = event.target;
    if (!(target instanceof Element)) return;
    const selector = selectorFor(target);
    target.style.setProperty('display', 'none', 'important');
    chrome.runtime.sendMessage({
      type: 'save-rule',
      host: location.hostname.toLowerCase().replace(/^www\./, ''),
      selector,
    });
    finish();
  }

  addEventListener('mousemove', show, true);
  addEventListener('keydown', onKey, true);
  for (const type of ['mousedown', 'mouseup', 'pointerdown', 'pointerup', 'auxclick']) {
    addEventListener(type, swallow, true);
  }
  addEventListener('click', onClick, true);
})();

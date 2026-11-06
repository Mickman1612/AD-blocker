// Registers page scripts and handles pause-per-site. Makes no network requests.
import { SITES } from './generated/sites.js';

const PAUSE_PRIORITY = 10; // Must outrank every static rule, including surrogate redirects.
const HOST_RE = /^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$/;
const MAX_SELECTOR_LENGTH = 1000;

const normalizeHost = (host) => String(host ?? '').trim().toLowerCase().replace(/^www\./, '');

async function getPaused() {
  const { paused = [] } = await chrome.storage.local.get('paused');
  return paused;
}

function excludesFor(paused) {
  return paused.flatMap((host) => [`*://${host}/*`, `*://*.${host}/*`]);
}

function scriptsFor(site, excludeMatches) {
  const base = {
    matches: site.matches,
    excludeMatches,
    allFrames: true,
    matchOriginAsFallback: true,
    runAt: 'document_start',
    persistAcrossSessions: true,
  };
  const scripts = [];
  if (site.css) {
    scripts.push({ ...base, id: `${site.id}-css`, css: [`generated/css/${site.css}.css`] });
  }
  if (site.hooks) {
    scripts.push({ ...base, id: `${site.id}-hooks`, js: ['content/main/net-hooks.js'], world: 'MAIN' });
  }
  const isolated = [
    site.generic && 'content/isolated/generic.js',
    site.generic && 'content/isolated/user-rules.js',
    site.guard && 'content/isolated/video-guard.js',
    site.feed && 'content/isolated/feed.js',
  ].filter(Boolean);
  if (isolated.length) {
    scripts.push({ ...base, id: `${site.id}-isolated`, js: isolated });
  }
  return scripts;
}

async function syncRules(paused) {
  const existing = await chrome.declarativeNetRequest.getDynamicRules();
  await chrome.declarativeNetRequest.updateDynamicRules({
    removeRuleIds: existing.map((rule) => rule.id),
    addRules: paused.map((host, index) => ({
      id: index + 1,
      priority: PAUSE_PRIORITY,
      action: { type: 'allowAllRequests' },
      condition: { requestDomains: [host], resourceTypes: ['main_frame', 'sub_frame'] },
    })),
  });
}

async function syncScripts(paused) {
  const excludes = excludesFor(paused);
  await chrome.scripting.unregisterContentScripts();
  await chrome.scripting.registerContentScripts(SITES.flatMap((site) => scriptsFor(site, excludes)));
}

// Changes run one at a time, because re-registering scripts can't overlap.
let queue = Promise.resolve();
function enqueue(task) {
  const run = queue.then(task);
  queue = run.catch((error) => console.error('Local Ad Blocker:', error));
  return run;
}

function applyAll() {
  return enqueue(async () => {
    const paused = await getPaused();
    await syncRules(paused);
    await syncScripts(paused);
    await chrome.declarativeNetRequest.setExtensionActionOptions({ displayActionCountAsBadgeText: true });
  });
}

function setPaused(host, shouldPause) {
  return enqueue(async () => {
    const paused = new Set(await getPaused());
    if (shouldPause) paused.add(host); else paused.delete(host);
    const list = [...paused];
    await chrome.storage.local.set({ paused: list });
    await syncRules(list);
    await syncScripts(list);
    return { paused: shouldPause };
  });
}

async function getUserRules() {
  const { userRules = {} } = await chrome.storage.local.get('userRules');
  return userRules;
}

const isSafeSelector = (selector) => typeof selector === 'string' && selector.length > 0
  && selector.length <= MAX_SELECTOR_LENGTH && !/[{}<]/.test(selector);

function saveRule(host, selector) {
  return enqueue(async () => {
    const userRules = await getUserRules();
    userRules[host] = [...new Set([...(userRules[host] ?? []), selector])];
    await chrome.storage.local.set({ userRules });
    return { ruleCount: userRules[host].length };
  });
}

function clearRules(host) {
  return enqueue(async () => {
    const userRules = await getUserRules();
    delete userRules[host];
    await chrome.storage.local.set({ userRules });
    return { ruleCount: 0 };
  });
}

async function applyRules(host, sender) {
  const rules = (await getUserRules())[host] ?? [];
  if (!rules.length || !sender.tab) return { applied: 0 };
  await chrome.scripting.insertCSS({
    target: { tabId: sender.tab.id, frameIds: [sender.frameId] },
    origin: 'USER',
    css: rules.map((selector) => `${selector}{display:none!important}`).join('\n'),
  });
  return { applied: rules.length };
}

async function handleMessage(message, sender) {
  const host = normalizeHost(message.host);
  if (!HOST_RE.test(host)) return { error: 'bad host' };
  switch (message.type) {
    case 'get-state':
      return {
        paused: (await getPaused()).includes(host),
        ruleCount: (await getUserRules())[host]?.length ?? 0,
      };
    case 'set-paused':
      return setPaused(host, Boolean(message.paused));
    case 'save-rule':
      if (!isSafeSelector(message.selector)) return { error: 'bad selector' };
      return saveRule(host, message.selector);
    case 'clear-rules':
      return clearRules(host);
    case 'apply-rules':
      return applyRules(host, sender);
    default:
      return { error: 'unknown message' };
  }
}

chrome.runtime.onInstalled.addListener(applyAll);
chrome.runtime.onStartup.addListener(applyAll);
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id) return false;
  handleMessage(message, sender).then(sendResponse, (error) => sendResponse({ error: String(error) }));
  return true;
});

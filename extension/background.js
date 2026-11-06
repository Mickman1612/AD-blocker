// Registers page scripts and handles pause-per-site. Makes no network requests.
import { SITES } from './generated/sites.js';

const PAUSE_PRIORITY = 10; // Must outrank every static rule, including surrogate redirects.
const HOST_RE = /^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$/;

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

async function handleMessage(message) {
  const host = normalizeHost(message.host);
  if (!HOST_RE.test(host)) return { error: 'bad host' };
  switch (message.type) {
    case 'get-state':
      return { paused: (await getPaused()).includes(host) };
    case 'set-paused':
      return setPaused(host, Boolean(message.paused));
    default:
      return { error: 'unknown message' };
  }
}

chrome.runtime.onInstalled.addListener(applyAll);
chrome.runtime.onStartup.addListener(applyAll);
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id) return false;
  handleMessage(message).then(sendResponse, (error) => sendResponse({ error: String(error) }));
  return true;
});

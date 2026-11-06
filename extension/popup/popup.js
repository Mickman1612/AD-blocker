const toggle = document.getElementById('toggle');
const pick = document.getElementById('pick');
const clear = document.getElementById('clear');
const hostLabel = document.getElementById('host');
const status = document.getElementById('status');

const normalizeHost = (hostname) => hostname.toLowerCase().replace(/^www\./, '');

function hostOf(tab) {
  try {
    const url = new URL(tab?.url ?? '');
    return /^https?:$/.test(url.protocol) ? normalizeHost(url.hostname) : null;
  } catch {
    return null;
  }
}

function render({ paused, ruleCount }) {
  toggle.setAttribute('aria-checked', String(!paused));
  status.textContent = paused ? 'Paused. Ads can appear on this site.' : 'On. Ads are blocked on this site.';
  clear.hidden = ruleCount === 0;
  clear.textContent = ruleCount === 1
    ? 'Show the 1 item you hid'
    : `Show the ${ruleCount} items you hid`;
}

async function start() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const host = hostOf(tab);

  if (!host) {
    hostLabel.textContent = "Ad blocking can't run on this page.";
    toggle.disabled = true;
    pick.disabled = true;
    status.textContent = '';
    return;
  }

  hostLabel.textContent = host;
  let state = await chrome.runtime.sendMessage({ type: 'get-state', host });
  render(state);

  toggle.addEventListener('click', async () => {
    toggle.disabled = true;
    const paused = toggle.getAttribute('aria-checked') === 'true';
    await chrome.runtime.sendMessage({ type: 'set-paused', host, paused });
    state = await chrome.runtime.sendMessage({ type: 'get-state', host });
    render(state);
    toggle.disabled = false;
    await chrome.tabs.reload(tab.id);
  });

  pick.addEventListener('click', async () => {
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ['content/isolated/picker.js'],
    });
    window.close();
  });

  clear.addEventListener('click', async () => {
    await chrome.runtime.sendMessage({ type: 'clear-rules', host });
    state = await chrome.runtime.sendMessage({ type: 'get-state', host });
    render(state);
    await chrome.tabs.reload(tab.id);
  });
}

start().catch((error) => {
  status.textContent = 'Something went wrong. Close this and try again.';
  console.error(error);
}).finally(() => {
  document.body.dataset.ready = 'true';
});

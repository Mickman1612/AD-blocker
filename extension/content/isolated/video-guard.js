// The safety net for video ads that get through: while a player reports an ad, make it
// silent and invisible and get past it as fast as possible, then put everything back.
(() => {
  'use strict';

  // For players where seeking or changing speed breaks playback, or that are live.
  const silentOnly = (domains, marker, skip = []) => ({
    domains,
    player: 'body',
    isAd: () => Boolean(document.querySelector(marker)),
    skip,
    fastForward: false,
  });

  const SITES = [
    silentOnly(['twitch.tv'], '[data-a-target="video-ad-label"],[data-a-target="video-ad-countdown"]'),
    silentOnly(['netflix.com'], '[data-uia="ads-info-container"],.watch-video--adsInfo-container'),
    silentOnly(
      ['primevideo.com', 'amazon.com', 'amazon.co.uk', 'amazon.com.au', 'amazon.in', 'amazon.ca', 'amazon.de'],
      '.atvwebplayersdk-ad-timer,.atvwebplayersdk-adtimeindicator-text,.adSkipButton',
      ['.adSkipButton'],
    ),
    silentOnly(['hulu.com'], '.AdUnitView,[data-automationid="ad-timer"]'),
    silentOnly(['peacocktv.com'], '.ad-countdown__container,[data-testid="ad-countdown"]'),
    silentOnly(['max.com'], '[data-testid="ad-countdown"],[data-testid="player-ux-ad-badge"]'),
    silentOnly(['disneyplus.com'], '[data-testid="ad-badge-overlay"],.ad-badge-overlay'),
    silentOnly(['tubitv.com', 'pluto.tv', 'crunchyroll.com', 'dailymotion.com'], '[data-testid="ad-badge"],.ad-showing'),
    silentOnly(['spotify.com'], '[data-testid="context-item-info-ad-title"],[data-testid="ad-link"]'),
    {
      domains: ['youtube.com', 'youtube-nocookie.com', 'youtubekids.com'],
      player: '.html5-video-player',
      isAd: (player) => player.classList.contains('ad-showing')
        || player.classList.contains('ad-interrupting'),
      skip: [
        '.ytp-skip-ad-button', '.ytp-ad-skip-button', '.ytp-ad-skip-button-modern',
        '.ytp-ad-skip-button-slot button', '.ytp-ad-overlay-close-button',
      ],
      // The "ad blockers aren't allowed" pop-up pauses the video behind it. Its data can't be
      // removed, because the player then refuses to play, so close it and carry on. Only ever
      // its close button: never "Allow YouTube Ads".
      warning: {
        message: 'ytd-enforcement-message-view-model',
        close: 'button[aria-label="Close"], #dismiss-button button',
      },
    },
  ];

  const FAST_RATE = 16;
  const CHECK_MS = 250;
  const SEEK_MARGIN_S = 0.1;
  const hostname = location.hostname.toLowerCase();
  const site = SITES.find(({ domains }) =>
    domains.some((domain) => hostname === domain || hostname.endsWith(`.${domain}`)));
  if (!site) return;

  const saved = new WeakMap();
  const observed = new WeakSet();

  function passAd(player, video) {
    if (!saved.has(video)) {
      saved.set(video, {
        muted: video.muted,
        rate: video.playbackRate,
        opacity: video.style.opacity,
      });
    }
    video.muted = true;
    video.style.opacity = '0';
    if (site.fastForward !== false) {
      try {
        video.playbackRate = FAST_RATE;
      } catch {
        // Some players refuse fast rates. Seeking below still applies.
      }
      seekToEnd(video);
    }
    for (const selector of site.skip ?? []) {
      for (const button of player.querySelectorAll(selector)) button.click();
    }
  }

  // Seeking media that can't seek restarts it, so the ad would never end.
  function seekToEnd(video) {
    const ranges = video.seekable;
    if (!ranges.length) return;
    const end = ranges.end(ranges.length - 1);
    if (Number.isFinite(end) && end - video.currentTime > SEEK_MARGIN_S) video.currentTime = end;
  }

  function restore(video) {
    const state = saved.get(video);
    if (!state) return;
    saved.delete(video);
    video.muted = state.muted;
    video.playbackRate = state.rate;
    video.style.opacity = state.opacity;
  }

  function checkPlayer(player) {
    const video = player.querySelector('video, audio');
    if (!video) return;
    if (site.isAd(player)) passAd(player, video);
    else restore(video);
  }

  const closedWarnings = new WeakSet();
  let resumeAfterWarning = false;

  function isOpen(message) {
    const dialog = message.closest('tp-yt-paper-dialog') ?? message;
    return dialog.getAttribute('aria-hidden') !== 'true' && dialog.style.display !== 'none';
  }

  function closeWarning() {
    for (const message of document.querySelectorAll(site.warning.message)) {
      if (!isOpen(message)) {
        closedWarnings.delete(message); // So it's closed again if the page reopens it.
        continue;
      }
      if (closedWarnings.has(message)) continue;
      closedWarnings.add(message);
      message.querySelector(site.warning.close)?.click();
      resumeAfterWarning = true;
    }
    if (!resumeAfterWarning) return;
    const video = document.querySelector(`${site.player} video`);
    if (!video) return;
    // Only once: any later pause is the viewer's own.
    resumeAfterWarning = false;
    if (video.paused) video.play().catch(() => {});
  }

  function check() {
    if (site.warning) closeWarning();
    for (const player of document.querySelectorAll(site.player)) {
      if (!observed.has(player)) {
        observed.add(player);
        // React the moment the ad ends, so normal video never plays at high speed.
        new MutationObserver(() => checkPlayer(player))
          .observe(player, { attributes: true, attributeFilter: ['class'] });
      }
      checkPlayer(player);
    }
  }

  setInterval(check, CHECK_MS);
})();

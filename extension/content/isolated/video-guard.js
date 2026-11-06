// The safety net for video ads that get through: while a player reports an ad, make it
// silent and invisible and get past it as fast as possible, then put everything back.
(() => {
  'use strict';

  const SITES = [
    {
      domains: ['youtube.com', 'youtube-nocookie.com', 'youtubekids.com'],
      player: '.html5-video-player',
      isAd: (player) => player.classList.contains('ad-showing')
        || player.classList.contains('ad-interrupting'),
      skip: [
        '.ytp-skip-ad-button', '.ytp-ad-skip-button', '.ytp-ad-skip-button-modern',
        '.ytp-ad-skip-button-slot button', '.ytp-ad-overlay-close-button',
      ],
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
    try {
      video.playbackRate = FAST_RATE;
    } catch {
      // Some players refuse fast rates. Seeking below still applies.
    }
    seekToEnd(video);
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
    const video = player.querySelector('video');
    if (!video) return;
    if (site.isAd(player)) passAd(player, video);
    else restore(video);
  }

  function check() {
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

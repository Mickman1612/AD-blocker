// Our stand-in for Google's IMA video ad library. It tells the player there are no ads,
// so the show starts straight away.
(() => {
  'use strict';

  class EventHost {
    constructor() {
      this.listeners = new Map();
    }

    addEventListener(types, listener) {
      for (const type of [].concat(types)) {
        if (!this.listeners.has(type)) this.listeners.set(type, new Set());
        this.listeners.get(type).add(listener);
      }
    }

    removeEventListener(types, listener) {
      for (const type of [].concat(types)) this.listeners.get(type)?.delete(listener);
    }

    dispatch(type, event) {
      for (const listener of [...(this.listeners.get(type) ?? [])]) {
        try {
          listener(event);
        } catch (error) {
          console.error(error);
        }
      }
    }
  }

  const AdEvent = {
    Type: {
      AD_BREAK_READY: 'adBreakReady',
      AD_METADATA: 'adMetadata',
      ALL_ADS_COMPLETED: 'allAdsCompleted',
      CLICK: 'click',
      COMPLETE: 'complete',
      CONTENT_PAUSE_REQUESTED: 'contentPauseRequested',
      CONTENT_RESUME_REQUESTED: 'contentResumeRequested',
      DURATION_CHANGE: 'durationChange',
      FIRST_QUARTILE: 'firstQuartile',
      IMPRESSION: 'impression',
      LOADED: 'loaded',
      LOG: 'log',
      MIDPOINT: 'midpoint',
      PAUSED: 'pause',
      RESUMED: 'resume',
      SKIPPED: 'skip',
      STARTED: 'start',
      THIRD_QUARTILE: 'thirdQuartile',
      USER_CLOSE: 'userClose',
      VOLUME_CHANGED: 'volumeChange',
      VOLUME_MUTED: 'mute',
    },
  };
  const AdErrorEvent = { Type: { AD_ERROR: 'adError' } };
  const AdsManagerLoadedEvent = { Type: { ADS_MANAGER_LOADED: 'adsManagerLoaded' } };

  class AdsManager extends EventHost {
    init() {}

    start() {
      setTimeout(() => {
        this.dispatch(AdEvent.Type.CONTENT_RESUME_REQUESTED, { type: AdEvent.Type.CONTENT_RESUME_REQUESTED });
        this.dispatch(AdEvent.Type.ALL_ADS_COMPLETED, { type: AdEvent.Type.ALL_ADS_COMPLETED });
      }, 0);
    }

    pause() {}
    resume() {}
    stop() {}
    skip() {}
    destroy() {}
    discardAdBreak() {}
    resize() {}
    collapse() {}
    expand() {}
    focus() {}
    setVolume() {}
    updateAdsRenderingSettings() {}
    configureAdsManager() {}
    getAdSkippableState() { return false; }
    getCuePoints() { return []; }
    getCurrentAd() { return null; }
    getRemainingTime() { return 0; }
    getVolume() { return 1; }
    isCustomClickTrackingUsed() { return false; }
    isCustomPlaybackUsed() { return false; }
  }

  class AdsLoader extends EventHost {
    requestAds() {
      setTimeout(() => {
        const manager = new AdsManager();
        this.dispatch(AdsManagerLoadedEvent.Type.ADS_MANAGER_LOADED, {
          type: AdsManagerLoadedEvent.Type.ADS_MANAGER_LOADED,
          getAdsManager: () => manager,
          getUserRequestContext: () => ({}),
        });
      }, 0);
    }

    contentComplete() {}
    destroy() {}
    getSettings() { return settings; }
    getVersion() { return ima.VERSION; }
  }

  class AdDisplayContainer {
    initialize() {}
    destroy() {}
  }

  class AdsRequest {
    setAdWillAutoPlay() {}
    setAdWillPlayMuted() {}
    setContinuousPlayback() {}
  }

  class AdsRenderingSettings {}
  class CompanionAdSelectionSettings {}

  // Settings has many setters and pages call whichever ones they like.
  const settings = new Proxy({}, {
    get: (_, key) => {
      if (key === 'then' || typeof key === 'symbol') return undefined;
      if (String(key).startsWith('get')) return () => undefined;
      return () => undefined;
    },
  });

  const ima = {
    VERSION: '3.0.0',
    AdDisplayContainer,
    AdError: { ErrorCode: {}, Type: { AD_LOAD: 'adLoadError', AD_PLAY: 'adPlayError' } },
    AdErrorEvent,
    AdEvent,
    AdsLoader,
    AdsManagerLoadedEvent,
    AdsRenderingSettings,
    AdsRequest,
    CompanionAdSelectionSettings,
    ImaSdkSettings: { VpaidMode: { DISABLED: 0, ENABLED: 1, INSECURE: 2 } },
    UiElements: { AD_ATTRIBUTION: 'adAttribution', COUNTDOWN: 'countdown' },
    UniversalAdIdInfo: class {},
    ViewMode: { FULLSCREEN: 'fullscreen', NORMAL: 'normal' },
    settings,
  };

  window.google = window.google ?? {};
  window.google.ima = ima;
})();

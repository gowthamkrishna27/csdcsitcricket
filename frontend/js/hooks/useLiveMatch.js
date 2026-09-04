/**
 * useLiveMatch Hook / Manager
 * Real-time match data manager connecting SSE (/api/matches/live/stream)
 * with graceful fallback to 5s polling. Guarantees zero-refresh updates.
 */
(function(window) {
  class LiveMatchManager {
    constructor() {
      this.currentMatch = null;
      this.subscribers = new Set();
      this.eventSource = null;
      this.pollInterval = null;
      this.isPolling = false;
      this.lastUpdated = null;
    }

    subscribe(callback) {
      this.subscribers.add(callback);
      if (this.currentMatch) {
        callback(this.currentMatch);
      }
      if (this.subscribers.size === 1) {
        this.startStream();
      }
      return () => {
        this.subscribers.delete(callback);
        if (this.subscribers.size === 0) {
          this.stop();
        }
      };
    }

    notify(matchData) {
      this.currentMatch = matchData;
      this.lastUpdated = new Date();
      this.subscribers.forEach(cb => {
        try {
          cb(matchData);
        } catch (e) {
          console.error('[useLiveMatch] Subscriber error:', e);
        }
      });
    }

    async refresh() {
      try {
        const json = await window.MatchesAPI.getLive();
        if (json.success && json.match) {
          this.notify(json.match);
        }
      } catch (err) {
        console.warn('[useLiveMatch] Refresh failed:', err);
      }
    }

    startStream() {
      this.refresh();

      if (window.EventSource) {
        try {
          this.eventSource = new EventSource('/api/matches/live/stream');

          this.eventSource.onmessage = (event) => {
            try {
              const data = JSON.parse(event.data);
              if (data && data.match) {
                this.notify(data.match);
              }
            } catch (err) {
              console.warn('[useLiveMatch] SSE parse error:', err);
            }
          };

          this.eventSource.onerror = () => {
            console.warn('[useLiveMatch] SSE disconnected. Falling back to polling.');
            if (this.eventSource) {
              this.eventSource.close();
              this.eventSource = null;
            }
            this.startPolling();
          };
          return;
        } catch (e) {
          console.warn('[useLiveMatch] Failed to establish SSE, starting polling:', e);
        }
      }

      this.startPolling();
    }

    startPolling() {
      if (this.isPolling) return;
      this.isPolling = true;
      this.pollInterval = setInterval(() => {
        this.refresh();
      }, 5000);
    }

    stop() {
      if (this.eventSource) {
        this.eventSource.close();
        this.eventSource = null;
      }
      if (this.pollInterval) {
        clearInterval(this.pollInterval);
        this.pollInterval = null;
      }
      this.isPolling = false;
    }
  }

  const liveManager = new LiveMatchManager();

  window.useLiveMatch = function(callback) {
    if (typeof callback === 'function') {
      return liveManager.subscribe(callback);
    }
    return {
      getMatch: () => liveManager.currentMatch,
      refresh: () => liveManager.refresh(),
      subscribe: (cb) => liveManager.subscribe(cb)
    };
  };
})(window);

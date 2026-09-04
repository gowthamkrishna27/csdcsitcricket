/**
 * CSD & CSIT Cricket — Stage 4.5 Offline Scoring Queue & Idempotent Sync
 * Database: hpl_scorer_offline_v1
 * Stores offline deliveries in IndexedDB before network dispatch and synchronizes
 * oldest-first when connection is restored.
 */

const ScorerOfflineSync = (function () {
  const DB_NAME = 'hpl_scorer_offline_v1';
  const DB_VERSION = 1;
  const STORE_NAME = 'delivery_queue';

  let dbPromise = null;

  function openDB() {
    if (dbPromise) return dbPromise;

    dbPromise = new Promise((resolve, reject) => {
      if (!window.indexedDB) {
        console.warn('IndexedDB not supported in this environment');
        return resolve(null);
      }

      const req = indexedDB.open(DB_NAME, DB_VERSION);

      req.onupgradeneeded = function (e) {
        const db = e.target.result;
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          const store = db.createObjectStore(STORE_NAME, { keyPath: 'client_event_uuid' });
          store.createIndex('match_id', 'match_id', { unique: false });
          store.createIndex('created_at', 'created_at', { unique: false });
          store.createIndex('status', 'status', { unique: false });
        }
      };

      req.onsuccess = function (e) {
        resolve(e.target.result);
      };

      req.onerror = function (e) {
        console.error('IndexedDB open error:', e);
        reject(e);
      };
    });

    return dbPromise;
  }

  function generateUUID() {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID();
    }
    return 'ev_' + Date.now() + '_' + Math.random().toString(36).substring(2, 11);
  }

  async function enqueueDelivery(matchId, payload) {
    const db = await openDB();
    const event = {
      client_event_uuid: payload.client_event_uuid || generateUUID(),
      match_id: Number(matchId),
      type: payload.type || (payload.wicket_type ? 'WICKET' : 'BALL'),
      runs: payload.runs !== undefined ? payload.runs : 0,
      extra: payload.extra || payload.extra_type || null,
      batsman_name: payload.batsman_name || null,
      bowler_name: payload.bowler_name || null,
      wicket_type: payload.wicket_type || null,
      out_batter: payload.out_batter || payload.out_batter_name || null,
      new_batter: payload.new_batter || payload.new_batter_name || null,
      fielder_name: payload.fielder_name || null,
      expected_sequence: payload.expected_sequence !== undefined ? payload.expected_sequence : null,
      status: 'PENDING',
      created_at: payload.created_at || Date.now()
    };

    if (db) {
      await new Promise((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, 'readwrite');
        const store = tx.objectStore(STORE_NAME);
        const req = store.put(event);
        req.onsuccess = () => resolve(event);
        req.onerror = (e) => reject(e);
      });
    }

    notifyQueueChanged(matchId);
    return event;
  }

  async function removeFromQueue(uuid, matchId) {
    const db = await openDB();
    if (!db) return;
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite');
      const store = tx.objectStore(STORE_NAME);
      const req = store.delete(uuid);
      req.onsuccess = () => {
        if (matchId) notifyQueueChanged(matchId);
        resolve();
      };
      req.onerror = (e) => reject(e);
    });
  }

  async function markConflict(uuid, errorMsg, matchId) {
    const db = await openDB();
    if (!db) return;
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite');
      const store = tx.objectStore(STORE_NAME);
      const getReq = store.get(uuid);
      getReq.onsuccess = () => {
        const item = getReq.result;
        if (item) {
          item.status = 'CONFLICT';
          item.error = errorMsg;
          store.put(item);
        }
        if (matchId) notifyQueueChanged(matchId);
        resolve();
      };
      getReq.onerror = (e) => reject(e);
    });
  }

  async function getPendingEvents(matchId) {
    const db = await openDB();
    if (!db) return [];

    return new Promise((resolve) => {
      const tx = db.transaction(STORE_NAME, 'readonly');
      const store = tx.objectStore(STORE_NAME);
      const req = store.getAll();

      req.onsuccess = () => {
        const all = req.result || [];
        const filtered = all
          .filter(e => (!matchId || e.match_id === Number(matchId)) && e.status === 'PENDING')
          .sort((a, b) => a.created_at - b.created_at); // Oldest event first
        resolve(filtered);
      };

      req.onerror = () => resolve([]);
    });
  }

  async function getPendingQueueCount(matchId) {
    const events = await getPendingEvents(matchId);
    return events.length;
  }

  /**
   * Online Submission Flow:
   * 1. Create UUID & persist to IndexedDB
   * 2. Send network request
   * 3. On success (200) -> remove from IndexedDB
   * 4. On failure -> keep in IndexedDB for subsequent background sync
   */
  async function recordDeliveryWithSync(matchId, payload) {
    // 1. Enqueue with UUID first
    const queuedEvent = await enqueueDelivery(matchId, payload);

    // 2. Try online submission if browser is online
    if (navigator.onLine) {
      try {
        const endpoint = queuedEvent.type === 'WICKET' 
          ? `/api/matches/${matchId}/wicket`
          : `/api/matches/${matchId}/ball`;

        const res = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(queuedEvent)
        });

        const data = await res.json();

        if (res.ok && data.success) {
          // Confirmed by server -> remove from local queue
          await removeFromQueue(queuedEvent.client_event_uuid, matchId);
          return { success: true, match: data.match, queued: false };
        } else if (res.status === 409 && data.status === 'REJECTED_CONFLICT') {
          // Timeline conflict: preserve locally
          await markConflict(queuedEvent.client_event_uuid, data.error, matchId);
          return { success: false, conflict: true, error: data.error, queued: true };
        }
      } catch (err) {
        console.warn('Network delivery submission failed, keeping event queued locally:', err);
      }
    }

    // Retained offline
    return {
      success: true,
      queued: true,
      offline: true,
      event: queuedEvent,
      message: 'Delivery saved offline. Will sync automatically when connection returns.'
    };
  }

  /**
   * Synchronization Flow:
   * Flushes all pending deliveries in oldest-first order via /api/scorer/matches/<id>/sync
   */
  async function flushOfflineQueue(matchId) {
    const pending = await getPendingEvents(matchId);
    if (!pending || pending.length === 0) return { synced: 0 };

    try {
      const res = await fetch(`/api/scorer/matches/${matchId}/sync`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ events: pending })
      });

      const data = await res.json();

      if (res.ok && data.success) {
        const results = data.results || [];
        for (const r of results) {
          if (r.status === 'APPLIED' || r.status === 'ALREADY_APPLIED') {
            await removeFromQueue(r.client_event_uuid, matchId);
          } else if (r.status === 'REJECTED_CONFLICT') {
            await markConflict(r.client_event_uuid, r.error || 'Server timeline conflict', matchId);
            console.error('Offline delivery rejected due to server timeline divergence:', r);
          }
        }

        notifyQueueChanged(matchId);
        return { synced: results.filter(r => r.status === 'APPLIED').length, results, match: data.match };
      }
    } catch (err) {
      console.warn('Offline sync attempt failed, queue preserved locally:', err);
    }

    return { synced: 0 };
  }

  const queueListeners = [];
  function onQueueChange(fn) {
    queueListeners.push(fn);
  }

  function notifyQueueChanged(matchId) {
    getPendingQueueCount(matchId).then(count => {
      queueListeners.forEach(fn => fn(count, matchId));
    });
  }

  // Auto-sync whenever internet connectivity is restored
  if (typeof window !== 'undefined') {
    window.addEventListener('online', () => {
      console.log('Network connection restored. Checking offline delivery queue...');
      flushOfflineQueue();
    });
  }

  return {
    openDB,
    generateUUID,
    enqueueDelivery,
    removeFromQueue,
    getPendingEvents,
    getPendingQueueCount,
    recordDeliveryWithSync,
    flushOfflineQueue,
    onQueueChange
  };
})();

if (typeof module !== 'undefined' && module.exports) {
  module.exports = ScorerOfflineSync;
}

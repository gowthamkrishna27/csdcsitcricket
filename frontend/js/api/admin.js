/**
 * Admin Match Management API Layer
 */
(function(window) {
  const AdminAPI = {
    async getMatches() {
      const res = await fetch('/api/admin/matches');
      return await res.json();
    },

    async getMatch(id) {
      const res = await fetch(`/api/admin/matches/${id}`);
      return await res.json();
    },

    async createMatch(matchData) {
      const res = await fetch('/api/admin/matches', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(matchData)
      });
      return await res.json();
    },

    async updateMatch(id, matchData) {
      const res = await fetch(`/api/admin/matches/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(matchData)
      });
      return await res.json();
    },

    async deleteMatch(id) {
      const res = await fetch(`/api/admin/matches/${id}`, {
        method: 'DELETE'
      });
      return await res.json();
    },

    async startMatch(id) {
      const res = await fetch(`/api/admin/matches/${id}/start`, {
        method: 'POST'
      });
      return await res.json();
    },

    async pauseMatch(id) {
      const res = await fetch(`/api/admin/matches/${id}/pause`, {
        method: 'POST'
      });
      return await res.json();
    },

    async completeMatch(id, { winner, margin = '' }) {
      const res = await fetch(`/api/admin/matches/${id}/complete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ winner, margin })
      });
      return await res.json();
    }
  };

  window.AdminAPI = AdminAPI;
})(window);

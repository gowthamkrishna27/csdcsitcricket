/**
 * Public Matches & Scorecard API Layer
 * Connects frontend to authoritative backend match endpoints
 */
(function(window) {
  const MatchesAPI = {
    async getAll() {
      const res = await fetch('/api/matches');
      return await res.json();
    },

    async getLive() {
      const res = await fetch('/api/matches/live');
      return await res.json();
    },

    async getById(id) {
      const res = await fetch(`/api/matches/${id}`);
      return await res.json();
    },

    async getScorecard(id) {
      const res = await fetch(`/api/matches/${id}/scorecard`);
      return await res.json();
    }
  };

  window.MatchesAPI = MatchesAPI;
})(window);

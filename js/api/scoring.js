/**
 * Admin Scoring API Layer
 * Protected endpoints for live ball recording, wickets, and authoritative undo
 */
(function(window) {
  const ScoringAPI = {
    async recordBall(matchId, { runs = 0, extra = null, batsman_name = null, bowler_name = null }) {
      const res = await fetch(`/api/admin/matches/${matchId}/ball`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ runs, extra, batsman_name, bowler_name })
      });
      return await res.json();
    },

    async recordWicket(matchId, { new_batter = 'Next Batter', wicket_type = 'BOWLED', out_batter = null, bowler_name = null }) {
      const res = await fetch(`/api/admin/matches/${matchId}/wicket`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ newBatter: new_batter, wicket_type, out_batter, bowler_name })
      });
      return await res.json();
    },

    async undoLastBall(matchId) {
      const res = await fetch(`/api/admin/matches/${matchId}/undo`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      return await res.json();
    },

    async setScore(matchId, { runs = 0, wickets = 0, overs = '0.0' }) {
      const res = await fetch(`/api/admin/matches/${matchId}/score`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ runs, wickets, overs })
      });
      return await res.json();
    },

    async switchInnings(matchId) {
      const res = await fetch(`/api/admin/matches/${matchId}/innings/switch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      return await res.json();
    }
  };

  window.ScoringAPI = ScoringAPI;
})(window);

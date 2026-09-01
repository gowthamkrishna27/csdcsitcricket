/**
 * useAdminScoring Hook
 * Manages admin scoring actions with state feedback, error handling, and toast alerts
 */
(function(window) {
  window.useAdminScoring = function() {
    let isSubmitting = false;

    return {
      async recordBall(matchId, ballData) {
        if (isSubmitting) return;
        isSubmitting = true;
        try {
          const res = await window.ScoringAPI.recordBall(matchId, ballData);
          return res;
        } finally {
          isSubmitting = false;
        }
      },

      async recordWicket(matchId, wicketData) {
        if (isSubmitting) return;
        isSubmitting = true;
        try {
          const res = await window.ScoringAPI.recordWicket(matchId, wicketData);
          return res;
        } finally {
          isSubmitting = false;
        }
      },

      async undo(matchId) {
        if (isSubmitting) return;
        isSubmitting = true;
        try {
          const res = await window.ScoringAPI.undoLastBall(matchId);
          return res;
        } finally {
          isSubmitting = false;
        }
      }
    };
  };
})(window);

/**
 * OverHistory Component
 * Displays recent overs with visual badges (0, 1, 2, 3, 4, 6, W, Wd, Nb)
 */
(function(window) {
  function getBallBadge(ball) {
    if (ball.wicket) {
      return `<span class="ball-badge wicket" title="Wicket: ${ball.wicket_type || 'OUT'}">W</span>`;
    }
    if (ball.extra_type === 'WIDE') {
      return `<span class="ball-badge extra" title="Wide">wd</span>`;
    }
    if (ball.extra_type === 'NO BALL') {
      return `<span class="ball-badge extra" title="No Ball">nb</span>`;
    }
    if (ball.runs === 4) {
      return `<span class="ball-badge four" title="Four">4</span>`;
    }
    if (ball.runs === 6) {
      return `<span class="ball-badge six" title="Six">6</span>`;
    }
    if (ball.runs === 0) {
      return `<span class="ball-badge dot" title="Dot Ball">0</span>`;
    }
    return `<span class="ball-badge single" title="${ball.runs} runs">${ball.runs}</span>`;
  }

  function render(match, container) {
    if (!container) return;
    const recentOvers = match && match.recent_overs ? match.recent_overs : [];

    if (recentOvers.length === 0) {
      container.innerHTML = `
        <div class="table-empty">Over just getting started...</div>
      `;
      return;
    }

    const html = recentOvers.map(ov => {
      const badges = ov.balls.map(b => getBallBadge(b)).join('');
      const totalOverRuns = ov.balls.reduce((sum, b) => sum + (b.runs || 0) + (b.extras || 0), 0);
      return `
        <div class="over-row">
          <div class="over-label">
            <span class="over-title">OVER ${ov.over_number + 1}</span>
            <span class="over-runs-tag">${totalOverRuns} runs</span>
          </div>
          <div class="over-balls-track">
            ${badges}
          </div>
        </div>
      `;
    }).join('');

    container.innerHTML = `
      <div class="recent-overs-container">
        <div class="recent-overs-header">
          <span class="overs-headline"><i class="fa fa-history"></i> RECENT OVERS</span>
        </div>
        <div class="recent-overs-list">
          ${html}
        </div>
      </div>
    `;
  }

  window.OverHistory = { render, getBallBadge };
})(window);

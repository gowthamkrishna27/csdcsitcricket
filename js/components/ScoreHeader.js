/**
 * ScoreHeader Component
 * Renders the top live match header with Team A, Team B, overs, run rates, and result status.
 */
(function(window) {
  function render(match, container) {
    if (!container) return;
    if (!match) {
      container.innerHTML = `
        <div style="padding: 24px; text-align: center; color: #8a9cb0;">
          <i class="fa fa-cricket-bat-ball" style="font-size: 28px; margin-bottom: 8px;"></i>
          <div>No active live match right now.</div>
        </div>
      `;
      return;
    }

    const innings = match.innings || [];
    const inn1 = innings.find(i => i.innings_number === 1) || match.current_inn;
    const inn2 = innings.find(i => i.innings_number === 2);
    const currInn = match.current_inn || inn1;

    const score1Text = inn1 ? `${inn1.runs}/${inn1.wickets}` : '0/0';
    const overs1Text = inn1 ? `${inn1.overs}.${inn1.balls}` : '0.0';

    let score2Html = '';
    if (inn2) {
      score2Html = `
        <div class="team-block team-b">
          <div class="team-name">${match.team_b}</div>
          <div class="team-score">${inn2.runs}/${inn2.wickets}</div>
          <div class="team-overs">${inn2.overs}.${inn2.balls} / ${match.total_overs} Ov</div>
        </div>
      `;
    } else {
      score2Html = `
        <div class="team-block team-b">
          <div class="team-name">${match.team_b}</div>
          <div class="team-score" style="font-size:18px; color:#8a9cb0;">Yet to Bat</div>
          <div class="team-overs">${match.total_overs} Overs Match</div>
        </div>
      `;
    }

    let statusHtml = '';
    if (match.status === 'COMPLETED') {
      const winnerTxt = match.winner ? `${match.winner.toUpperCase()} WON ${match.result_margin || ''}`.trim() : 'MATCH COMPLETED';
      statusHtml = `<div class="status-banner completed">${winnerTxt}</div>`;
    } else if (match.status === 'PAUSED') {
      statusHtml = `<div class="status-banner paused">MATCH PAUSED (${match.venue})</div>`;
    } else if (currInn && currInn.target) {
      const need = currInn.target - currInn.runs;
      const remBalls = (match.total_overs * 6) - (currInn.overs * 6 + currInn.balls);
      statusHtml = `<div class="status-banner chase">${currInn.batting_team} need ${Math.max(0, need)} runs in ${Math.max(0, remBalls)} balls (Target: ${currInn.target})</div>`;
    } else {
      statusHtml = `<div class="status-banner live"><span class="live-dot"></span> LIVE · CRR: ${match.crr || '0.00'} · ${match.venue}</div>`;
    }

    container.innerHTML = `
      <div class="score-header-card">
        <div class="score-header-top">
          <span class="match-league-badge"><i class="fa fa-trophy"></i> HPL 2026 · ${match.total_overs} OVERS</span>
          <span class="live-pill ${match.status.toLowerCase()}">${match.status}</span>
        </div>
        <div class="score-teams-row">
          <div class="team-block team-a">
            <div class="team-name">${match.team_a}</div>
            <div class="team-score">${score1Text}</div>
            <div class="team-overs">${overs1Text} / ${match.total_overs} Ov</div>
          </div>
          <div class="vs-divider">VS</div>
          ${score2Html}
        </div>
        ${statusHtml}
      </div>
    `;
  }

  window.ScoreHeader = { render };
})(window);

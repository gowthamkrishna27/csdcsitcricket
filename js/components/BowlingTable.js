/**
 * BowlingTable Component
 * Displays the current bowler (Bowler, Overs, Maidens, Runs, Wickets, Economy)
 */
(function(window) {
  function render(match, container) {
    if (!container) return;
    const bowler = match && match.current_bowler ? match.current_bowler : null;

    if (!bowler) {
      container.innerHTML = `
        <div class="table-empty">Bowler yet to be assigned for this over.</div>
      `;
      return;
    }

    const econ = bowler.economy !== undefined ? Number(bowler.economy).toFixed(2) : '0.00';
    const overs = bowler.overs !== undefined ? Number(bowler.overs).toFixed(1) : '0.0';

    container.innerHTML = `
      <div class="cricket-table-wrap">
        <table class="cricket-stat-table bowling-table">
          <thead>
            <tr>
              <th style="text-align:left;">BOWLER</th>
              <th>O</th>
              <th>M</th>
              <th>R</th>
              <th>W</th>
              <th>ECO</th>
            </tr>
          </thead>
          <tbody>
            <tr class="active-bowler-row">
              <td class="player-name-cell">
                <span class="player-name">${bowler.player_name}</span>
                <span class="bowling-badge">Current</span>
              </td>
              <td class="stat-cell">${overs}</td>
              <td class="stat-cell">${bowler.maidens || 0}</td>
              <td class="stat-cell runs-conceded"><strong>${bowler.runs}</strong></td>
              <td class="stat-cell wickets-cell"><strong>${bowler.wickets}</strong></td>
              <td class="stat-cell">${econ}</td>
            </tr>
          </tbody>
        </table>
      </div>
    `;
  }

  window.BowlingTable = { render };
})(window);

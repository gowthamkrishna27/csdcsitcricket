/**
 * BattingTable Component
 * Displays the current batsmen on pitch (Batter, Runs, Balls, 4s, 6s, Strike Rate)
 * with visual * on-strike indicator.
 */
(function(window) {
  function render(match, container) {
    if (!container) return;
    const batsmen = match && match.current_batsmen ? match.current_batsmen : [];

    if (batsmen.length === 0) {
      container.innerHTML = `
        <div class="table-empty">No active batsmen on pitch.</div>
      `;
      return;
    }

    const rows = batsmen.map(b => {
      const strikeIndicator = b.is_on_strike ? '<span class="strike-star">*</span>' : '';
      const sr = b.strike_rate !== undefined ? Number(b.strike_rate).toFixed(1) : '0.0';
      return `
        <tr class="${b.is_on_strike ? 'on-strike' : ''}">
          <td class="player-name-cell">
            <span class="player-name">${b.player_name}</span>
            ${strikeIndicator}
          </td>
          <td class="stat-cell runs-cell"><strong>${b.runs}</strong></td>
          <td class="stat-cell">${b.balls}</td>
          <td class="stat-cell">${b.fours}</td>
          <td class="stat-cell">${b.sixes}</td>
          <td class="stat-cell sr-cell">${sr}</td>
        </tr>
      `;
    }).join('');

    container.innerHTML = `
      <div class="cricket-table-wrap">
        <table class="cricket-stat-table batting-table">
          <thead>
            <tr>
              <th style="text-align:left;">BATTER</th>
              <th>R</th>
              <th>B</th>
              <th>4s</th>
              <th>6s</th>
              <th>SR</th>
            </tr>
          </thead>
          <tbody>
            ${rows}
          </tbody>
        </table>
      </div>
    `;
  }

  window.BattingTable = { render };
})(window);

/**
 * LiveScore Component
 * Main coordinator component rendering Hero ScoreHeader, Current Batsmen,
 * Current Bowler, Recent Overs, and the Full Detailed Scorecard.
 */
(function(window) {
  let activeTab = 'summary'; // 'summary' | 'scorecard'
  let currentMatchData = null;
  let fullScorecardData = null;

  async function loadFullScorecard(matchId) {
    try {
      const json = await window.MatchesAPI.getScorecard(matchId);
      if (json.success && json.scorecard) {
        fullScorecardData = json.scorecard;
        renderDetailedScorecard();
      }
    } catch (e) {
      console.warn('[LiveScore] Failed to load full scorecard:', e);
    }
  }

  function renderDetailedScorecard() {
    const scContainer = document.getElementById('fullScorecardContent');
    if (!scContainer) return;
    if (!fullScorecardData || !fullScorecardData.scorecards) {
      scContainer.innerHTML = '<div class="table-empty">Scorecard details unavailable.</div>';
      return;
    }

    const cardsHtml = fullScorecardData.scorecards.map((sc, idx) => {
      const innInfo = sc.innings_info;
      const battingRows = (sc.batting || []).map(b => `
        <tr>
          <td style="text-align:left;">
            <strong>${b.player_name}</strong>
            <div style="font-size:11px; color:#7f8c8d;">${b.dismissal_text || 'not out'}</div>
          </td>
          <td class="stat-cell"><strong>${b.runs}</strong></td>
          <td class="stat-cell">${b.balls}</td>
          <td class="stat-cell">${b.fours}</td>
          <td class="stat-cell">${b.sixes}</td>
          <td class="stat-cell">${Number(b.strike_rate || 0).toFixed(1)}</td>
        </tr>
      `).join('');

      const bowlingRows = (sc.bowling || []).map(bw => `
        <tr>
          <td style="text-align:left;"><strong>${bw.player_name}</strong></td>
          <td class="stat-cell">${Number(bw.overs || 0).toFixed(1)}</td>
          <td class="stat-cell">${bw.maidens || 0}</td>
          <td class="stat-cell">${bw.runs}</td>
          <td class="stat-cell"><strong>${bw.wickets}</strong></td>
          <td class="stat-cell">${Number(bw.economy || 0).toFixed(2)}</td>
        </tr>
      `).join('');

      const fowList = (sc.fall_of_wickets || []).map((w, wIdx) => 
        `<span>${w.out_player_name || 'Wicket'} (${w.runs || ''} runs, ${w.over_number}.${w.ball_number} ov)</span>`
      ).join(' · ') || 'None';

      const ext = sc.extras || {};

      return `
        <div class="scorecard-innings-card">
          <div class="scorecard-innings-header">
            <h3>${innInfo.batting_team} Innings: ${innInfo.runs}/${innInfo.wickets} (${innInfo.overs}.${innInfo.balls} Ov)</h3>
          </div>
          <table class="cricket-stat-table">
            <thead>
              <tr>
                <th style="text-align:left;">BATTER</th>
                <th>R</th><th>B</th><th>4s</th><th>6s</th><th>SR</th>
              </tr>
            </thead>
            <tbody>
              ${battingRows || '<tr><td colspan="6" class="table-empty">No batting records</td></tr>'}
            </tbody>
          </table>
          <div class="extras-summary">
            <span>Extras: <strong>${ext.total || 0}</strong> (b ${ext.byes || 0}, lb ${ext.legbyes || 0}, w ${ext.wides || 0}, nb ${ext.noballs || 0})</span>
            <span style="float:right;">Total: <strong>${innInfo.runs}/${innInfo.wickets}</strong> (${innInfo.overs}.${innInfo.balls} Ov)</span>
          </div>

          <div class="fow-summary">
            <strong>Fall of Wickets:</strong> ${fowList}
          </div>

          <div class="scorecard-innings-header" style="margin-top:16px;">
            <h4>${innInfo.bowling_team} Bowling</h4>
          </div>
          <table class="cricket-stat-table">
            <thead>
              <tr>
                <th style="text-align:left;">BOWLER</th>
                <th>O</th><th>M</th><th>R</th><th>W</th><th>ECO</th>
              </tr>
            </thead>
            <tbody>
              ${bowlingRows || '<tr><td colspan="6" class="table-empty">No bowling records</td></tr>'}
            </tbody>
          </table>
        </div>
      `;
    }).join('');

    scContainer.innerHTML = cardsHtml;
  }

  function init(options = {}) {
    const {
      headerSelector = '#liveScoreHeader',
      battingSelector = '#liveBattingTable',
      bowlingSelector = '#liveBowlingTable',
      oversSelector = '#liveRecentOvers',
      scorecardSelector = '#fullScorecardContent'
    } = options;

    window.useLiveMatch((match) => {
      currentMatchData = match;

      const headerEl = document.querySelector(headerSelector);
      const battingEl = document.querySelector(battingSelector);
      const bowlingEl = document.querySelector(bowlingSelector);
      const oversEl = document.querySelector(oversSelector);

      if (window.ScoreHeader) window.ScoreHeader.render(match, headerEl);
      if (window.BattingTable) window.BattingTable.render(match, battingEl);
      if (window.BowlingTable) window.BowlingTable.render(match, bowlingEl);
      if (window.OverHistory) window.OverHistory.render(match, oversEl);

      // Also update top header banner if present
      const miniLiveTitle = document.querySelector('.rca-live-season .rca-match-title');
      const miniLiveScore = document.querySelector('.rca-live-season .rca-match-score');
      if (miniLiveTitle && miniLiveScore && match) {
        const inn = match.current_inn || (match.innings && match.innings[0]);
        miniLiveTitle.textContent = `${(match.team_a || '').toUpperCase()} vs ${(match.team_b || '').toUpperCase()} : `;
        if (inn) {
          miniLiveScore.textContent = `${inn.batting_team} ${inn.runs}/${inn.wickets} (${inn.overs}.${inn.balls} ov)`;
        }
      }

      if (match && match.id) {
        loadFullScorecard(match.id);
      }
    });
  }

  window.LiveScore = {
    init,
    loadFullScorecard
  };
})(window);

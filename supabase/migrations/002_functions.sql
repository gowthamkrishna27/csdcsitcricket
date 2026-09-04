-- =============================================================================
-- CSDC/CSIT Cricket Tournament — Supabase PostgreSQL Functions
-- Migration 002: Helper Functions & Standings Recalculation
-- Run in: Supabase Dashboard → SQL Editor (after 001_schema.sql)
-- =============================================================================

-- =============================================================================
-- recalculate_standings(p_league_id INTEGER)
-- Recomputes the full points table for a league from match results.
-- Mirrors the Python logic in cricket_db.recalculate_standings().
-- =============================================================================
CREATE OR REPLACE FUNCTION recalculate_standings(p_league_id INTEGER)
RETURNS VOID AS $$
DECLARE
    r       RECORD;
    team    TEXT;
    teams_in_league TEXT[];
BEGIN
    -- 1. Gather all teams that participated in this league
    SELECT ARRAY(
        SELECT DISTINCT unnest(ARRAY[team_a, team_b])
        FROM matches
        WHERE league_id = p_league_id
        UNION
        SELECT name FROM teams WHERE league_id = p_league_id
    ) INTO teams_in_league;

    -- 2. Delete stale standing rows for this league
    DELETE FROM league_standings WHERE league_id = p_league_id;

    -- 3. Compute per-team stats from completed matches
    FOREACH team IN ARRAY teams_in_league
    LOOP
        INSERT INTO league_standings (
            league_id, team_name,
            played, wins, losses, ties, no_results, points,
            runs_scored, overs_faced, runs_conceded, overs_bowled, net_run_rate
        )
        SELECT
            p_league_id,
            team,
            COUNT(*)                                                        AS played,
            SUM(CASE WHEN winner = team THEN 1 ELSE 0 END)                 AS wins,
            SUM(CASE
                    WHEN winner NOT IN ('', 'No Result', 'Match Tied', 'Cancelled')
                         AND winner != team THEN 1 ELSE 0
                END)                                                        AS losses,
            SUM(CASE WHEN winner = 'Match Tied' THEN 1 ELSE 0 END)        AS ties,
            SUM(CASE WHEN winner IN ('No Result', 'Cancelled') THEN 1 ELSE 0 END) AS no_results,
            -- Points: win=2, tie/NR=1, loss=0
            SUM(CASE
                    WHEN winner = team THEN 2
                    WHEN winner IN ('Match Tied', 'No Result') THEN 1
                    ELSE 0
                END)                                                        AS points,
            -- Runs scored by this team (batting)
            COALESCE((
                SELECT SUM(i.runs)
                FROM innings i
                JOIN matches m2 ON i.match_id = m2.id
                WHERE m2.league_id = p_league_id
                  AND m2.status = 'COMPLETED'
                  AND i.batting_team = team
                  AND (m2.team_a = team OR m2.team_b = team)
            ), 0)                                                            AS runs_scored,
            -- Overs faced in base-6 decimal (e.g. 9.4 overs = 9 + 4/6 = 9.667)
            COALESCE((
                SELECT SUM(
                    CASE
                        WHEN i.wickets >= COALESCE(m2.players_per_team - 1, 10)
                        THEN m2.total_overs
                        ELSE (i.overs + (i.balls / 6.0))
                    END
                )
                FROM innings i
                JOIN matches m2 ON i.match_id = m2.id
                WHERE m2.league_id = p_league_id
                  AND m2.status = 'COMPLETED'
                  AND i.batting_team = team
                  AND (m2.team_a = team OR m2.team_b = team)
            ), 0.0)                                                          AS overs_faced,
            -- Runs conceded (bowling)
            COALESCE((
                SELECT SUM(i.runs)
                FROM innings i
                JOIN matches m2 ON i.match_id = m2.id
                WHERE m2.league_id = p_league_id
                  AND m2.status = 'COMPLETED'
                  AND i.bowling_team = team
                  AND (m2.team_a = team OR m2.team_b = team)
            ), 0)                                                            AS runs_conceded,
            -- Overs bowled in base-6 decimal
            COALESCE((
                SELECT SUM(
                    CASE
                        WHEN i.wickets >= COALESCE(m2.players_per_team - 1, 10)
                        THEN m2.total_overs
                        ELSE (i.overs + (i.balls / 6.0))
                    END
                )
                FROM innings i
                JOIN matches m2 ON i.match_id = m2.id
                WHERE m2.league_id = p_league_id
                  AND m2.status = 'COMPLETED'
                  AND i.bowling_team = team
                  AND (m2.team_a = team OR m2.team_b = team)
            ), 0.0)                                                          AS overs_bowled,
            0.0                                                             AS net_run_rate
        FROM matches
        WHERE league_id = p_league_id
          AND status = 'COMPLETED'
          AND (team_a = team OR team_b = team);

        -- 4. Update NRR for this team
        UPDATE league_standings ls
        SET net_run_rate = CASE
            WHEN ls.overs_faced > 0 AND ls.overs_bowled > 0
            THEN ROUND(
                CAST((ls.runs_scored / NULLIF(ls.overs_faced, 0))
                   - (ls.runs_conceded / NULLIF(ls.overs_bowled, 0)) AS NUMERIC), 3
            )
            ELSE 0.0
        END
        WHERE ls.league_id = p_league_id AND ls.team_name = team;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

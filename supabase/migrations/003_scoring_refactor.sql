-- =============================================================================
-- CSDC/CSIT Cricket Tournament — Supabase PostgreSQL Schema Refactor
-- Migration 003: Scoring Engine Hardening, Invariants & Security
-- Run in: Supabase Dashboard → SQL Editor (after 001_schema.sql & 002_functions.sql)
-- =============================================================================

-- 1. INNINGS STATUS & CONSTRAINTS
-- Add explicit status to innings (NOT_STARTED, ACTIVE, COMPLETED)
ALTER TABLE innings
    ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'ACTIVE'
    CHECK (status IN ('NOT_STARTED', 'ACTIVE', 'COMPLETED'));

-- 2. CLIENT EVENT UUID IDEMPOTENCY CONSTRAINT
-- Ensure every delivery UUID is globally unique across ball events
CREATE UNIQUE INDEX IF NOT EXISTS idx_ball_events_client_uuid
    ON ball_events (client_event_uuid)
    WHERE client_event_uuid IS NOT NULL AND client_event_uuid != '';

-- 3. SECURITY HARDENING: DROP PUBLIC ANONYMOUS INSERT POLICY
-- Revoke anonymous writes to ball_events (all mutations must pass through backend service role)
DROP POLICY IF EXISTS "anon_insert_ball_events" ON ball_events;

-- Ensure public read-only access remains for all viewer tables
CREATE POLICY "public_read_ball_events_v2" ON ball_events FOR SELECT USING (true);

-- 4. MATHEMATICALLY CORRECT STANDINGS RECALCULATION FUNCTION
-- Fixes base-6 overs calculation (overs + balls / 6.0) and all-out quota
CREATE OR REPLACE FUNCTION recalculate_standings(p_league_id INTEGER)
RETURNS VOID AS $$
DECLARE
    r RECORD;
    t_name TEXT;
    teams_in_league TEXT[];
BEGIN
    -- Gather all teams in league
    SELECT ARRAY(
        SELECT DISTINCT unnest(ARRAY[team_a, team_b])
        FROM matches
        WHERE league_id = p_league_id
        UNION
        SELECT name FROM teams WHERE league_id = p_league_id
    ) INTO teams_in_league;

    -- Delete stale standings
    DELETE FROM league_standings WHERE league_id = p_league_id;

    -- Compute per-team stats
    FOREACH t_name IN ARRAY teams_in_league
    LOOP
        INSERT INTO league_standings (
            league_id, team_name,
            played, wins, losses, ties, no_results, points,
            runs_scored, overs_faced, runs_conceded, overs_bowled, net_run_rate
        )
        SELECT
            p_league_id,
            t_name,
            COUNT(*)                                                        AS played,
            SUM(CASE WHEN winner = t_name THEN 1 ELSE 0 END)                AS wins,
            SUM(CASE
                    WHEN winner NOT IN ('', 'No Result', 'Match Tied', 'Cancelled')
                         AND winner != t_name THEN 1 ELSE 0
                END)                                                        AS losses,
            SUM(CASE WHEN winner = 'Match Tied' THEN 1 ELSE 0 END)          AS ties,
            SUM(CASE WHEN winner IN ('No Result', 'Cancelled') THEN 1 ELSE 0 END) AS no_results,
            SUM(CASE
                    WHEN winner = t_name THEN 2
                    WHEN winner IN ('Match Tied', 'No Result') THEN 1
                    ELSE 0
                END)                                                        AS points,
            -- Runs scored
            COALESCE((
                SELECT SUM(i.runs)
                FROM innings i
                JOIN matches m2 ON i.match_id = m2.id
                WHERE m2.league_id = p_league_id
                  AND m2.status = 'COMPLETED'
                  AND i.batting_team = t_name
                  AND (m2.team_a = t_name OR m2.team_b = t_name)
            ), 0)                                                            AS runs_scored,
            -- Overs faced in base-6 decimal (e.g. 9.4 overs = 9 + 4/6 = 9.667)
            COALESCE((
                SELECT SUM(
                    CASE
                        -- All out: full quota of match overs
                        WHEN i.wickets >= COALESCE(m2.players_per_team - 1, 10)
                        THEN m2.total_overs
                        ELSE (i.overs + (i.balls / 6.0))
                    END
                )
                FROM innings i
                JOIN matches m2 ON i.match_id = m2.id
                WHERE m2.league_id = p_league_id
                  AND m2.status = 'COMPLETED'
                  AND i.batting_team = t_name
                  AND (m2.team_a = t_name OR m2.team_b = t_name)
            ), 0.0)                                                          AS overs_faced,
            -- Runs conceded
            COALESCE((
                SELECT SUM(i.runs)
                FROM innings i
                JOIN matches m2 ON i.match_id = m2.id
                WHERE m2.league_id = p_league_id
                  AND m2.status = 'COMPLETED'
                  AND i.bowling_team = t_name
                  AND (m2.team_a = t_name OR m2.team_b = t_name)
            ), 0)                                                            AS runs_conceded,
            -- Overs bowled in base-6 decimal
            COALESCE((
                SELECT SUM(
                    CASE
                        -- Opponent all out: full quota
                        WHEN i.wickets >= COALESCE(m2.players_per_team - 1, 10)
                        THEN m2.total_overs
                        ELSE (i.overs + (i.balls / 6.0))
                    END
                )
                FROM innings i
                JOIN matches m2 ON i.match_id = m2.id
                WHERE m2.league_id = p_league_id
                  AND m2.status = 'COMPLETED'
                  AND i.bowling_team = t_name
                  AND (m2.team_a = t_name OR m2.team_b = t_name)
            ), 0.0)                                                          AS overs_bowled,
            0.0                                                             AS net_run_rate
        FROM matches
        WHERE league_id = p_league_id
          AND status = 'COMPLETED'
          AND (team_a = t_name OR team_b = t_name);

        -- Update NRR
        UPDATE league_standings ls
        SET net_run_rate = CASE
            WHEN ls.overs_faced > 0 AND ls.overs_bowled > 0
            THEN ROUND(
                CAST((ls.runs_scored / NULLIF(ls.overs_faced, 0))
                   - (ls.runs_conceded / NULLIF(ls.overs_bowled, 0)) AS NUMERIC), 3
            )
            ELSE 0.0
        END
        WHERE ls.league_id = p_league_id AND ls.team_name = t_name;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

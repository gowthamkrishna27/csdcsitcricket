-- =============================================================================
-- CSDC/CSIT Cricket Tournament — Supabase PostgreSQL Schema
-- Migration 001: Full Schema with RLS
-- Run in: Supabase Dashboard → SQL Editor
-- =============================================================================

-- -------------------------
-- EXTENSIONS
-- -------------------------
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- -------------------------
-- 0. TOURNAMENTS
-- -------------------------
CREATE TABLE IF NOT EXISTS tournaments (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    season     TEXT DEFAULT '2026',
    status     TEXT DEFAULT 'active' CHECK (status IN ('active', 'disabled', 'completed')),
    start_date TEXT,
    end_date   TEXT,
    total_overs     INTEGER DEFAULT 10,
    format_name     TEXT DEFAULT 'T10',
    description     TEXT,
    is_active       INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- -------------------------
-- 1. LEAGUES
-- -------------------------
CREATE TABLE IF NOT EXISTS leagues (
    id            SERIAL PRIMARY KEY,
    tournament_id INTEGER DEFAULT 1,
    name          TEXT NOT NULL UNIQUE,
    short_name    TEXT,
    description   TEXT,
    status        TEXT DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- -------------------------
-- 2. TEAMS
-- -------------------------
CREATE TABLE IF NOT EXISTS teams (
    id         TEXT PRIMARY KEY,        -- Preserved: T1, T2, ...
    name       TEXT UNIQUE NOT NULL,
    short_name TEXT,
    captain    TEXT,
    color      TEXT DEFAULT '#1a73e8',
    league_id  INTEGER DEFAULT 1 REFERENCES leagues(id)
);

-- -------------------------
-- 3. PLAYERS
-- -------------------------
CREATE TABLE IF NOT EXISTS players (
    id             TEXT PRIMARY KEY,    -- Preserved: P01, P02, ...
    team_id        TEXT REFERENCES teams(id) ON DELETE SET NULL,
    name           TEXT NOT NULL,
    role           TEXT DEFAULT 'Batsman',
    jersey_number  INTEGER DEFAULT 0
);

-- -------------------------
-- 4. MATCHES
-- -------------------------
CREATE TABLE IF NOT EXISTS matches (
    id                  SERIAL PRIMARY KEY,
    match_name          TEXT,
    team_a              TEXT NOT NULL,
    team_b              TEXT NOT NULL,
    venue               TEXT DEFAULT 'College Ground',
    match_date          TEXT DEFAULT 'Today',
    time                TEXT DEFAULT '02:00 PM',
    status              TEXT DEFAULT 'UPCOMING' CHECK (status IN ('UPCOMING','LIVE','PAUSED','COMPLETED')),
    current_innings     INTEGER DEFAULT 1,
    total_overs         INTEGER DEFAULT 10,
    format_name         TEXT DEFAULT 'T10',
    players_per_team    INTEGER DEFAULT 11,
    balls_per_over      INTEGER DEFAULT 6,
    winner              TEXT DEFAULT '',
    result_margin       TEXT DEFAULT '',
    toss_winner         TEXT DEFAULT '',
    toss_decision       TEXT DEFAULT '',
    playing_xi_a        TEXT DEFAULT '[]',
    playing_xi_b        TEXT DEFAULT '[]',
    captain_a           TEXT DEFAULT '',
    captain_b           TEXT DEFAULT '',
    wicketkeeper_a      TEXT DEFAULT '',
    wicketkeeper_b      TEXT DEFAULT '',
    league_id           INTEGER DEFAULT 1 REFERENCES leagues(id),
    tournament_id       INTEGER DEFAULT 1 REFERENCES tournaments(id),
    stage               TEXT DEFAULT 'LEAGUE',
    stage_order         INTEGER DEFAULT 0,
    is_locked           INTEGER DEFAULT 0,
    locked_at           TIMESTAMPTZ DEFAULT NULL,
    locked_by           TEXT DEFAULT NULL,
    claimed_by_user_id  TEXT DEFAULT NULL,
    claim_expires_at    TIMESTAMPTZ DEFAULT NULL,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- -------------------------
-- 5. INNINGS
-- -------------------------
CREATE TABLE IF NOT EXISTS innings (
    id             SERIAL PRIMARY KEY,
    match_id       INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    innings_number INTEGER NOT NULL CHECK (innings_number IN (1, 2)),
    batting_team   TEXT NOT NULL,
    bowling_team   TEXT NOT NULL,
    runs           INTEGER DEFAULT 0,
    wickets        INTEGER DEFAULT 0,
    overs          INTEGER DEFAULT 0,
    balls          INTEGER DEFAULT 0,
    target         INTEGER DEFAULT NULL,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);

-- -------------------------
-- 6. BATTING SCORES
-- -------------------------
CREATE TABLE IF NOT EXISTS batting_scores (
    id             SERIAL PRIMARY KEY,
    innings_id     INTEGER NOT NULL REFERENCES innings(id) ON DELETE CASCADE,
    player_id      TEXT,
    player_name    TEXT NOT NULL,
    runs           INTEGER DEFAULT 0,
    balls          INTEGER DEFAULT 0,
    fours          INTEGER DEFAULT 0,
    sixes          INTEGER DEFAULT 0,
    strike_rate    REAL DEFAULT 0.0,
    is_out         INTEGER DEFAULT 0,
    dismissal_text TEXT DEFAULT 'not out',
    batting_order  INTEGER DEFAULT 0,
    is_on_strike   INTEGER DEFAULT 0
);

-- -------------------------
-- 7. BOWLING SCORES
-- -------------------------
CREATE TABLE IF NOT EXISTS bowling_scores (
    id                 SERIAL PRIMARY KEY,
    innings_id         INTEGER NOT NULL REFERENCES innings(id) ON DELETE CASCADE,
    player_id          TEXT,
    player_name        TEXT NOT NULL,
    overs              REAL DEFAULT 0.0,
    legal_balls        INTEGER DEFAULT 0,
    maidens            INTEGER DEFAULT 0,
    runs               INTEGER DEFAULT 0,
    wickets            INTEGER DEFAULT 0,
    economy            REAL DEFAULT 0.0,
    is_current_bowler  INTEGER DEFAULT 0
);

-- -------------------------
-- 8. BALL EVENTS
-- -------------------------
CREATE TABLE IF NOT EXISTS ball_events (
    id                SERIAL PRIMARY KEY,
    innings_id        INTEGER NOT NULL REFERENCES innings(id) ON DELETE CASCADE,
    over_number       INTEGER NOT NULL,
    ball_number       INTEGER NOT NULL,
    batsman_id        TEXT,
    batsman_name      TEXT NOT NULL,
    bowler_id         TEXT,
    bowler_name       TEXT NOT NULL,
    runs              INTEGER DEFAULT 0,
    extras            INTEGER DEFAULT 0,
    extra_type        TEXT DEFAULT NULL,
    wicket            INTEGER DEFAULT 0,
    wicket_type       TEXT DEFAULT NULL,
    out_player_name   TEXT DEFAULT NULL,
    fielder_name      TEXT DEFAULT NULL,
    commentary        TEXT DEFAULT NULL,
    client_event_uuid TEXT UNIQUE DEFAULT NULL,  -- Idempotent offline sync key
    timestamp         TIMESTAMPTZ DEFAULT NOW()
);

-- -------------------------
-- 9. USERS (Unified RBAC)
-- -------------------------
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,          -- Preserved: U001, U002, ...
    name          TEXT NOT NULL,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'ADMIN' CHECK (role IN ('ADMIN', 'SCORER')),
    status        TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'DISABLED')),
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW(),
    last_login    TIMESTAMPTZ
);

-- -------------------------
-- 10. ADMINS (Legacy — kept for reference)
-- -------------------------
CREATE TABLE IF NOT EXISTS admins (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT DEFAULT 'admin',
    status        TEXT DEFAULT 'active',
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW(),
    last_login    TIMESTAMPTZ
);

-- -------------------------
-- 11. LEAGUE STANDINGS
-- -------------------------
CREATE TABLE IF NOT EXISTS league_standings (
    id              SERIAL PRIMARY KEY,
    league_id       INTEGER NOT NULL REFERENCES leagues(id) ON DELETE CASCADE,
    team_name       TEXT NOT NULL,
    played          INTEGER DEFAULT 0,
    wins            INTEGER DEFAULT 0,
    losses          INTEGER DEFAULT 0,
    ties            INTEGER DEFAULT 0,
    no_results      INTEGER DEFAULT 0,
    points          INTEGER DEFAULT 0,
    runs_scored     INTEGER DEFAULT 0,
    overs_faced     REAL DEFAULT 0.0,
    runs_conceded   INTEGER DEFAULT 0,
    overs_bowled    REAL DEFAULT 0.0,
    net_run_rate    REAL DEFAULT 0.0,
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (league_id, team_name)
);

-- -------------------------
-- 12. AUDIT LOGS
-- -------------------------
CREATE TABLE IF NOT EXISTS audit_logs (
    id          SERIAL PRIMARY KEY,
    user_id     TEXT,
    user_email  TEXT,
    action      TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id   TEXT,
    reason      TEXT NOT NULL,
    before_data TEXT,
    after_data  TEXT,
    timestamp   TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- INDEXES
-- =============================================================================
CREATE INDEX IF NOT EXISTS idx_matches_status       ON matches(status);
CREATE INDEX IF NOT EXISTS idx_matches_league       ON matches(league_id);
CREATE INDEX IF NOT EXISTS idx_innings_match        ON innings(match_id);
CREATE INDEX IF NOT EXISTS idx_batting_innings      ON batting_scores(innings_id);
CREATE INDEX IF NOT EXISTS idx_bowling_innings      ON bowling_scores(innings_id);
CREATE INDEX IF NOT EXISTS idx_ball_events_innings  ON ball_events(innings_id);
CREATE INDEX IF NOT EXISTS idx_ball_events_ts       ON ball_events(timestamp);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ball_events_uuid
    ON ball_events(client_event_uuid) WHERE client_event_uuid IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_standings_league     ON league_standings(league_id);
CREATE INDEX IF NOT EXISTS idx_audit_target         ON audit_logs(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_tournaments_active   ON tournaments(is_active);

-- =============================================================================
-- AUTO updated_at TRIGGER
-- =============================================================================
CREATE OR REPLACE FUNCTION trigger_set_timestamp()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$ DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['tournaments','leagues','matches','innings','users','admins']
    LOOP
        EXECUTE format('
            DROP TRIGGER IF EXISTS set_timestamp_%I ON %I;
            CREATE TRIGGER set_timestamp_%I
            BEFORE UPDATE ON %I
            FOR EACH ROW EXECUTE PROCEDURE trigger_set_timestamp();
        ', t, t, t, t);
    END LOOP;
END $$;

-- =============================================================================
-- ROW LEVEL SECURITY (RLS)
-- =============================================================================

-- Enable RLS on all tables
ALTER TABLE tournaments       ENABLE ROW LEVEL SECURITY;
ALTER TABLE leagues           ENABLE ROW LEVEL SECURITY;
ALTER TABLE teams             ENABLE ROW LEVEL SECURITY;
ALTER TABLE players           ENABLE ROW LEVEL SECURITY;
ALTER TABLE matches           ENABLE ROW LEVEL SECURITY;
ALTER TABLE innings           ENABLE ROW LEVEL SECURITY;
ALTER TABLE batting_scores    ENABLE ROW LEVEL SECURITY;
ALTER TABLE bowling_scores    ENABLE ROW LEVEL SECURITY;
ALTER TABLE ball_events       ENABLE ROW LEVEL SECURITY;
ALTER TABLE users             ENABLE ROW LEVEL SECURITY;
ALTER TABLE admins            ENABLE ROW LEVEL SECURITY;
ALTER TABLE league_standings  ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs        ENABLE ROW LEVEL SECURITY;

-- Public read for scoreboard tables (no auth required)
CREATE POLICY "public_read_tournaments"      ON tournaments      FOR SELECT USING (true);
CREATE POLICY "public_read_leagues"          ON leagues          FOR SELECT USING (true);
CREATE POLICY "public_read_teams"            ON teams            FOR SELECT USING (true);
CREATE POLICY "public_read_players"          ON players          FOR SELECT USING (true);
CREATE POLICY "public_read_matches"          ON matches          FOR SELECT USING (true);
CREATE POLICY "public_read_innings"          ON innings          FOR SELECT USING (true);
CREATE POLICY "public_read_batting"          ON batting_scores   FOR SELECT USING (true);
CREATE POLICY "public_read_bowling"          ON bowling_scores   FOR SELECT USING (true);
CREATE POLICY "public_read_ball_events"      ON ball_events      FOR SELECT USING (true);
CREATE POLICY "public_read_standings"        ON league_standings FOR SELECT USING (true);

-- Service role has full access (used by Flask backend with service-role key)
-- The service role bypasses RLS automatically in Supabase.
-- These policies cover direct client access if ever needed:

CREATE POLICY "anon_insert_ball_events" ON ball_events
    FOR INSERT WITH CHECK (true);  -- Idempotent upserts from scorer client

CREATE POLICY "users_read_own" ON users
    FOR SELECT USING (true);  -- Backend handles auth; all reads via service key

-- =============================================================================
-- SEED DEFAULT DATA
-- =============================================================================

-- Default tournament
INSERT INTO tournaments (name, season, status, format_name, total_overs, description, is_active)
VALUES ('College Premier League 2026', '2026', 'active', 'T10', 10,
        'Official College Cricket Tournament Championship', 1)
ON CONFLICT (name) DO NOTHING;

-- Default leagues
INSERT INTO leagues (id, tournament_id, name, short_name, description, status)
VALUES
    (1, 1, 'League 1', 'L1', 'Premier Division Cricket League',      'active'),
    (2, 1, 'League 2', 'L2', 'Championship Division Cricket League', 'active')
ON CONFLICT (id) DO NOTHING;

-- Sequence alignment after manual ID insert
SELECT setval('leagues_id_seq', (SELECT MAX(id) FROM leagues));

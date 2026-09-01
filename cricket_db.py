import os
import sqlite3
import datetime
import json

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "cricket.db")

def get_db():
    """Returns a thread-safe sqlite3 connection with Row factory and foreign keys enabled."""
    conn = sqlite3.connect(DB_PATH, timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    """Initializes the relational schema with tables, foreign keys, and indexes."""
    with get_db() as conn:
        cursor = conn.cursor()

        # 1. TEAMS
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS teams (
            id TEXT PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            short_name TEXT,
            captain TEXT,
            color TEXT DEFAULT '#1a73e8'
        );
        """)

        # 2. PLAYERS
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id TEXT PRIMARY KEY,
            team_id TEXT,
            name TEXT NOT NULL,
            role TEXT DEFAULT 'Batsman',
            jersey_number INTEGER DEFAULT 0,
            FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE SET NULL
        );
        """)

        # 3. MATCHES
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_name TEXT,
            team_a TEXT NOT NULL,
            team_b TEXT NOT NULL,
            venue TEXT DEFAULT 'College Ground',
            match_date TEXT DEFAULT 'Today',
            status TEXT DEFAULT 'UPCOMING' CHECK(status IN ('UPCOMING', 'LIVE', 'PAUSED', 'COMPLETED')),
            current_innings INTEGER DEFAULT 1,
            total_overs INTEGER DEFAULT 10,
            winner TEXT DEFAULT '',
            result_margin TEXT DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # 4. INNINGS
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS innings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL,
            innings_number INTEGER NOT NULL CHECK(innings_number IN (1, 2)),
            batting_team TEXT NOT NULL,
            bowling_team TEXT NOT NULL,
            runs INTEGER DEFAULT 0,
            wickets INTEGER DEFAULT 0,
            overs INTEGER DEFAULT 0,
            balls INTEGER DEFAULT 0,
            target INTEGER DEFAULT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE
        );
        """)

        # 5. BATTING SCORES
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS batting_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            innings_id INTEGER NOT NULL,
            player_id TEXT,
            player_name TEXT NOT NULL,
            runs INTEGER DEFAULT 0,
            balls INTEGER DEFAULT 0,
            fours INTEGER DEFAULT 0,
            sixes INTEGER DEFAULT 0,
            strike_rate REAL DEFAULT 0.0,
            is_out INTEGER DEFAULT 0,
            dismissal_text TEXT DEFAULT 'not out',
            batting_order INTEGER DEFAULT 0,
            is_on_strike INTEGER DEFAULT 0,
            FOREIGN KEY (innings_id) REFERENCES innings(id) ON DELETE CASCADE
        );
        """)

        # 6. BOWLING SCORES
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS bowling_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            innings_id INTEGER NOT NULL,
            player_id TEXT,
            player_name TEXT NOT NULL,
            overs REAL DEFAULT 0.0,
            legal_balls INTEGER DEFAULT 0,
            maidens INTEGER DEFAULT 0,
            runs INTEGER DEFAULT 0,
            wickets INTEGER DEFAULT 0,
            economy REAL DEFAULT 0.0,
            is_current_bowler INTEGER DEFAULT 0,
            FOREIGN KEY (innings_id) REFERENCES innings(id) ON DELETE CASCADE
        );
        """)

        # 7. BALL EVENTS (Authoritative Event History)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS ball_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            innings_id INTEGER NOT NULL,
            over_number INTEGER NOT NULL,
            ball_number INTEGER NOT NULL,
            batsman_id TEXT,
            batsman_name TEXT NOT NULL,
            bowler_id TEXT,
            bowler_name TEXT NOT NULL,
            runs INTEGER DEFAULT 0,
            extras INTEGER DEFAULT 0,
            extra_type TEXT DEFAULT NULL,
            wicket INTEGER DEFAULT 0,
            wicket_type TEXT DEFAULT NULL,
            out_player_name TEXT DEFAULT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (innings_id) REFERENCES innings(id) ON DELETE CASCADE
        );
        """)

        # 8. ADMINS (Local relational admin store for secure auth)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'admin',
            status TEXT DEFAULT 'active',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_login DATETIME
        );
        """)

        # 9. INDEXES
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_innings_match ON innings(match_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_batting_innings ON batting_scores(innings_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_bowling_innings ON bowling_scores(innings_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ball_events_innings ON ball_events(innings_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ball_events_timestamp ON ball_events(timestamp);")

        conn.commit()

    seed_default_data()

def seed_default_data():
    """Seeds initial tournament data if database is empty."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Check teams
        cursor.execute("SELECT COUNT(*) AS count FROM teams")
        if cursor.fetchone()["count"] == 0:
            teams = [
                ("T1", "House Vayu", "VAY", "Rahul Sharma", "#2980b9"),
                ("T2", "House Agni", "AGN", "Rohit Verma", "#e67e22"),
                ("T3", "House Akasha", "AKA", "Siddharth Roy", "#8e44ad"),
                ("T4", "House Jala", "JAL", "Vikram Patel", "#16a085"),
                ("T5", "House Prithvi", "PRI", "Aditya Rao", "#27ae60")
            ]
            cursor.executemany("INSERT INTO teams (id, name, short_name, captain, color) VALUES (?, ?, ?, ?, ?)", teams)

        # Check players
        cursor.execute("SELECT COUNT(*) AS count FROM players")
        if cursor.fetchone()["count"] == 0:
            players = [
                ("P01", "T1", "Rahul Sharma", "Batsman", 7),
                ("P02", "T1", "Arjun Varma", "All-Rounder", 18),
                ("P03", "T1", "Kunal Mehra", "Bowler", 24),
                ("P04", "T1", "Devansh Nair", "Wicketkeeper", 11),
                ("P05", "T1", "Tanmay Joshi", "All-Rounder", 33),

                ("P06", "T2", "Rohit Verma", "Batsman", 10),
                ("P07", "T2", "Sai Krishna", "Bowler", 23),
                ("P08", "T2", "Manish Pandey", "Batsman", 9),
                ("P09", "T2", "Ravi Bishnoi", "Bowler", 56),
                ("P10", "T2", "Aman Khan", "All-Rounder", 45),

                ("P11", "T3", "Siddharth Roy", "All-Rounder", 3),
                ("P12", "T3", "Chetan Sakariya", "Bowler", 14),
                ("P13", "T3", "Karan Sharma", "Batsman", 22),

                ("P14", "T4", "Vikram Patel", "Batsman", 9),
                ("P15", "T4", "Ankit Raj", "Bowler", 19),
                ("P16", "T4", "Suresh Raina", "All-Rounder", 48),

                ("P17", "T5", "Aditya Rao", "All-Rounder", 1),
                ("P18", "T5", "Gaurav Sen", "Bowler", 99),
                ("P19", "T5", "Pranav Anand", "Batsman", 17)
            ]
            cursor.executemany("INSERT INTO players (id, team_id, name, role, jersey_number) VALUES (?, ?, ?, ?, ?)", players)

        # Check bootstrap admin
        cursor.execute("SELECT COUNT(*) AS count FROM admins")
        if cursor.fetchone()["count"] == 0:
            from werkzeug.security import generate_password_hash
            default_email = os.getenv("ADMIN_EMAIL", "admin@hpl.cricket").strip().lower()
            default_pass = os.getenv("ADMIN_PASSWORD", "admin123")
            pw_hash = generate_password_hash(default_pass)
            cursor.execute("""
            INSERT INTO admins (id, name, email, password_hash, role, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """, ("A001", "Tournament Admin", default_email, pw_hash, "admin", "active"))

        # Check matches
        cursor.execute("SELECT COUNT(*) AS count FROM matches")
        if cursor.fetchone()["count"] == 0:
            # Seed a LIVE match and an UPCOMING match
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
            INSERT INTO matches (match_name, team_a, team_b, venue, match_date, status, current_innings, total_overs)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, ("Match 1 - VAY vs AGN", "House Vayu", "House Agni", "College Main Ground", "Today", "LIVE", 1, 10))
            match_id = cursor.lastrowid

            # Create 1st innings for LIVE match
            cursor.execute("""
            INSERT INTO innings (match_id, innings_number, batting_team, bowling_team, runs, wickets, overs, balls)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (match_id, 1, "House Vayu", "House Agni", 0, 0, 0, 0))
            innings_id = cursor.lastrowid

            # Seed initial batsmen and bowler for this innings
            cursor.execute("""
            INSERT INTO batting_scores (innings_id, player_id, player_name, runs, balls, fours, sixes, strike_rate, is_out, dismissal_text, batting_order, is_on_strike)
            VALUES (?, ?, ?, 0, 0, 0, 0, 0.0, 0, 'not out', 1, 1)
            """, (innings_id, "P01", "Rahul Sharma"))

            cursor.execute("""
            INSERT INTO batting_scores (innings_id, player_id, player_name, runs, balls, fours, sixes, strike_rate, is_out, dismissal_text, batting_order, is_on_strike)
            VALUES (?, ?, ?, 0, 0, 0, 0, 0.0, 0, 'not out', 2, 0)
            """, (innings_id, "P02", "Arjun Varma"))

            cursor.execute("""
            INSERT INTO bowling_scores (innings_id, player_id, player_name, overs, legal_balls, maidens, runs, wickets, economy, is_current_bowler)
            VALUES (?, ?, ?, 0.0, 0, 0, 0, 0, 0.0, 1)
            """, (innings_id, "P07", "Sai Krishna"))

            # UPCOMING match
            cursor.execute("""
            INSERT INTO matches (match_name, team_a, team_b, venue, match_date, status, current_innings, total_overs)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, ("Match 2 - JAL vs PRI", "House Jala", "House Prithvi", "College Main Ground", "Tomorrow", "UPCOMING", 1, 10))

            # COMPLETED match
            cursor.execute("""
            INSERT INTO matches (match_name, team_a, team_b, venue, match_date, status, current_innings, total_overs, winner, result_margin)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, ("Match 0 - AKA vs VAY", "House Akasha", "House Vayu", "College Ground", "Yesterday", "COMPLETED", 2, 10, "House Akasha", "by 24 runs"))
            c_match_id = cursor.lastrowid

            # Innings for completed match
            cursor.execute("""
            INSERT INTO innings (match_id, innings_number, batting_team, bowling_team, runs, wickets, overs, balls)
            VALUES (?, 1, 'House Akasha', 'House Vayu', 156, 4, 10, 0)
            """, (c_match_id,))
            cursor.execute("""
            INSERT INTO innings (match_id, innings_number, batting_team, bowling_team, runs, wickets, overs, balls, target)
            VALUES (?, 2, 'House Vayu', 'House Akasha', 132, 7, 10, 0, 157)
            """, (c_match_id,))

        conn.commit()

# ==============================================================================
# MATCH REPOSITORIES & QUERIES
# ==============================================================================

def get_all_matches():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM matches ORDER BY id DESC")
        matches = [dict(row) for row in cursor.fetchall()]
        for m in matches:
            m["teamA"] = m["team_a"]
            m["teamB"] = m["team_b"]
            m["matchNo"] = f"{m['id']:02d}" if isinstance(m["id"], int) else str(m["id"])
            m["date"] = m["match_date"]
            m["time"] = "02:00 PM"
            m["overs"] = m["total_overs"]
            m["innings"] = get_match_innings(m["id"])
            
            inn1 = next((i for i in m["innings"] if i["innings_number"] == 1), None)
            inn2 = next((i for i in m["innings"] if i["innings_number"] == 2), None)
            m["scoreA"] = f"{inn1['runs']}/{inn1['wickets']}" if inn1 else ""
            m["oversA"] = f"{inn1['overs']}.{inn1['balls']}" if inn1 else ""
            m["scoreB"] = f"{inn2['runs']}/{inn2['wickets']}" if inn2 else ("Yet to Bat" if m["status"] == "LIVE" else "")
            m["oversB"] = f"{inn2['overs']}.{inn2['balls']}" if inn2 else ""

            if m["status"] == "LIVE" and inn1:
                # Add liveScorecard summary
                m["liveScorecard"] = {
                    "runs": inn1["runs"],
                    "wickets": inn1["wickets"],
                    "oversCompleted": inn1["overs"],
                    "ballsInOver": inn1["balls"]
                }
        return matches

def get_match_by_id(match_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
        row = cursor.fetchone()
        if not row:
            return None
        match_dict = dict(row)
        match_dict["innings"] = get_match_innings(match_id)
        return match_dict

def get_match_innings(match_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM innings WHERE match_id = ? ORDER BY innings_number ASC", (match_id,))
        return [dict(row) for row in cursor.fetchall()]

def create_match(team_a, team_b, venue="College Ground", match_date="Today", total_overs=10, match_name=None):
    if not team_a or not team_b:
        return False, "Team A and Team B are required"
    if team_a == team_b:
        return False, "Team A and Team B cannot be the same"
    
    if not match_name:
        match_name = f"{team_a} vs {team_b}"

    total_overs = int(total_overs) if total_overs else 10

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO matches (match_name, team_a, team_b, venue, match_date, status, current_innings, total_overs)
        VALUES (?, ?, ?, ?, ?, 'UPCOMING', 1, ?)
        """, (match_name, team_a, team_b, venue, match_date, total_overs))
        match_id = cursor.lastrowid
        conn.commit()

    return True, get_match_by_id(match_id)

def update_match(match_id, team_a=None, team_b=None, venue=None, match_date=None, total_overs=None, status=None):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
        existing = cursor.fetchone()
        if not existing:
            return False, "Match not found"

        updates = []
        params = []
        if team_a:
            updates.append("team_a = ?")
            params.append(team_a)
        if team_b:
            updates.append("team_b = ?")
            params.append(team_b)
        if venue:
            updates.append("venue = ?")
            params.append(venue)
        if match_date:
            updates.append("match_date = ?")
            params.append(match_date)
        if total_overs:
            updates.append("total_overs = ?")
            params.append(int(total_overs))
        if status:
            updates.append("status = ?")
            params.append(status)

        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(match_id)
            cursor.execute(f"UPDATE matches SET {', '.join(updates)} WHERE id = ?", params)
            conn.commit()

    return True, get_match_by_id(match_id)

def delete_match(match_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM matches WHERE id = ?", (match_id,))
        if not cursor.fetchone():
            return False, "Match not found"
        cursor.execute("DELETE FROM matches WHERE id = ?", (match_id,))
        conn.commit()
    return True, f"Match {match_id} deleted successfully"

def start_match(match_id):
    """Starts a match, setting it to LIVE, completing any other live match, and initializing 1st innings."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
        target = cursor.fetchone()
        if not target:
            return False, f"Match {match_id} not found"

        # Complete any other match currently marked LIVE
        cursor.execute("UPDATE matches SET status = 'COMPLETED' WHERE status = 'LIVE' AND id != ?", (match_id,))

        cursor.execute("UPDATE matches SET status = 'LIVE', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (match_id,))

        # Check if innings exists
        cursor.execute("SELECT * FROM innings WHERE match_id = ? AND innings_number = 1", (match_id,))
        inn = cursor.fetchone()
        if not inn:
            cursor.execute("""
            INSERT INTO innings (match_id, innings_number, batting_team, bowling_team, runs, wickets, overs, balls)
            VALUES (?, 1, ?, ?, 0, 0, 0, 0)
            """, (match_id, target["team_a"], target["team_b"]))
            inn_id = cursor.lastrowid
            
            # Add top 2 players of team_a as strikers
            cursor.execute("SELECT * FROM players WHERE team_id = (SELECT id FROM teams WHERE name = ?) ORDER BY id ASC LIMIT 2", (target["team_a"],))
            p_bat = cursor.fetchall()
            b1_name = p_bat[0]["name"] if len(p_bat) > 0 else "Striker 1"
            b1_id = p_bat[0]["id"] if len(p_bat) > 0 else None
            b2_name = p_bat[1]["name"] if len(p_bat) > 1 else "Striker 2"
            b2_id = p_bat[1]["id"] if len(p_bat) > 1 else None

            cursor.execute("""
            INSERT INTO batting_scores (innings_id, player_id, player_name, is_on_strike, batting_order)
            VALUES (?, ?, ?, 1, 1)
            """, (inn_id, b1_id, b1_name))
            cursor.execute("""
            INSERT INTO batting_scores (innings_id, player_id, player_name, is_on_strike, batting_order)
            VALUES (?, ?, ?, 0, 2)
            """, (inn_id, b2_id, b2_name))

            # Add opening bowler of team_b
            cursor.execute("SELECT * FROM players WHERE team_id = (SELECT id FROM teams WHERE name = ?) ORDER BY id ASC LIMIT 1", (target["team_b"],))
            p_bowl = cursor.fetchall()
            bowl_name = p_bowl[0]["name"] if len(p_bowl) > 0 else "Opening Bowler"
            bowl_id = p_bowl[0]["id"] if len(p_bowl) > 0 else None

            cursor.execute("""
            INSERT INTO bowling_scores (innings_id, player_id, player_name, is_current_bowler)
            VALUES (?, ?, ?, 1)
            """, (inn_id, bowl_id, bowl_name))

        conn.commit()

    return True, get_live_match_details()

def pause_match(match_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE matches SET status = 'PAUSED', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (match_id,))
        conn.commit()
    return True, get_match_by_id(match_id)

def complete_match(match_id, winner=None, result_margin=""):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
        m = cursor.fetchone()
        if not m:
            return False, "Match not found"

        winner_team = winner or m["team_a"]
        cursor.execute("""
        UPDATE matches 
        SET status = 'COMPLETED', winner = ?, result_margin = ?, updated_at = CURRENT_TIMESTAMP 
        WHERE id = ?
        """, (winner_team, result_margin, match_id))
        conn.commit()

    return True, get_match_by_id(match_id)

def switch_to_second_innings(match_id):
    """Switches match from 1st innings to 2nd innings, setting target score automatically."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
        m = cursor.fetchone()
        if not m:
            return False, "Match not found"

        cursor.execute("SELECT * FROM innings WHERE match_id = ? AND innings_number = 1", (match_id,))
        inn1 = cursor.fetchone()
        if not inn1:
            return False, "1st innings not found"

        target_score = inn1["runs"] + 1

        # Check if innings 2 already exists
        cursor.execute("SELECT * FROM innings WHERE match_id = ? AND innings_number = 2", (match_id,))
        inn2 = cursor.fetchone()
        if not inn2:
            cursor.execute("""
            INSERT INTO innings (match_id, innings_number, batting_team, bowling_team, runs, wickets, overs, balls, target)
            VALUES (?, 2, ?, ?, 0, 0, 0, 0, ?)
            """, (match_id, inn1["bowling_team"], inn1["batting_team"], target_score))
            inn2_id = cursor.lastrowid

            # Add opening batsmen of chasing team
            cursor.execute("SELECT * FROM players WHERE team_id = (SELECT id FROM teams WHERE name = ?) ORDER BY id ASC LIMIT 2", (inn1["bowling_team"],))
            p_bat = cursor.fetchall()
            b1_name = p_bat[0]["name"] if len(p_bat) > 0 else "Striker"
            b1_id = p_bat[0]["id"] if len(p_bat) > 0 else None
            b2_name = p_bat[1]["name"] if len(p_bat) > 1 else "Non-Striker"
            b2_id = p_bat[1]["id"] if len(p_bat) > 1 else None

            cursor.execute("INSERT INTO batting_scores (innings_id, player_id, player_name, is_on_strike, batting_order) VALUES (?, ?, ?, 1, 1)", (inn2_id, b1_id, b1_name))
            cursor.execute("INSERT INTO batting_scores (innings_id, player_id, player_name, is_on_strike, batting_order) VALUES (?, ?, ?, 0, 2)", (inn2_id, b2_id, b2_name))

            # Add opening bowler of defending team
            cursor.execute("SELECT * FROM players WHERE team_id = (SELECT id FROM teams WHERE name = ?) ORDER BY id ASC LIMIT 1", (inn1["batting_team"],))
            p_bowl = cursor.fetchall()
            bowl_name = p_bowl[0]["name"] if len(p_bowl) > 0 else "Opening Bowler"
            bowl_id = p_bowl[0]["id"] if len(p_bowl) > 0 else None

            cursor.execute("INSERT INTO bowling_scores (innings_id, player_id, player_name, is_current_bowler) VALUES (?, ?, ?, 1)", (inn2_id, bowl_id, bowl_name))

        cursor.execute("UPDATE matches SET current_innings = 2, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (match_id,))
        conn.commit()

    return True, get_live_match_details()

# ==============================================================================
# AUTHORITATIVE CRICKET SCORING CALCULATION ENGINE (ACID & EVENT-SOURCED)
# ==============================================================================

def recalculate_innings_state(innings_id, conn):
    """
    Pure authoritative recalculation of an innings from its ball_events.
    Ensures complete mathematical consistency for deliveries, overs, maidens,
    batsman runs/balls/4s/6s, bowler runs/wickets/economy, and strike rotation.
    """
    cursor = conn.cursor()

    # 1. Fetch innings and match info
    cursor.execute("SELECT * FROM innings WHERE id = ?", (innings_id,))
    inn = cursor.fetchone()
    if not inn:
        return

    cursor.execute("SELECT * FROM matches WHERE id = ?", (inn["match_id"],))
    match_info = cursor.fetchone()
    total_overs = match_info["total_overs"] if match_info else 10

    # 2. Fetch all ball events for this innings in chronological order
    cursor.execute("SELECT * FROM ball_events WHERE innings_id = ? ORDER BY id ASC", (innings_id,))
    events = [dict(r) for r in cursor.fetchall()]

    # Reset in-memory trackers
    total_runs = 0
    total_wickets = 0
    legal_balls_count = 0

    batsmen_stats = {}   # name -> {runs, balls, fours, sixes, is_out, dismissal, player_id, batting_order}
    bowlers_stats = {}   # name -> {legal_balls, maidens, runs, wickets, player_id, over_runs_map}
    
    # Track current striker and non-striker
    # Seed with existing batting scores order if any
    cursor.execute("SELECT * FROM batting_scores WHERE innings_id = ? ORDER BY batting_order ASC", (innings_id,))
    initial_bat = [dict(r) for r in cursor.fetchall()]

    striker_name = initial_bat[0]["player_name"] if len(initial_bat) > 0 else "Striker"
    non_striker_name = initial_bat[1]["player_name"] if len(initial_bat) > 1 else "Non-Striker"

    for b in initial_bat:
        batsmen_stats[b["player_name"]] = {
            "player_id": b["player_id"],
            "runs": 0, "balls": 0, "fours": 0, "sixes": 0,
            "is_out": 0, "dismissal": "not out",
            "batting_order": b["batting_order"]
        }

    cursor.execute("SELECT * FROM bowling_scores WHERE innings_id = ?", (innings_id,))
    initial_bowl = [dict(r) for r in cursor.fetchall()]
    current_bowler_name = initial_bowl[0]["player_name"] if len(initial_bowl) > 0 else "Bowler"

    for bw in initial_bowl:
        bowlers_stats[bw["player_name"]] = {
            "player_id": bw["player_id"],
            "legal_balls": 0, "maidens": 0, "runs": 0, "wickets": 0,
            "overs_dict": {} # over_num -> runs in over
        }

    # Replay all ball events
    for ev in events:
        b_name = ev["batsman_name"]
        bw_name = ev["bowler_name"]
        runs = ev["runs"]
        extra = ev["extra_type"]
        is_wicket = ev["wicket"]
        w_type = ev["wicket_type"]
        out_player = ev["out_player_name"] or b_name

        if b_name not in batsmen_stats:
            batsmen_stats[b_name] = {
                "player_id": ev["batsman_id"], "runs": 0, "balls": 0, "fours": 0, "sixes": 0,
                "is_out": 0, "dismissal": "not out", "batting_order": len(batsmen_stats) + 1
            }

        if bw_name not in bowlers_stats:
            bowlers_stats[bw_name] = {
                "player_id": ev["bowler_id"], "legal_balls": 0, "maidens": 0, "runs": 0, "wickets": 0,
                "overs_dict": {}
            }

        current_bowler_name = bw_name
        current_over_idx = legal_balls_count // 6

        # Calculate runs
        ball_total_runs = runs + ev["extras"]
        total_runs += ball_total_runs

        # Bowler runs conceded (byes and leg byes don't count against bowler)
        bowler_conceded = runs
        if extra in ("WIDE", "NO BALL"):
            bowler_conceded += ev["extras"]
        bowlers_stats[bw_name]["runs"] += bowler_conceded
        bowlers_stats[bw_name]["overs_dict"].setdefault(current_over_idx, 0)
        bowlers_stats[bw_name]["overs_dict"][current_over_idx] += bowler_conceded

        # Batsman runs and balls faced
        if extra not in ("WIDE", "BYE", "LEG BYE"):
            batsmen_stats[b_name]["runs"] += runs
            if runs == 4:
                batsmen_stats[b_name]["fours"] += 1
            elif runs == 6:
                batsmen_stats[b_name]["sixes"] += 1

        if extra != "WIDE":
            batsmen_stats[b_name]["balls"] += 1

        # Legal delivery check
        is_legal = extra not in ("WIDE", "NO BALL")
        if is_legal:
            legal_balls_count += 1
            bowlers_stats[bw_name]["legal_balls"] += 1

        # Wicket processing
        if is_wicket:
            total_wickets += 1
            if w_type != "RUN OUT":
                bowlers_stats[bw_name]["wickets"] += 1

            dismissal_str = f"c & b {bw_name}" if w_type == "CAUGHT" else (f"b {bw_name}" if w_type == "BOWLED" else f"{w_type or 'out'} b {bw_name}")
            if out_player in batsmen_stats:
                batsmen_stats[out_player]["is_out"] = 1
                batsmen_stats[out_player]["dismissal"] = dismissal_str

            # Next batsman replaces out player
            if out_player == striker_name:
                striker_name = None
            elif out_player == non_striker_name:
                non_striker_name = None

        # Strike rotation
        # If striker scored odd runs (and not out, or general running runs)
        if runs % 2 == 1 and striker_name and non_striker_name:
            striker_name, non_striker_name = non_striker_name, striker_name

        # Over completion check
        if is_legal and (legal_balls_count % 6 == 0):
            # End of over: switch strike
            if striker_name and non_striker_name:
                striker_name, non_striker_name = non_striker_name, striker_name

    # Calculate maidens for bowlers
    for bw_name, b_data in bowlers_stats.items():
        completed_overs = b_data["legal_balls"] // 6
        maidens = 0
        for ov_idx, ov_runs in b_data["overs_dict"].items():
            if ov_runs == 0 and completed_overs > 0:
                maidens += 1
        b_data["maidens"] = maidens

    # Compute overs and balls for innings
    completed_overs = legal_balls_count // 6
    balls_in_over = legal_balls_count % 6

    # Update innings table
    cursor.execute("""
    UPDATE innings 
    SET runs = ?, wickets = ?, overs = ?, balls = ?, updated_at = CURRENT_TIMESTAMP
    WHERE id = ?
    """, (total_runs, total_wickets, completed_overs, balls_in_over, innings_id))

    # Update batting_scores table
    for b_name, b_info in batsmen_stats.items():
        sr = round((b_info["runs"] / b_info["balls"] * 100.0), 2) if b_info["balls"] > 0 else 0.0
        on_strike = 1 if (b_name == striker_name and not b_info["is_out"]) else 0

        cursor.execute("SELECT id FROM batting_scores WHERE innings_id = ? AND player_name = ?", (innings_id, b_name))
        existing = cursor.fetchone()
        if existing:
            cursor.execute("""
            UPDATE batting_scores
            SET runs = ?, balls = ?, fours = ?, sixes = ?, strike_rate = ?, is_out = ?, dismissal_text = ?, is_on_strike = ?
            WHERE id = ?
            """, (b_info["runs"], b_info["balls"], b_info["fours"], b_info["sixes"], sr, b_info["is_out"], b_info["dismissal"], on_strike, existing["id"]))
        else:
            cursor.execute("""
            INSERT INTO batting_scores (innings_id, player_id, player_name, runs, balls, fours, sixes, strike_rate, is_out, dismissal_text, batting_order, is_on_strike)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (innings_id, b_info["player_id"], b_name, b_info["runs"], b_info["balls"], b_info["fours"], b_info["sixes"], sr, b_info["is_out"], b_info["dismissal"], b_info["batting_order"], on_strike))

    # Update bowling_scores table
    for bw_name, bw_info in bowlers_stats.items():
        b_ov = round(bw_info["legal_balls"] // 6 + (bw_info["legal_balls"] % 6) / 10.0, 1)
        econ = round(bw_info["runs"] / (bw_info["legal_balls"] / 6.0), 2) if bw_info["legal_balls"] > 0 else 0.0
        is_cur = 1 if bw_name == current_bowler_name else 0

        cursor.execute("SELECT id FROM bowling_scores WHERE innings_id = ? AND player_name = ?", (innings_id, bw_name))
        existing_bw = cursor.fetchone()
        if existing_bw:
            cursor.execute("""
            UPDATE bowling_scores
            SET overs = ?, legal_balls = ?, maidens = ?, runs = ?, wickets = ?, economy = ?, is_current_bowler = ?
            WHERE id = ?
            """, (b_ov, bw_info["legal_balls"], bw_info["maidens"], bw_info["runs"], bw_info["wickets"], econ, is_cur, existing_bw["id"]))
        else:
            cursor.execute("""
            INSERT INTO bowling_scores (innings_id, player_id, player_name, overs, legal_balls, maidens, runs, wickets, economy, is_current_bowler)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (innings_id, bw_info["player_id"], bw_name, b_ov, bw_info["legal_balls"], bw_info["maidens"], bw_info["runs"], bw_info["wickets"], econ, is_cur))

    # Check match conclusion rules:
    # 1. In 2nd innings, if runs >= target -> chasing team won!
    if inn["innings_number"] == 2 and inn["target"]:
        if total_runs >= inn["target"]:
            winner_team = inn["batting_team"]
            margin = f"by {10 - total_wickets} wickets"
            cursor.execute("UPDATE matches SET status = 'COMPLETED', winner = ?, result_margin = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (winner_team, margin, inn["match_id"]))
        elif (completed_overs >= total_overs) or (total_wickets >= 10):
            if total_runs == inn["target"] - 1:
                cursor.execute("UPDATE matches SET status = 'COMPLETED', winner = 'Match Tied', result_margin = '', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (inn["match_id"],))
            else:
                winner_team = inn["bowling_team"]
                margin = f"by {inn['target'] - 1 - total_runs} runs"
                cursor.execute("UPDATE matches SET status = 'COMPLETED', winner = ?, result_margin = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (winner_team, margin, inn["match_id"]))

def record_ball(match_id, runs=0, extra=None, batsman_name=None, bowler_name=None):
    """
    Authoritative Delivery Recorder with full ACID database transaction.
    Records ball_event and recalculates pure database state.
    """
    with get_db() as conn:
        cursor = conn.cursor()

        # Find active match and current innings
        cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
        match = cursor.fetchone()
        if not match:
            return False, f"Match {match_id} not found"
        if match["status"] not in ("LIVE", "PAUSED"):
            return False, f"Match is {match['status']}, not LIVE"

        curr_inn_num = match["current_innings"]
        cursor.execute("SELECT * FROM innings WHERE match_id = ? AND innings_number = ?", (match_id, curr_inn_num))
        inn = cursor.fetchone()
        if not inn:
            return False, "Active innings not found"

        inn_id = inn["id"]

        # Determine current striker and bowler if not provided
        if not batsman_name:
            cursor.execute("SELECT player_name FROM batting_scores WHERE innings_id = ? AND is_on_strike = 1 AND is_out = 0 LIMIT 1", (inn_id,))
            st_row = cursor.fetchone()
            batsman_name = st_row["player_name"] if st_row else "Striker"

        if not bowler_name:
            cursor.execute("SELECT player_name FROM bowling_scores WHERE innings_id = ? AND is_current_bowler = 1 LIMIT 1", (inn_id,))
            bw_row = cursor.fetchone()
            bowler_name = bw_row["player_name"] if bw_row else "Bowler"

        runs = int(runs)
        extras = 0
        extra_type = extra.strip().upper() if extra else None

        if extra_type in ("WIDE", "NO BALL"):
            extras = 1
        elif extra_type in ("BYE", "LEG BYE"):
            extras = runs
            runs = 0  # batsman scores 0 off byes/leg-byes

        over_num = inn["overs"]
        ball_num = inn["balls"] + 1 if extra_type not in ("WIDE", "NO BALL") else inn["balls"]

        # Insert ball_event
        cursor.execute("""
        INSERT INTO ball_events (innings_id, over_number, ball_number, batsman_name, bowler_name, runs, extras, extra_type, wicket, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
        """, (inn_id, over_num, ball_num, batsman_name, bowler_name, runs, extras, extra_type))

        # Re-calculate pure state from events
        recalculate_innings_state(inn_id, conn)
        conn.commit()

    return True, get_live_match_details(match_id)

def record_wicket(match_id, new_batter_name="Next Batter", wicket_type="BOWLED", out_batter_name=None, bowler_name=None):
    """
    Authoritative Wicket Recorder with full ACID database transaction.
    """
    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
        match = cursor.fetchone()
        if not match:
            return False, f"Match {match_id} not found"

        curr_inn_num = match["current_innings"]
        cursor.execute("SELECT * FROM innings WHERE match_id = ? AND innings_number = ?", (match_id, curr_inn_num))
        inn = cursor.fetchone()
        if not inn:
            return False, "Active innings not found"

        inn_id = inn["id"]

        # Determine out batsman
        if not out_batter_name:
            cursor.execute("SELECT player_name FROM batting_scores WHERE innings_id = ? AND is_on_strike = 1 AND is_out = 0 LIMIT 1", (inn_id,))
            st_row = cursor.fetchone()
            out_batter_name = st_row["player_name"] if st_row else "Striker"

        if not bowler_name:
            cursor.execute("SELECT player_name FROM bowling_scores WHERE innings_id = ? AND is_current_bowler = 1 LIMIT 1", (inn_id,))
            bw_row = cursor.fetchone()
            bowler_name = bw_row["player_name"] if bw_row else "Bowler"

        over_num = inn["overs"]
        ball_num = inn["balls"] + 1

        # Insert wicket ball_event
        cursor.execute("""
        INSERT INTO ball_events (innings_id, over_number, ball_number, batsman_name, bowler_name, runs, extras, wicket, wicket_type, out_player_name, timestamp)
        VALUES (?, ?, ?, ?, ?, 0, 0, 1, ?, ?, CURRENT_TIMESTAMP)
        """, (inn_id, over_num, ball_num, out_batter_name, bowler_name, wicket_type.upper(), out_batter_name))

        # Add new batter into batting scores
        if new_batter_name:
            cursor.execute("SELECT COUNT(*) AS count FROM batting_scores WHERE innings_id = ?", (inn_id,))
            b_count = cursor.fetchone()["count"]
            cursor.execute("""
            INSERT INTO batting_scores (innings_id, player_name, runs, balls, fours, sixes, strike_rate, is_out, batting_order, is_on_strike)
            VALUES (?, ?, 0, 0, 0, 0, 0.0, 0, ?, 1)
            """, (inn_id, new_batter_name, b_count + 1))

        # Re-calculate pure state from events
        recalculate_innings_state(inn_id, conn)
        conn.commit()

    return True, get_live_match_details(match_id)

def undo_last_ball(match_id):
    """
    Undo system:
    1. Identify last ball_event in active innings.
    2. Remove event.
    3. Authoritatively recalculate innings, batting scores, bowler scores from remaining events.
    """
    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
        match = cursor.fetchone()
        if not match:
            return False, f"Match {match_id} not found"

        curr_inn_num = match["current_innings"]
        cursor.execute("SELECT * FROM innings WHERE match_id = ? AND innings_number = ?", (match_id, curr_inn_num))
        inn = cursor.fetchone()
        if not inn:
            return False, "Active innings not found"

        inn_id = inn["id"]

        # Find last ball event
        cursor.execute("SELECT * FROM ball_events WHERE innings_id = ? ORDER BY id DESC LIMIT 1", (inn_id,))
        last_event = cursor.fetchone()
        if not last_event:
            return False, "No ball events to undo for this innings"

        # Delete the last event
        cursor.execute("DELETE FROM ball_events WHERE id = ?", (last_event["id"],))

        # Recalculate pure state
        recalculate_innings_state(inn_id, conn)
        conn.commit()

    return True, get_live_match_details(match_id)

def set_live_score(match_id, runs, wickets, overs_val):
    """Direct score calibration endpoint for Admin panel overrides."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
        m = cursor.fetchone()
        if not m:
            return False, "Match not found"

        curr_inn_num = m["current_innings"]
        cursor.execute("SELECT * FROM innings WHERE match_id = ? AND innings_number = ?", (match_id, curr_inn_num))
        inn = cursor.fetchone()
        if not inn:
            return False, "Innings not found"

        # Parse overs (e.g. 8.3 -> 8 overs, 3 balls)
        try:
            o_parts = str(overs_val).split(".")
            ov_comp = int(o_parts[0])
            b_in_ov = int(o_parts[1]) if len(o_parts) > 1 else 0
        except Exception:
            ov_comp = 0
            b_in_ov = 0

        cursor.execute("""
        UPDATE innings
        SET runs = ?, wickets = ?, overs = ?, balls = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """, (int(runs), int(wickets), ov_comp, b_in_ov, inn["id"]))
        conn.commit()

    return True, get_live_match_details(match_id)

# ==============================================================================
# LIVE SCORECARD & PUBLIC API AGGREGATION
# ==============================================================================

def get_live_match_details(match_id=None):
    """Returns the comprehensive real-time live match state for Home and Admin panels."""
    with get_db() as conn:
        cursor = conn.cursor()

        if match_id:
            cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
        else:
            cursor.execute("SELECT * FROM matches WHERE status = 'LIVE' ORDER BY id DESC LIMIT 1")
        
        m_row = cursor.fetchone()
        if not m_row:
            # Fallback to any recent match if none marked LIVE
            cursor.execute("SELECT * FROM matches ORDER BY id DESC LIMIT 1")
            m_row = cursor.fetchone()

        if not m_row:
            return None

        match = dict(m_row)
        m_id = match["id"]

        # Fetch innings
        cursor.execute("SELECT * FROM innings WHERE match_id = ? ORDER BY innings_number ASC", (m_id,))
        innings_list = [dict(r) for r in cursor.fetchall()]

        curr_inn_num = match["current_innings"]
        current_inn = next((i for i in innings_list if i["innings_number"] == curr_inn_num), None)
        if not current_inn and innings_list:
            current_inn = innings_list[-1]

        live_data = {
            "id": match["id"],
            "match_name": match["match_name"],
            "team_a": match["team_a"],
            "team_b": match["team_b"],
            "venue": match["venue"],
            "match_date": match["match_date"],
            "status": match["status"],
            "current_innings": match["current_innings"],
            "total_overs": match["total_overs"],
            "winner": match["winner"],
            "result_margin": match["result_margin"],
            "innings": innings_list,
            "current_inn": current_inn
        }

        if current_inn:
            inn_id = current_inn["id"]

            # Current batsmen (not out, currently on pitch)
            cursor.execute("""
            SELECT * FROM batting_scores 
            WHERE innings_id = ? AND is_out = 0 
            ORDER BY is_on_strike DESC, batting_order ASC 
            LIMIT 2
            """, (inn_id,))
            current_batsmen = [dict(r) for r in cursor.fetchall()]
            striker = current_batsmen[0] if len(current_batsmen) > 0 else None
            non_striker = current_batsmen[1] if len(current_batsmen) > 1 else None

            # Current bowler
            cursor.execute("""
            SELECT * FROM bowling_scores 
            WHERE innings_id = ? AND is_current_bowler = 1 
            LIMIT 1
            """, (inn_id,))
            bw_row = cursor.fetchone()
            current_bowler = dict(bw_row) if bw_row else None

            # Recent deliveries (last 18 balls for timeline)
            cursor.execute("""
            SELECT * FROM ball_events 
            WHERE innings_id = ? 
            ORDER BY id DESC LIMIT 18
            """, (inn_id,))
            recent_balls = [dict(r) for r in cursor.fetchall()]
            recent_balls.reverse()

            # Group recent balls into recent overs
            overs_dict = {}
            for b in recent_balls:
                ov = b["over_number"]
                overs_dict.setdefault(ov, []).append(b)
            
            recent_overs = []
            for ov_num in sorted(overs_dict.keys(), reverse=True):
                recent_overs.append({
                    "over_number": ov_num,
                    "balls": overs_dict[ov_num]
                })

            # Calculate Run Rates
            completed_overs = current_inn["overs"]
            balls = current_inn["balls"]
            total_legal_overs = completed_overs + (balls / 6.0)
            crr = round(current_inn["runs"] / total_legal_overs, 2) if total_legal_overs > 0 else 0.0

            rrr = None
            if current_inn.get("target"):
                needed_runs = current_inn["target"] - current_inn["runs"]
                remaining_balls = (match["total_overs"] * 6) - (completed_overs * 6 + balls)
                if remaining_balls > 0 and needed_runs > 0:
                    rrr = round(needed_runs / (remaining_balls / 6.0), 2)
                elif needed_runs <= 0:
                    rrr = 0.0

            live_data["current_batsmen"] = current_batsmen
            live_data["striker"] = striker
            live_data["non_striker"] = non_striker
            live_data["current_bowler"] = current_bowler
            live_data["recent_overs"] = recent_overs
            live_data["crr"] = crr
            live_data["rrr"] = rrr

            # Admin & Legacy Scoreboard Bridge Fields
            balls_in_cur_over = []
            if recent_overs and len(recent_overs) > 0:
                for b in recent_overs[0]["balls"]:
                    if b.get("wicket"):
                        balls_in_cur_over.append("W")
                    elif b.get("extra_type"):
                        balls_in_cur_over.append(b["extra_type"][0])
                    else:
                        balls_in_cur_over.append(str(b["runs"]))

            live_data["teamA"] = match["team_a"]
            live_data["teamB"] = match["team_b"]
            live_data["matchNo"] = f"{match['id']:02d}" if isinstance(match["id"], int) else str(match["id"])
            live_data["scoreA"] = f"{current_inn['runs']}/{current_inn['wickets']}"
            live_data["oversA"] = f"{current_inn['overs']}.{current_inn['balls']}"
            live_data["liveScorecard"] = {
                "runs": current_inn["runs"],
                "wickets": current_inn["wickets"],
                "oversCompleted": current_inn["overs"],
                "ballsInOver": current_inn["balls"],
                "striker": {"name": striker["player_name"], "runs": striker["runs"], "balls": striker["balls"]} if striker else {"name": "Striker", "runs": 0, "balls": 0},
                "nonStriker": {"name": non_striker["player_name"], "runs": non_striker["runs"], "balls": non_striker["balls"]} if non_striker else {"name": "Non-Striker", "runs": 0, "balls": 0},
                "bowler": {"name": current_bowler["player_name"], "wickets": current_bowler["wickets"], "runs": current_bowler["runs"]} if current_bowler else {"name": "Bowler", "wickets": 0, "runs": 0},
                "currentOverBalls": balls_in_cur_over
            }

        return live_data

def get_match_full_scorecard(match_id):
    """Returns the complete, authoritative scorecard for both innings."""
    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
        m_row = cursor.fetchone()
        if not m_row:
            return None

        match = dict(m_row)

        cursor.execute("SELECT * FROM innings WHERE match_id = ? ORDER BY innings_number ASC", (match_id,))
        innings_rows = [dict(r) for r in cursor.fetchall()]

        scorecard_innings = []
        for inn in innings_rows:
            inn_id = inn["id"]

            # Batting scorecard
            cursor.execute("SELECT * FROM batting_scores WHERE innings_id = ? ORDER BY batting_order ASC", (inn_id,))
            batting = [dict(r) for r in cursor.fetchall()]

            # Bowling scorecard
            cursor.execute("SELECT * FROM bowling_scores WHERE innings_id = ? ORDER BY legal_balls DESC", (inn_id,))
            bowling = [dict(r) for r in cursor.fetchall()]

            # Fall of wickets
            cursor.execute("""
            SELECT * FROM ball_events 
            WHERE innings_id = ? AND wicket = 1 
            ORDER BY id ASC
            """, (inn_id,))
            fow_events = [dict(r) for r in cursor.fetchall()]
            
            # Extras breakdown
            cursor.execute("SELECT SUM(extras) AS total_extras FROM ball_events WHERE innings_id = ?", (inn_id,))
            ext_row = cursor.fetchone()
            total_extras = ext_row["total_extras"] or 0

            cursor.execute("SELECT COUNT(*) as count FROM ball_events WHERE innings_id = ? AND extra_type = 'WIDE'", (inn_id,))
            wides = cursor.fetchone()["count"]
            cursor.execute("SELECT COUNT(*) as count FROM ball_events WHERE innings_id = ? AND extra_type = 'NO BALL'", (inn_id,))
            noballs = cursor.fetchone()["count"]
            cursor.execute("SELECT SUM(extras) as sum_byes FROM ball_events WHERE innings_id = ? AND extra_type = 'BYE'", (inn_id,))
            byes = cursor.fetchone()["sum_byes"] or 0
            cursor.execute("SELECT SUM(extras) as sum_lb FROM ball_events WHERE innings_id = ? AND extra_type = 'LEG BYE'", (inn_id,))
            legbyes = cursor.fetchone()["sum_lb"] or 0

            scorecard_innings.append({
                "innings_info": inn,
                "batting": batting,
                "bowling": bowling,
                "fall_of_wickets": fow_events,
                "extras": {
                    "total": total_extras,
                    "wides": wides,
                    "noballs": noballs,
                    "byes": byes,
                    "legbyes": legbyes
                }
            })

        return {
            "match": match,
            "scorecards": scorecard_innings
        }

# ==============================================================================
# TEAMS & PLAYERS REPOSITORIES & OPERATIONS
# ==============================================================================

def get_all_teams():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM teams ORDER BY name ASC")
        teams = [dict(r) for r in cursor.fetchall()]
        for t in teams:
            t["short"] = t.get("short_name", "")
        return teams

def create_team(name, short="", captain="", color="#1a73e8"):
    name = (name or "").strip()
    if not name:
        return False, "Team name is required"
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM teams WHERE name = ?", (name,))
        if cursor.fetchone():
            return False, f"Team '{name}' already exists"
        cursor.execute("SELECT COUNT(*) as count FROM teams")
        t_id = f"T{cursor.fetchone()['count'] + 1}"
        short = (short or name[:3]).upper().strip()
        cursor.execute("""
        INSERT INTO teams (id, name, short_name, captain, color)
        VALUES (?, ?, ?, ?, ?)
        """, (t_id, name, short, captain or "TBD", color or "#1a73e8"))
        conn.commit()
        return True, {"id": t_id, "name": name, "short": short, "short_name": short, "captain": captain or "TBD", "color": color}

def update_team(team_id, name=None, short=None, captain=None, color=None):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM teams WHERE id = ? OR name = ?", (team_id, team_id))
        t = cursor.fetchone()
        if not t:
            return False, "Team not found"
        real_id = t["id"]
        old_name = t["name"]

        updates = []
        params = []
        if name:
            updates.append("name = ?")
            params.append(name.strip())
        if short:
            updates.append("short_name = ?")
            params.append(short.strip().upper())
        if captain:
            updates.append("captain = ?")
            params.append(captain.strip())
        if color:
            updates.append("color = ?")
            params.append(color.strip())

        if updates:
            params.append(real_id)
            cursor.execute(f"UPDATE teams SET {', '.join(updates)} WHERE id = ?", params)
            if name and name.strip() != old_name:
                cursor.execute("UPDATE matches SET team_a = ? WHERE team_a = ?", (name.strip(), old_name))
                cursor.execute("UPDATE matches SET team_b = ? WHERE team_b = ?", (name.strip(), old_name))
            conn.commit()

        cursor.execute("SELECT * FROM teams WHERE id = ?", (real_id,))
        res = dict(cursor.fetchone())
        res["short"] = res.get("short_name", "")
        return True, res

def delete_team(team_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM teams WHERE id = ? OR name = ?", (team_id, team_id))
        t = cursor.fetchone()
        if not t:
            return False, "Team not found"
        real_id = t["id"]
        t_name = t["name"]
        cursor.execute("DELETE FROM players WHERE team_id = ?", (real_id,))
        cursor.execute("DELETE FROM teams WHERE id = ?", (real_id,))
        conn.commit()
        return True, f"Team {t_name} deleted successfully"

def get_all_players():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT p.*, t.name as team_name, t.color as team_color, p.jersey_number as jersey,
               COALESCE(t.name, 'Unassigned') as team
        FROM players p 
        LEFT JOIN teams t ON p.team_id = t.id 
        ORDER BY p.name ASC
        """)
        return [dict(r) for r in cursor.fetchall()]

def create_player(name, team_name_or_id, role="Batsman", jersey=0):
    name = (name or "").strip()
    if not name:
        return False, "Player name is required"
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM teams WHERE id = ? OR name = ?", (team_name_or_id, team_name_or_id))
        t = cursor.fetchone()
        t_id = t["id"] if t else None
        t_name = t["name"] if t else team_name_or_id

        cursor.execute("SELECT COUNT(*) as count FROM players")
        p_id = f"P{cursor.fetchone()['count'] + 1:02d}"
        jersey_num = int(jersey) if jersey else 0

        cursor.execute("""
        INSERT INTO players (id, team_id, name, role, jersey_number)
        VALUES (?, ?, ?, ?, ?)
        """, (p_id, t_id, name, role or "Batsman", jersey_num))
        conn.commit()

        return True, {
            "id": p_id, "name": name, "team_id": t_id, "team": t_name,
            "role": role or "Batsman", "jersey": jersey_num, "jersey_number": jersey_num
        }

def update_player(player_id, name=None, team_name_or_id=None, role=None, jersey=None):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM players WHERE id = ?", (player_id,))
        p = cursor.fetchone()
        if not p:
            return False, "Player not found"

        updates = []
        params = []
        if name:
            updates.append("name = ?")
            params.append(name.strip())
        if team_name_or_id:
            cursor.execute("SELECT id FROM teams WHERE id = ? OR name = ?", (team_name_or_id, team_name_or_id))
            t = cursor.fetchone()
            if t:
                updates.append("team_id = ?")
                params.append(t["id"])
        if role:
            updates.append("role = ?")
            params.append(role)
        if jersey is not None:
            updates.append("jersey_number = ?")
            params.append(int(jersey))

        if updates:
            params.append(player_id)
            cursor.execute(f"UPDATE players SET {', '.join(updates)} WHERE id = ?", params)
            conn.commit()

        cursor.execute("""
        SELECT p.*, t.name as team_name, p.jersey_number as jersey, COALESCE(t.name, 'Unassigned') as team 
        FROM players p LEFT JOIN teams t ON p.team_id = t.id WHERE p.id = ?
        """, (player_id,))
        return True, dict(cursor.fetchone())

def delete_player(player_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM players WHERE id = ?", (player_id,))
        p = cursor.fetchone()
        if not p:
            return False, "Player not found"
        p_name = p["name"]
        cursor.execute("DELETE FROM players WHERE id = ?", (player_id,))
        conn.commit()
        return True, f"Player {p_name} deleted successfully"

def set_captain(team_name_or_id, player_name):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM teams WHERE id = ? OR name = ?", (team_name_or_id, team_name_or_id))
        t = cursor.fetchone()
        if not t:
            return False, "Team not found"
        cursor.execute("UPDATE teams SET captain = ? WHERE id = ?", (player_name, t["id"]))
        conn.commit()
        return True, f"{player_name} appointed as captain"

def set_wicketkeeper(player_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE players SET role = 'Wicketkeeper' WHERE id = ?", (player_id,))
        conn.commit()
        return True, "Player role updated to Wicketkeeper"

# ==============================================================================
# MATCH ADVANCED CONTROLS (RESUME, RESET, SWAP STRIKE, BOWLER ASSIGN)
# ==============================================================================

def resume_match(match_id):
    with get_db() as conn:
        cursor = conn.cursor()
        # Ensure only 1 match is live
        cursor.execute("UPDATE matches SET status = 'PAUSED' WHERE status = 'LIVE' AND id != ?", (match_id,))
        cursor.execute("UPDATE matches SET status = 'LIVE', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (match_id,))
        conn.commit()
    return True, get_live_match_details(match_id)

def reset_match(match_id):
    """Purges all match delivery history and resets to 0/0 (0.0 ov) in UPCOMING status."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
        m = cursor.fetchone()
        if not m:
            return False, "Match not found"

        # Delete ball events for all innings of this match
        cursor.execute("DELETE FROM ball_events WHERE innings_id IN (SELECT id FROM innings WHERE match_id = ?)", (match_id,))
        cursor.execute("DELETE FROM batting_scores WHERE innings_id IN (SELECT id FROM innings WHERE match_id = ?)", (match_id,))
        cursor.execute("DELETE FROM bowling_scores WHERE innings_id IN (SELECT id FROM innings WHERE match_id = ?)", (match_id,))
        cursor.execute("DELETE FROM innings WHERE match_id = ? AND innings_number = 2", (match_id,))
        
        cursor.execute("""
        UPDATE innings SET runs = 0, wickets = 0, overs = 0, balls = 0, target = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE match_id = ? AND innings_number = 1
        """, (match_id,))

        cursor.execute("""
        UPDATE matches SET status = 'UPCOMING', current_innings = 1, winner = '', result_margin = '', updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """, (match_id,))
        conn.commit()

    return True, get_match_by_id(match_id)

def select_active_match(match_id):
    """Selects a specific match as the active LIVE match."""
    return start_match(match_id)

def swap_strike(match_id):
    """Manually rotates strike between striker and non-striker on pitch."""
    with get_db() as conn:
        cursor = conn.cursor()
        live = get_live_match_details(match_id)
        if not live or not live.get("current_inn"):
            return False, "No active innings found"
        inn_id = live["current_inn"]["id"]

        cursor.execute("SELECT * FROM batting_scores WHERE innings_id = ? AND is_out = 0 ORDER BY is_on_strike DESC LIMIT 2", (inn_id,))
        batsmen = [dict(r) for r in cursor.fetchall()]
        if len(batsmen) < 2:
            return False, "Need at least two batsmen on pitch to swap strike"

        b1_id = batsmen[0]["id"]
        b2_id = batsmen[1]["id"]
        # Swap on_strike flags
        cursor.execute("UPDATE batting_scores SET is_on_strike = 0 WHERE id = ?", (b1_id,))
        cursor.execute("UPDATE batting_scores SET is_on_strike = 1 WHERE id = ?", (b2_id,))
        conn.commit()

    return True, get_live_match_details(match_id)

def set_current_striker(match_id, player_name):
    with get_db() as conn:
        cursor = conn.cursor()
        live = get_live_match_details(match_id)
        if not live or not live.get("current_inn"):
            return False, "No active innings found"
        inn_id = live["current_inn"]["id"]

        cursor.execute("UPDATE batting_scores SET is_on_strike = 0 WHERE innings_id = ?", (inn_id,))
        cursor.execute("UPDATE batting_scores SET is_on_strike = 1 WHERE innings_id = ? AND player_name = ?", (inn_id, player_name))
        conn.commit()
    return True, get_live_match_details(match_id)

def set_current_bowler(match_id, player_name):
    with get_db() as conn:
        cursor = conn.cursor()
        live = get_live_match_details(match_id)
        if not live or not live.get("current_inn"):
            return False, "No active innings found"
        inn_id = live["current_inn"]["id"]

        cursor.execute("UPDATE bowling_scores SET is_current_bowler = 0 WHERE innings_id = ?", (inn_id,))
        cursor.execute("SELECT id FROM bowling_scores WHERE innings_id = ? AND player_name = ?", (inn_id, player_name))
        bw = cursor.fetchone()
        if bw:
            cursor.execute("UPDATE bowling_scores SET is_current_bowler = 1 WHERE id = ?", (bw["id"],))
        else:
            cursor.execute("""
            INSERT INTO bowling_scores (innings_id, player_name, overs, legal_balls, maidens, runs, wickets, economy, is_current_bowler)
            VALUES (?, ?, 0.0, 0, 0, 0, 0, 0.0, 1)
            """, (inn_id, player_name))
        conn.commit()
    return True, get_live_match_details(match_id)

def get_dashboard_stats():
    """Authoritative dashboard counts calculated directly from database tables."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM matches")
        total_matches = cursor.fetchone()["count"]
        cursor.execute("SELECT COUNT(*) as count FROM matches WHERE status = 'LIVE'")
        live_matches = cursor.fetchone()["count"]
        cursor.execute("SELECT COUNT(*) as count FROM matches WHERE status = 'COMPLETED'")
        completed_matches = cursor.fetchone()["count"]
        cursor.execute("SELECT COUNT(*) as count FROM matches WHERE status = 'UPCOMING'")
        upcoming_matches = cursor.fetchone()["count"]
        cursor.execute("SELECT COUNT(*) as count FROM teams")
        total_teams = cursor.fetchone()["count"]
        cursor.execute("SELECT COUNT(*) as count FROM players")
        total_players = cursor.fetchone()["count"]

        return {
            "total_matches": total_matches,
            "live_matches": live_matches,
            "completed_matches": completed_matches,
            "upcoming_matches": upcoming_matches,
            "total_teams": total_teams,
            "total_players": total_players
        }

def recalculate_standings():
    """Computes tournament points table from completed matches."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM teams")
        teams = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT * FROM matches WHERE status = 'COMPLETED'")
        matches = [dict(r) for r in cursor.fetchall()]

        standings = {}
        for t in teams:
            standings[t["name"]] = {
                "team": t["name"],
                "color": t.get("color", "#1a73e8"),
                "p": 0, "w": 0, "l": 0, "nr": 0, "pts": 0, "nrr": "+0.00"
            }

        for m in matches:
            tA = m["team_a"]
            tB = m["team_b"]
            winner = m["winner"] or ""

            if tA in standings:
                standings[tA]["p"] += 1
            if tB in standings:
                standings[tB]["p"] += 1

            if winner and tA in winner:
                if tA in standings:
                    standings[tA]["w"] += 1
                    standings[tA]["pts"] += 2
                if tB in standings:
                    standings[tB]["l"] += 1
            elif winner and tB in winner:
                if tB in standings:
                    standings[tB]["w"] += 1
                    standings[tB]["pts"] += 2
                if tA in standings:
                    standings[tA]["l"] += 1
            else:
                if tA in standings:
                    standings[tA]["nr"] += 1
                    standings[tA]["pts"] += 1
                if tB in standings:
                    standings[tB]["nr"] += 1
                    standings[tB]["pts"] += 1

        res = list(standings.values())
        res.sort(key=lambda x: (-x["pts"], x["team"]))
        for idx, s in enumerate(res):
            s["pos"] = idx + 1

        return res

# Initialize on module import
init_db()

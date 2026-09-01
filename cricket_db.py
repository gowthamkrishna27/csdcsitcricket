import os
import sqlite3
import datetime
import json

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)
DEFAULT_DB_PATH = os.path.join(DATA_DIR, "cricket.db")

def get_db_path():
    """Returns the active database path, with support for environment overrides."""
    return os.getenv("CRICKET_DB_PATH", DEFAULT_DB_PATH)

DB_PATH = get_db_path()

def get_db():
    """Returns a thread-safe sqlite3 connection with Row factory and foreign keys enabled."""
    conn = sqlite3.connect(get_db_path(), timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    """Initializes the relational schema with tables, foreign keys, and indexes."""
    with get_db() as conn:
        cursor = conn.cursor()

        # 0. LEAGUES (Independent Tournament Divisions)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS leagues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            short_name TEXT,
            description TEXT,
            status TEXT DEFAULT 'active' CHECK(status IN ('active', 'disabled')),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # 1. TEAMS
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS teams (
            id TEXT PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            short_name TEXT,
            captain TEXT,
            color TEXT DEFAULT '#1a73e8',
            league_id INTEGER DEFAULT 1 REFERENCES leagues(id)
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
            league_id INTEGER DEFAULT 1 REFERENCES leagues(id),
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

        # MIGRATION CHECKS
        cursor.execute("PRAGMA table_info(teams)")
        team_cols = [r["name"] for r in cursor.fetchall()]
        if "league_id" not in team_cols:
            cursor.execute("ALTER TABLE teams ADD COLUMN league_id INTEGER DEFAULT 1")

        cursor.execute("PRAGMA table_info(matches)")
        match_cols = [r["name"] for r in cursor.fetchall()]
        if "league_id" not in match_cols:
            cursor.execute("ALTER TABLE matches ADD COLUMN league_id INTEGER DEFAULT 1")
        if "format_name" not in match_cols:
            cursor.execute("ALTER TABLE matches ADD COLUMN format_name TEXT DEFAULT 'T10'")
        if "players_per_team" not in match_cols:
            cursor.execute("ALTER TABLE matches ADD COLUMN players_per_team INTEGER DEFAULT 11")
        if "balls_per_over" not in match_cols:
            cursor.execute("ALTER TABLE matches ADD COLUMN balls_per_over INTEGER DEFAULT 6")
        if "toss_winner" not in match_cols:
            cursor.execute("ALTER TABLE matches ADD COLUMN toss_winner TEXT DEFAULT ''")
        if "toss_decision" not in match_cols:
            cursor.execute("ALTER TABLE matches ADD COLUMN toss_decision TEXT DEFAULT ''")
        if "playing_xi_a" not in match_cols:
            cursor.execute("ALTER TABLE matches ADD COLUMN playing_xi_a TEXT DEFAULT '[]'")
        if "playing_xi_b" not in match_cols:
            cursor.execute("ALTER TABLE matches ADD COLUMN playing_xi_b TEXT DEFAULT '[]'")
        if "captain_a" not in match_cols:
            cursor.execute("ALTER TABLE matches ADD COLUMN captain_a TEXT DEFAULT ''")
        if "captain_b" not in match_cols:
            cursor.execute("ALTER TABLE matches ADD COLUMN captain_b TEXT DEFAULT ''")
        if "wicketkeeper_a" not in match_cols:
            cursor.execute("ALTER TABLE matches ADD COLUMN wicketkeeper_a TEXT DEFAULT ''")
        if "wicketkeeper_b" not in match_cols:
            cursor.execute("ALTER TABLE matches ADD COLUMN wicketkeeper_b TEXT DEFAULT ''")

        cursor.execute("UPDATE teams SET league_id = 1 WHERE league_id IS NULL OR league_id = 0")
        cursor.execute("UPDATE matches SET league_id = 1 WHERE league_id IS NULL OR league_id = 0")
        cursor.execute("UPDATE matches SET format_name = 'T10' WHERE format_name IS NULL")
        cursor.execute("UPDATE matches SET players_per_team = 11 WHERE players_per_team IS NULL OR players_per_team = 0")
        cursor.execute("UPDATE matches SET balls_per_over = 6 WHERE balls_per_over IS NULL OR balls_per_over = 0")

        # Add commentary and fielder_name columns to ball_events if missing
        cursor.execute("PRAGMA table_info(ball_events)")
        ball_cols = [r["name"] for r in cursor.fetchall()]
        if "commentary" not in ball_cols:
            cursor.execute("ALTER TABLE ball_events ADD COLUMN commentary TEXT DEFAULT NULL")
        if "fielder_name" not in ball_cols:
            cursor.execute("ALTER TABLE ball_events ADD COLUMN fielder_name TEXT DEFAULT NULL")

        # 9. LEAGUE STANDINGS (Isolated Tournament Points Tables)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS league_standings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            league_id INTEGER NOT NULL,
            team_name TEXT NOT NULL,
            played INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            ties INTEGER DEFAULT 0,
            no_results INTEGER DEFAULT 0,
            points INTEGER DEFAULT 0,
            runs_scored INTEGER DEFAULT 0,
            overs_faced REAL DEFAULT 0.0,
            runs_conceded INTEGER DEFAULT 0,
            overs_bowled REAL DEFAULT 0.0,
            net_run_rate REAL DEFAULT 0.0,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (league_id) REFERENCES leagues(id) ON DELETE CASCADE,
            UNIQUE(league_id, team_name)
        );
        """)

        # 10. INDEXES
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_innings_match ON innings(match_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_batting_innings ON batting_scores(innings_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_bowling_innings ON bowling_scores(innings_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ball_events_innings ON ball_events(innings_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ball_events_timestamp ON ball_events(timestamp);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_matches_league ON matches(league_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_standings_league ON league_standings(league_id);")

        # Ensure default leagues exist
        cursor.execute("INSERT OR IGNORE INTO leagues (id, name, short_name, description, status) VALUES (1, 'League 1', 'L1', 'Premier Division Cricket League', 'active')")
        cursor.execute("INSERT OR IGNORE INTO leagues (id, name, short_name, description, status) VALUES (2, 'League 2', 'L2', 'Championship Division Cricket League', 'active')")

        # Ensure default admin exists
        cursor.execute("SELECT COUNT(*) AS count FROM admins")
        if cursor.fetchone()["count"] == 0:
            from werkzeug.security import generate_password_hash
            default_email = os.getenv("ADMIN_EMAIL", "gowthamkrishna18v@gmail.com").strip().lower()
            default_pass = os.getenv("ADMIN_PASSWORD", "0724")
            pw_hash = generate_password_hash(default_pass)
            cursor.execute("""
            INSERT INTO admins (id, name, email, password_hash, role, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """, ("A001", "Gowtham Krishna", default_email, pw_hash, "admin", "active"))

        conn.commit()

def seed_default_data():
    """Seeds initial tournament data if database is empty."""
    with get_db() as conn:
        cursor = conn.cursor()

        # 1. Check leagues
        cursor.execute("INSERT OR IGNORE INTO leagues (id, name, short_name, description, status) VALUES (1, 'League 1', 'L1', 'Premier Division Cricket League', 'active')")
        cursor.execute("INSERT OR IGNORE INTO leagues (id, name, short_name, description, status) VALUES (2, 'League 2', 'L2', 'Championship Division Cricket League', 'active')")

        # 2. Check teams (League 1 teams)
        cursor.execute("SELECT COUNT(*) AS count FROM teams WHERE league_id = 1")
        if cursor.fetchone()["count"] == 0:
            teams = [
                ("T1", "House Vayu", "VAY", "Rahul Sharma", "#2980b9", 1),
                ("T2", "House Agni", "AGN", "Rohit Verma", "#e67e22", 1),
                ("T3", "House Akasha", "AKA", "Siddharth Roy", "#8e44ad", 1),
                ("T4", "House Jala", "JAL", "Vikram Patel", "#16a085", 1),
                ("T5", "House Prithvi", "PRI", "Aditya Rao", "#27ae60", 1)
            ]
            cursor.executemany("INSERT OR IGNORE INTO teams (id, name, short_name, captain, color, league_id) VALUES (?, ?, ?, ?, ?, ?)", teams)

        # League 2 teams
        cursor.execute("SELECT COUNT(*) AS count FROM teams WHERE league_id = 2")
        if cursor.fetchone()["count"] == 0:
            l2_teams = [
                ("T6", "Titan Strikers", "TIT", "Kabir Bedi", "#e74c3c", 2),
                ("T7", "Falcon Kings", "FAL", "Suraj Singh", "#f39c12", 2),
                ("T8", "Solar Hawks", "SOL", "Deepak Chahar", "#8e44ad", 2),
                ("T9", "Storm Riders", "STO", "Yash Dayal", "#16a085", 2)
            ]
            cursor.executemany("INSERT OR IGNORE INTO teams (id, name, short_name, captain, color, league_id) VALUES (?, ?, ?, ?, ?, ?)", l2_teams)

        # Check players
        # Check players - ensure full squad roster (at least 11 players per team)
        full_squads = [
            # T1: House Vayu
            ("P01", "T1", "Rahul Sharma", "Batsman", 7),
            ("P02", "T1", "Arjun Varma", "All-Rounder", 18),
            ("P03", "T1", "Kunal Mehra", "Bowler", 24),
            ("P04", "T1", "Devansh Nair", "Wicketkeeper", 11),
            ("P05", "T1", "Tanmay Joshi", "All-Rounder", 33),
            ("P05b1", "T1", "Varun Chakravarthy", "Bowler", 29),
            ("P05b2", "T1", "Rajat Patidar", "Batsman", 31),
            ("P05b3", "T1", "Harshal Patel", "Bowler", 77),
            ("P05b4", "T1", "Shubman Gill", "Batsman", 77),
            ("P05b5", "T1", "Mohammed Shami", "Bowler", 11),
            ("P05b6", "T1", "Ravindra Jadeja", "All-Rounder", 8),

            # T2: House Agni
            ("P06", "T2", "Rohit Verma", "Batsman", 10),
            ("P07", "T2", "Sai Krishna", "Bowler", 23),
            ("P08", "T2", "Manish Pandey", "Batsman", 9),
            ("P09", "T2", "Ravi Bishnoi", "Bowler", 56),
            ("P10", "T2", "Aman Khan", "All-Rounder", 45),
            ("P10b1", "T2", "Rinku Singh", "Batsman", 35),
            ("P10b2", "T2", "Kuldeep Yadav", "Bowler", 23),
            ("P10b3", "T2", "Hardik Pandya", "All-Rounder", 33),
            ("P10b4", "T2", "Ishan Kishan", "Wicketkeeper", 32),
            ("P10b5", "T2", "Jasprit Bumrah", "Bowler", 93),
            ("P10b6", "T2", "Surya Kumar", "Batsman", 63),

            # T3: House Akasha
            ("P11", "T3", "Siddharth Roy", "All-Rounder", 3),
            ("P12", "T3", "Chetan Sakariya", "Bowler", 14),
            ("P13", "T3", "Karan Sharma", "Batsman", 22),
            ("P13b1", "T3", "Sanju Samson", "Wicketkeeper", 11),
            ("P13b2", "T3", "Axar Patel", "All-Rounder", 20),
            ("P13b3", "T3", "Umran Malik", "Bowler", 24),
            ("P13b4", "T3", "Tilak Varma", "Batsman", 9),
            ("P13b5", "T3", "Avesh Khan", "Bowler", 65),
            ("P13b6", "T3", "Ruturaj Gaikwad", "Batsman", 13),
            ("P13b7", "T3", "Deepak Hooda", "All-Rounder", 5),
            ("P13b8", "T3", "Washington Sundar", "All-Rounder", 55),

            # T4: House Jala
            ("P14", "T4", "Vikram Patel", "Batsman", 9),
            ("P15", "T4", "Ankit Raj", "Bowler", 19),
            ("P16", "T4", "Suresh Raina", "All-Rounder", 48),
            ("P16b1", "T4", "Dinesh Karthik", "Wicketkeeper", 21),
            ("P16b2", "T4", "Yuzvendra Chahal", "Bowler", 3),
            ("P16b3", "T4", "Shardul Thakur", "All-Rounder", 54),
            ("P16b4", "T4", "Prithvi Shaw", "Batsman", 100),
            ("P16b5", "T4", "Navdeep Saini", "Bowler", 96),
            ("P16b6", "T4", "Nitish Rana", "Batsman", 27),
            ("P16b7", "T4", "Rahul Tripathi", "Batsman", 52),
            ("P16b8", "T4", "Prasidh Krishna", "Bowler", 43),

            # T5: House Prithvi
            ("P17", "T5", "Aditya Rao", "All-Rounder", 1),
            ("P18", "T5", "Gaurav Sen", "Bowler", 99),
            ("P19", "T5", "Pranav Anand", "Batsman", 17),
            ("P19b1", "T5", "KL Rahul", "Wicketkeeper", 1),
            ("P19b2", "T5", "Shreyas Iyer", "Batsman", 41),
            ("P19b3", "T5", "Bhuvneshwar Kumar", "Bowler", 15),
            ("P19b4", "T5", "Venkatesh Iyer", "All-Rounder", 25),
            ("P19b5", "T5", "Arshdeep Singh", "Bowler", 2),
            ("P19b6", "T5", "Shivam Dube", "All-Rounder", 70),
            ("P19b7", "T5", "Yashasvi Jaiswal", "Batsman", 64),
            ("P19b8", "T5", "Mukesh Kumar", "Bowler", 49),

            # League 2: Titan Strikers
            ("P20", "T6", "Kabir Bedi", "Batsman", 12),
            ("P21", "T6", "Sameer Roy", "Bowler", 8),
            ("P21b1", "T6", "Amit Mishra", "Bowler", 99),
            ("P21b2", "T6", "Mandeep Singh", "Batsman", 37),
            ("P21b3", "T6", "Harpreet Brar", "All-Rounder", 95),
            ("P21b4", "T6", "Jitesh Sharma", "Wicketkeeper", 6),
            ("P21b5", "T6", "Khaleel Ahmed", "Bowler", 71),
            ("P21b6", "T6", "Shahrukh Khan", "All-Rounder", 35),
            ("P21b7", "T6", "Abhishek Sharma", "All-Rounder", 4),
            ("P21b8", "T6", "T Natarajan", "Bowler", 44),
            ("P21b9", "T6", "Mayank Agarwal", "Batsman", 16),

            # League 2: Falcon Kings
            ("P22", "T7", "Suraj Singh", "Batsman", 7),
            ("P23", "T7", "Manoj Das", "Bowler", 15),
            ("P23b1", "T7", "Kagiso Rabada", "Bowler", 25),
            ("P23b2", "T7", "Liam Livingstone", "All-Rounder", 23),
            ("P23b3", "T7", "Sam Curran", "All-Rounder", 58),
            ("P23b4", "T7", "Prabhsimran Singh", "Wicketkeeper", 84),
            ("P23b5", "T7", "Rahul Chahar", "Bowler", 28),
            ("P23b6", "T7", "Atharva Taide", "Batsman", 14),
            ("P23b7", "T7", "Vidwath Kaverappa", "Bowler", 88),
            ("P23b8", "T7", "Ashutosh Sharma", "Batsman", 90),
            ("P23b9", "T7", "Shashank Singh", "All-Rounder", 27),

            # League 2: Solar Hawks
            ("P24", "T8", "Deepak Chahar", "All-Rounder", 27),
            ("P24b1", "T8", "Devdutt Padikkal", "Batsman", 19),
            ("P24b2", "T8", "Riyan Parag", "All-Rounder", 12),
            ("P24b3", "T8", "Dhruv Jurel", "Wicketkeeper", 21),
            ("P24b4", "T8", "Trent Boult", "Bowler", 18),
            ("P24b5", "T8", "Sandeep Sharma", "Bowler", 66),
            ("P24b6", "T8", "Nandre Burger", "Bowler", 77),
            ("P24b7", "T8", "Rovman Powell", "Batsman", 52),
            ("P24b8", "T8", "Shimron Hetmyer", "Batsman", 189),
            ("P24b9", "T8", "Avesh Khan", "Bowler", 65),
            ("P24b10", "T8", "Tanush Kotian", "All-Rounder", 80),

            # League 2: Storm Riders
            ("P25", "T9", "Yash Dayal", "Bowler", 31),
            ("P25b1", "T9", "Faf du Plessis", "Batsman", 13),
            ("P25b2", "T9", "Glenn Maxwell", "All-Rounder", 32),
            ("P25b3", "T9", "Cameron Green", "All-Rounder", 42),
            ("P25b4", "T9", "Mahipal Lomror", "All-Rounder", 7),
            ("P25b5", "T9", "Anuj Rawat", "Wicketkeeper", 55),
            ("P25b6", "T9", "Karn Sharma", "Bowler", 33),
            ("P25b7", "T9", "Lockie Ferguson", "Bowler", 69),
            ("P25b8", "T9", "Alzarri Joseph", "Bowler", 8),
            ("P25b9", "T9", "Suyash Prabhudessai", "Batsman", 16),
            ("P25b10", "T9", "Akash Deep", "Bowler", 41)
        ]
        cursor.executemany("INSERT OR IGNORE INTO players (id, team_id, name, role, jersey_number) VALUES (?, ?, ?, ?, ?)", full_squads)

        # Check bootstrap admin
        cursor.execute("SELECT COUNT(*) AS count FROM admins")
        if cursor.fetchone()["count"] == 0:
            from werkzeug.security import generate_password_hash
            default_email = os.getenv("ADMIN_EMAIL", "gowthamkrishna18v@gmail.com").strip().lower()
            default_pass = os.getenv("ADMIN_PASSWORD", "0724")
            pw_hash = generate_password_hash(default_pass)
            cursor.execute("""
            INSERT INTO admins (id, name, email, password_hash, role, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """, ("A001", "Tournament Admin", default_email, pw_hash, "admin", "active"))

        # Check matches for League 1
        cursor.execute("SELECT COUNT(*) AS count FROM matches WHERE league_id = 1")
        if cursor.fetchone()["count"] == 0:
            # Seed a LIVE match and an UPCOMING match
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
            INSERT INTO matches (match_name, team_a, team_b, venue, match_date, status, current_innings, total_overs, league_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
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
            INSERT INTO matches (match_name, team_a, team_b, venue, match_date, status, current_innings, total_overs, league_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, ("Match 2 - JAL vs PRI", "House Jala", "House Prithvi", "College Main Ground", "Tomorrow", "UPCOMING", 1, 10))

            # COMPLETED match
            cursor.execute("""
            INSERT INTO matches (match_name, team_a, team_b, venue, match_date, status, current_innings, total_overs, winner, result_margin, league_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
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

        # Check matches for League 2
        cursor.execute("SELECT COUNT(*) AS count FROM matches WHERE league_id = 2")
        if cursor.fetchone()["count"] == 0:
            # 1 COMPLETED match in League 2
            cursor.execute("""
            INSERT INTO matches (match_name, team_a, team_b, venue, match_date, status, current_innings, total_overs, winner, result_margin, league_id)
            VALUES (?, ?, ?, ?, ?, 'COMPLETED', 2, ?, ?, ?, 2)
            """, ("Titan Strikers vs Falcon Kings", "Titan Strikers", "Falcon Kings", "Championship Arena", "Yesterday", 10, "Titan Strikers", "by 18 runs"))
            l2_comp_id = cursor.lastrowid
            cursor.execute("""
            INSERT INTO innings (match_id, innings_number, batting_team, bowling_team, runs, wickets, overs, balls)
            VALUES (?, 1, 'Titan Strikers', 'Falcon Kings', 145, 5, 10, 0)
            """, (l2_comp_id,))
            cursor.execute("""
            INSERT INTO innings (match_id, innings_number, batting_team, bowling_team, runs, wickets, overs, balls, target)
            VALUES (?, 2, 'Falcon Kings', 'Titan Strikers', 127, 8, 10, 0, 146)
            """, (l2_comp_id,))

            # 1 UPCOMING match in League 2
            cursor.execute("""
            INSERT INTO matches (match_name, team_a, team_b, venue, match_date, status, current_innings, total_overs, league_id)
            VALUES (?, ?, ?, ?, ?, 'UPCOMING', 1, ?, 2)
            """, ("Solar Hawks vs Storm Riders", "Solar Hawks", "Storm Riders", "Championship Arena", "Tomorrow", 10))

        conn.commit()

# ==============================================================================
# LEAGUE MANAGEMENT & ISOLATED QUERIES
# ==============================================================================

def get_all_leagues():
    """Returns all leagues with real-time match and team counts."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM leagues ORDER BY id ASC")
        leagues = [dict(r) for r in cursor.fetchall()]
        for l in leagues:
            cursor.execute("SELECT COUNT(*) as cnt FROM matches WHERE league_id = ?", (l["id"],))
            l["matches_count"] = cursor.fetchone()["cnt"]
            cursor.execute("""
            SELECT COUNT(DISTINCT team) as cnt FROM (
                SELECT team_a AS team FROM matches WHERE league_id = ?
                UNION
                SELECT team_b AS team FROM matches WHERE league_id = ?
                UNION
                SELECT name AS team FROM teams WHERE league_id = ?
            )
            """, (l["id"], l["id"], l["id"]))
            l["teams_count"] = cursor.fetchone()["cnt"]
        return leagues

def get_league_by_id(league_id):
    """Returns a single league by ID with its summary stats."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM leagues WHERE id = ?", (league_id,))
        row = cursor.fetchone()
        if not row:
            return None
        l = dict(row)
        cursor.execute("SELECT COUNT(*) as cnt FROM matches WHERE league_id = ?", (l["id"],))
        l["matches_count"] = cursor.fetchone()["cnt"]
        cursor.execute("""
        SELECT COUNT(DISTINCT team) as cnt FROM (
            SELECT team_a AS team FROM matches WHERE league_id = ?
            UNION
            SELECT team_b AS team FROM matches WHERE league_id = ?
            UNION
            SELECT name AS team FROM teams WHERE league_id = ?
        )
        """, (l["id"], l["id"], l["id"]))
        l["teams_count"] = cursor.fetchone()["cnt"]
        return l

def create_league(name, short_name=None, description="", status="active"):
    """Creates a new isolated tournament league."""
    if not name or not name.strip():
        return False, "League name is required"
    name = name.strip()
    short_name = (short_name or name[:3]).strip().upper()
    status = status if status in ("active", "disabled") else "active"

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM leagues WHERE name = ?", (name,))
        if cursor.fetchone():
            return False, f"League '{name}' already exists"
        cursor.execute("""
        INSERT INTO leagues (name, short_name, description, status)
        VALUES (?, ?, ?, ?)
        """, (name, short_name, description, status))
        league_id = cursor.lastrowid
        conn.commit()

    recalculate_standings(league_id)
    return True, get_league_by_id(league_id)

def update_league(league_id, name=None, short_name=None, description=None, status=None):
    """Updates league metadata or active/disabled status."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM leagues WHERE id = ?", (league_id,))
        existing = cursor.fetchone()
        if not existing:
            return False, "League not found"

        updates = []
        params = []
        if name is not None:
            updates.append("name = ?")
            params.append(name.strip())
        if short_name is not None:
            updates.append("short_name = ?")
            params.append(short_name.strip().upper())
        if description is not None:
            updates.append("description = ?")
            params.append(description.strip())
        if status is not None and status in ("active", "disabled"):
            updates.append("status = ?")
            params.append(status)

        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(league_id)
            cursor.execute(f"UPDATE leagues SET {', '.join(updates)} WHERE id = ?", params)
            conn.commit()

    return True, get_league_by_id(league_id)

def delete_league(league_id):
    """Safely deletes a league and cascades its matches and standings."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as cnt FROM leagues")
        if cursor.fetchone()["cnt"] <= 1:
            return False, "Cannot delete the only remaining league"

        cursor.execute("SELECT id FROM leagues WHERE id = ?", (league_id,))
        if not cursor.fetchone():
            return False, "League not found"

        cursor.execute("DELETE FROM matches WHERE league_id = ?", (league_id,))
        cursor.execute("DELETE FROM league_standings WHERE league_id = ?", (league_id,))
        cursor.execute("DELETE FROM leagues WHERE id = ?", (league_id,))
        conn.commit()

    return True, f"League {league_id} deleted successfully"

def get_league_overview(league_id):
    """Returns overview dashboard counters and featured matches for League View."""
    league = get_league_by_id(league_id)
    if not league:
        return None

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM matches WHERE league_id = ? ORDER BY id DESC", (league_id,))
        raw_matches = [dict(r) for r in cursor.fetchall()]

        completed = [m for m in raw_matches if m["status"] == "COMPLETED"]
        live = [m for m in raw_matches if m["status"] == "LIVE"]
        upcoming = [m for m in raw_matches if m["status"] == "UPCOMING"]

        cursor.execute("""
        SELECT DISTINCT team FROM (
            SELECT team_a AS team FROM matches WHERE league_id = ?
            UNION
            SELECT team_b AS team FROM matches WHERE league_id = ?
            UNION
            SELECT name AS team FROM teams WHERE league_id = ?
        )
        """, (league_id, league_id, league_id))
        teams = [r["team"] for r in cursor.fetchall()]

        live_details = None
        if live:
            live_details = get_live_match_details(live[0]["id"])

        recent_completed = None
        if completed:
            recent_completed = get_match_by_id(completed[0]["id"])

        next_upcoming = None
        if upcoming:
            next_upcoming = get_match_by_id(upcoming[0]["id"])

        standings = recalculate_standings(league_id)

        return {
            "league": league,
            "total_teams": len(teams),
            "total_matches": len(raw_matches),
            "completed_matches": len(completed),
            "live_matches": len(live),
            "upcoming_matches": len(upcoming),
            "live_match": live_details,
            "recent_completed": recent_completed,
            "next_upcoming": next_upcoming,
            "top_standings": standings[:4] if standings else []
        }

def get_league_matches(league_id, status=None):
    """Returns matches strictly isolated to a specific league."""
    return get_all_matches(league_id=league_id, status=status)

def get_league_team_details(league_id, team_name):
    """Returns team profile, current points table row, and isolated match history within the league."""
    standings = recalculate_standings(league_id)
    team_stat = next((s for s in standings if s["team"].lower() == team_name.lower()), None)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM teams WHERE name = ? AND league_id = ?", (team_name, league_id))
        team_row = cursor.fetchone()
        if not team_row:
            cursor.execute("SELECT * FROM teams WHERE name = ?", (team_name,))
            team_row = cursor.fetchone()

        team_info = dict(team_row) if team_row else {
            "name": team_name,
            "short_name": team_name[:3].upper(),
            "captain": "N/A",
            "color": "#1a73e8"
        }

        cursor.execute("""
        SELECT * FROM matches 
        WHERE league_id = ? AND (team_a = ? OR team_b = ?)
        ORDER BY id DESC
        """, (league_id, team_name, team_name))
        raw_matches = [dict(r) for r in cursor.fetchall()]
        for m in raw_matches:
            m["teamA"] = m["team_a"]
            m["teamB"] = m["team_b"]
            m["matchNo"] = f"{m['id']:02d}" if isinstance(m["id"], int) else str(m["id"])
            m["innings"] = get_match_innings(m["id"])
            inn1 = next((i for i in m["innings"] if i["innings_number"] == 1), None)
            inn2 = next((i for i in m["innings"] if i["innings_number"] == 2), None)
            m["scoreA"] = f"{inn1['runs']}/{inn1['wickets']}" if inn1 else ""
            m["scoreB"] = f"{inn2['runs']}/{inn2['wickets']}" if inn2 else ""

        return {
            "team": team_info,
            "standing": team_stat,
            "matches": raw_matches
        }

def get_player_profile(player_name_or_id):
    """Calculates comprehensive career statistics for a player from actual match records."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # 1. Batting career stats
        cursor.execute("""
        SELECT 
            b.player_name,
            COUNT(b.id) as innings,
            SUM(b.runs) as total_runs,
            SUM(b.balls) as total_balls,
            SUM(b.fours) as total_fours,
            SUM(b.sixes) as total_sixes,
            MAX(b.runs) as highest_score,
            SUM(CASE WHEN b.is_out = 1 THEN 1 ELSE 0 END) as times_out,
            SUM(CASE WHEN b.runs >= 50 AND b.runs < 100 THEN 1 ELSE 0 END) as fifties,
            SUM(CASE WHEN b.runs >= 100 THEN 1 ELSE 0 END) as hundreds
        FROM batting_scores b
        WHERE LOWER(b.player_name) = LOWER(?) OR b.player_id = ?
        GROUP BY b.player_name
        """, (str(player_name_or_id), str(player_name_or_id)))
        bat_row = cursor.fetchone()
        
        # 2. Bowling career stats
        cursor.execute("""
        SELECT 
            bw.player_name,
            COUNT(bw.id) as bowling_innings,
            SUM(bw.legal_balls) as total_legal_balls,
            SUM(bw.maidens) as total_maidens,
            SUM(bw.runs) as total_runs_conceded,
            SUM(bw.wickets) as total_wickets
        FROM bowling_scores bw
        WHERE LOWER(bw.player_name) = LOWER(?) OR bw.player_id = ?
        GROUP BY bw.player_name
        """, (str(player_name_or_id), str(player_name_or_id)))
        bowl_row = cursor.fetchone()

        # 3. Find Best Bowling Figures in a single match
        cursor.execute("""
        SELECT wickets, runs, overs
        FROM bowling_scores
        WHERE (LOWER(player_name) = LOWER(?) OR player_id = ?) AND legal_balls > 0
        ORDER BY wickets DESC, runs ASC
        LIMIT 1
        """, (str(player_name_or_id), str(player_name_or_id)))
        best_bowl_row = cursor.fetchone()

        p_name = bat_row["player_name"] if bat_row else (bowl_row["player_name"] if bowl_row else str(player_name_or_id))
        
        # Calculate Batting stats
        inn_cnt = bat_row["innings"] if bat_row else 0
        t_runs = bat_row["total_runs"] if bat_row else 0
        t_balls = bat_row["total_balls"] if bat_row else 0
        t_fours = bat_row["total_fours"] if bat_row else 0
        t_sixes = bat_row["total_sixes"] if bat_row else 0
        hs = bat_row["highest_score"] if bat_row else 0
        t_out = bat_row["times_out"] if bat_row else 0
        bat_avg = round(t_runs / t_out, 2) if t_out > 0 else (float(t_runs) if t_runs > 0 else 0.0)
        bat_sr = round((t_runs / t_balls * 100.0), 2) if t_balls > 0 else 0.0

        # Calculate Bowling stats
        bw_inns = bowl_row["bowling_innings"] if bowl_row else 0
        bw_balls = bowl_row["total_legal_balls"] if bowl_row else 0
        bw_overs = round(bw_balls // 6 + (bw_balls % 6) / 10.0, 1)
        bw_maidens = bowl_row["total_maidens"] if bowl_row else 0
        bw_runs = bowl_row["total_runs_conceded"] if bowl_row else 0
        bw_wkts = bowl_row["total_wickets"] if bowl_row else 0
        bw_eco = round(bw_runs / (bw_balls / 6.0), 2) if bw_balls > 0 else 0.0
        bw_avg = round(bw_runs / bw_wkts, 2) if bw_wkts > 0 else 0.0
        best_bb = f"{best_bowl_row['wickets']}/{best_bowl_row['runs']}" if best_bowl_row else "—"

        # Check team info
        cursor.execute("""
        SELECT t.name as team_name, p.role 
        FROM players p LEFT JOIN teams t ON p.team_id = t.id 
        WHERE LOWER(p.name) = LOWER(?) LIMIT 1
        """, (p_name,))
        p_info = cursor.fetchone()
        team_name = p_info["team_name"] if p_info else "Tournament Squad"
        role = p_info["role"] if p_info else "All-Rounder"

        return {
            "name": p_name,
            "team": team_name,
            "role": role,
            "batting": {
                "innings": inn_cnt,
                "runs": t_runs,
                "balls": t_balls,
                "average": bat_avg,
                "strike_rate": bat_sr,
                "highest_score": hs,
                "fours": t_fours,
                "sixes": t_sixes,
                "fifties": bat_row["fifties"] if bat_row else 0,
                "hundreds": bat_row["hundreds"] if bat_row else 0
            },
            "bowling": {
                "innings": bw_inns,
                "overs": bw_overs,
                "legal_balls": bw_balls,
                "maidens": bw_maidens,
                "runs": bw_runs,
                "wickets": bw_wkts,
                "economy": bw_eco,
                "average": bw_avg,
                "best_bowling": best_bb
            }
        }

def get_tournament_leaderboards(league_id=None):
    """Calculates top performers across matches (Most Runs, Most Wickets, Best SR, Best Economy, Highest Score)."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        league_filter_bat = ""
        league_filter_bowl = ""
        params = []
        if league_id:
            league_filter_bat = "JOIN innings i ON b.innings_id = i.id JOIN matches m ON i.match_id = m.id WHERE m.league_id = ?"
            league_filter_bowl = "JOIN innings i ON bw.innings_id = i.id JOIN matches m ON i.match_id = m.id WHERE m.league_id = ?"
            params = [int(league_id)]

        # 1. Most Runs
        cursor.execute(f"""
        SELECT b.player_name, SUM(b.runs) as total_runs, SUM(b.balls) as total_balls,
               SUM(b.fours) as fours, SUM(b.sixes) as sixes, MAX(b.runs) as hs
        FROM batting_scores b {league_filter_bat}
        GROUP BY b.player_name
        ORDER BY total_runs DESC, total_balls ASC
        LIMIT 10
        """, params)
        most_runs = [dict(r) for r in cursor.fetchall()]
        for r in most_runs:
            r["sr"] = round((r["total_runs"] / r["total_balls"] * 100.0), 2) if r["total_balls"] > 0 else 0.0

        # 2. Most Wickets
        cursor.execute(f"""
        SELECT bw.player_name, SUM(bw.wickets) as total_wickets, SUM(bw.runs) as total_runs,
               SUM(bw.legal_balls) as total_balls
        FROM bowling_scores bw {league_filter_bowl}
        GROUP BY bw.player_name
        ORDER BY total_wickets DESC, total_runs ASC
        LIMIT 10
        """, params)
        most_wickets = [dict(r) for r in cursor.fetchall()]
        for r in most_wickets:
            r["overs"] = round(r["total_balls"] // 6 + (r["total_balls"] % 6) / 10.0, 1)
            r["economy"] = round(r["total_runs"] / (r["total_balls"] / 6.0), 2) if r["total_balls"] > 0 else 0.0

        # 3. Best Strike Rate (min 6 balls)
        cursor.execute(f"""
        SELECT b.player_name, SUM(b.runs) as total_runs, SUM(b.balls) as total_balls
        FROM batting_scores b {league_filter_bat}
        GROUP BY b.player_name
        HAVING total_balls >= 6
        ORDER BY (CAST(SUM(b.runs) AS REAL) / SUM(b.balls)) DESC
        LIMIT 10
        """, params)
        best_sr = [dict(r) for r in cursor.fetchall()]
        for r in best_sr:
            r["sr"] = round((r["total_runs"] / r["total_balls"] * 100.0), 2) if r["total_balls"] > 0 else 0.0

        # 4. Best Economy (min 6 balls)
        cursor.execute(f"""
        SELECT bw.player_name, SUM(bw.wickets) as total_wickets, SUM(bw.runs) as total_runs,
               SUM(bw.legal_balls) as total_balls
        FROM bowling_scores bw {league_filter_bowl}
        GROUP BY bw.player_name
        HAVING total_balls >= 6
        ORDER BY (CAST(SUM(bw.runs) AS REAL) / (SUM(bw.legal_balls) / 6.0)) ASC
        LIMIT 10
        """, params)
        best_eco = [dict(r) for r in cursor.fetchall()]
        for r in best_eco:
            r["overs"] = round(r["total_balls"] // 6 + (r["total_balls"] % 6) / 10.0, 1)
            r["economy"] = round(r["total_runs"] / (r["total_balls"] / 6.0), 2) if r["total_balls"] > 0 else 0.0

        # 5. Highest Scores (Single innings)
        cursor.execute(f"""
        SELECT b.player_name, b.runs, b.balls, b.fours, b.sixes, b.strike_rate
        FROM batting_scores b {league_filter_bat}
        ORDER BY b.runs DESC, b.strike_rate DESC
        LIMIT 10
        """, params)
        highest_scores = [dict(r) for r in cursor.fetchall()]

        return {
            "league_id": league_id,
            "most_runs": most_runs,
            "most_wickets": most_wickets,
            "best_strike_rate": best_sr,
            "best_economy": best_eco,
            "highest_scores": highest_scores
        }

# ==============================================================================
# MATCH REPOSITORIES & QUERIES
# ==============================================================================

def _format_match_dict(m):
    if not m:
        return None
    m = dict(m)
    m["league_id"] = m.get("league_id") or 1
    m["teamA"] = m.get("team_a")
    m["teamB"] = m.get("team_b")
    m["matchNo"] = f"{m['id']:02d}" if isinstance(m.get("id"), int) else str(m.get("id"))
    m["date"] = m.get("match_date")
    m["time"] = "02:00 PM"
    
    total_overs = m.get("total_overs") or 10
    m["total_overs"] = total_overs
    m["overs"] = total_overs
    m["format_name"] = m.get("format_name") or ("T6" if total_overs == 6 else ("T10" if total_overs == 10 else f"T{total_overs}"))
    m["players_per_team"] = m.get("players_per_team") or (8 if total_overs == 6 else 11)
    m["balls_per_over"] = m.get("balls_per_over") or 6

    try:
        m["playing_xi_a"] = json.loads(m["playing_xi_a"]) if isinstance(m.get("playing_xi_a"), str) and m["playing_xi_a"].strip() else []
    except Exception:
        m["playing_xi_a"] = []

    try:
        m["playing_xi_b"] = json.loads(m["playing_xi_b"]) if isinstance(m.get("playing_xi_b"), str) and m["playing_xi_b"].strip() else []
    except Exception:
        m["playing_xi_b"] = []

    m["captain_a"] = m.get("captain_a") or ""
    m["captain_b"] = m.get("captain_b") or ""
    m["wicketkeeper_a"] = m.get("wicketkeeper_a") or ""
    m["wicketkeeper_b"] = m.get("wicketkeeper_b") or ""
    m["toss_winner"] = m.get("toss_winner") or ""
    m["toss_decision"] = m.get("toss_decision") or ""

    m["innings"] = get_match_innings(m["id"])
    
    inn1 = next((i for i in m["innings"] if i["innings_number"] == 1), None)
    inn2 = next((i for i in m["innings"] if i["innings_number"] == 2), None)
    m["scoreA"] = f"{inn1['runs']}/{inn1['wickets']}" if inn1 else ""
    m["oversA"] = f"{inn1['overs']}.{inn1['balls']}" if inn1 else ""
    m["scoreB"] = f"{inn2['runs']}/{inn2['wickets']}" if inn2 else ("Yet to Bat" if m["status"] == "LIVE" else "")
    m["oversB"] = f"{inn2['overs']}.{inn2['balls']}" if inn2 else ""

    if m["status"] == "LIVE" and inn1:
        m["liveScorecard"] = {
            "runs": inn1["runs"],
            "wickets": inn1["wickets"],
            "oversCompleted": inn1["overs"],
            "ballsInOver": inn1["balls"]
        }
    return m

def get_all_matches(league_id=None, status=None, date=None, team=None):
    """Returns all matches, optionally filtered by league_id, status, date, and/or team."""
    with get_db() as conn:
        cursor = conn.cursor()
        clauses = []
        params = []
        if league_id is not None:
            clauses.append("m.league_id = ?")
            params.append(int(league_id))
        if status is not None:
            clauses.append("m.status = ?")
            params.append(status.upper())
        if date is not None and str(date).strip():
            clauses.append("LOWER(m.match_date) LIKE ?")
            params.append(f"%{str(date).strip().lower()}%")
        if team is not None and str(team).strip():
            clauses.append("(LOWER(m.team_a) LIKE ? OR LOWER(m.team_b) LIKE ?)")
            t_clean = f"%{str(team).strip().lower()}%"
            params.extend([t_clean, t_clean])

        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
        SELECT m.*, l.name as league_name, l.short_name as league_short_name 
        FROM matches m 
        LEFT JOIN leagues l ON m.league_id = l.id 
        {where_clause}
        ORDER BY m.id DESC
        """
        cursor.execute(query, params)
        raw_matches = [dict(row) for row in cursor.fetchall()]
        return [_format_match_dict(m) for m in raw_matches]

def get_match_by_id(match_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT m.*, l.name as league_name, l.short_name as league_short_name 
        FROM matches m 
        LEFT JOIN leagues l ON m.league_id = l.id 
        WHERE m.id = ?
        """, (match_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return _format_match_dict(dict(row))

def get_match_innings(match_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM innings WHERE match_id = ? ORDER BY innings_number ASC", (match_id,))
        return [dict(row) for row in cursor.fetchall()]

def create_match(team_a, team_b, venue="College Ground", match_date="Today", total_overs=10, match_name=None, league_id=1, format_name="T10", players_per_team=None, balls_per_over=6):
    if not team_a or not team_b:
        return False, "Team A and Team B are required"
    if str(team_a).strip().lower() == str(team_b).strip().lower():
        return False, "Team A and Team B cannot be the same"
    
    try:
        total_overs = int(total_overs)
    except (ValueError, TypeError):
        return False, "Total overs must be a valid integer"

    if total_overs <= 0:
        return False, "Total overs must be greater than 0"

    league_id = int(league_id) if league_id else 1
    team_a = str(team_a).strip()
    team_b = str(team_b).strip()
    venue = (venue or "College Ground").strip()
    match_date = (match_date or "Today").strip()
    
    fmt = (format_name or ("T6" if total_overs == 6 else ("T10" if total_overs == 10 else f"T{total_overs}"))).strip()
    
    if players_per_team is None:
        ppt = 8 if (total_overs == 6 or fmt.upper() == "T6") else 11
    else:
        try:
            ppt = int(players_per_team)
            if ppt <= 0:
                return False, "Players per team must be greater than 0"
        except (ValueError, TypeError):
            ppt = 11

    try:
        bpo = int(balls_per_over) if balls_per_over else 6
        if bpo <= 0:
            bpo = 6
    except (ValueError, TypeError):
        bpo = 6

    if not match_name:
        match_name = f"{team_a} vs {team_b}"

    with get_db() as conn:
        cursor = conn.cursor()
        # Check duplicate upcoming fixture with same teams, date, and venue in this league
        cursor.execute("""
        SELECT id FROM matches 
        WHERE league_id = ? AND team_a = ? AND team_b = ? AND match_date = ? AND venue = ? AND status = 'UPCOMING'
        """, (league_id, team_a, team_b, match_date, venue))
        if cursor.fetchone():
            return False, f"A fixture between {team_a} and {team_b} at {venue} on {match_date} already exists in this league"

        cursor.execute("""
        INSERT INTO matches (match_name, team_a, team_b, venue, match_date, status, current_innings, total_overs, league_id, format_name, players_per_team, balls_per_over)
        VALUES (?, ?, ?, ?, ?, 'UPCOMING', 1, ?, ?, ?, ?, ?)
        """, (match_name, team_a, team_b, venue, match_date, total_overs, league_id, fmt, ppt, bpo))
        match_id = cursor.lastrowid
        conn.commit()

    recalculate_standings(league_id)
    return True, get_match_by_id(match_id)

def update_match(match_id, team_a=None, team_b=None, venue=None, match_date=None, total_overs=None, status=None, league_id=None, format_name=None, players_per_team=None, balls_per_over=None):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
        existing = cursor.fetchone()
        if not existing:
            return False, "Match not found"

        old_league_id = existing["league_id"] or 1
        
        # Check if match has recorded deliveries
        cursor.execute("SELECT COUNT(*) as count FROM ball_events b JOIN innings i ON b.innings_id = i.id WHERE i.match_id = ?", (match_id,))
        has_balls = cursor.fetchone()["count"] > 0

        updates = []
        params = []
        if team_a:
            team_a_clean = str(team_a).strip()
            if has_balls and team_a_clean != existing["team_a"]:
                return False, "Cannot change team names after deliveries have been recorded"
            updates.append("team_a = ?")
            params.append(team_a_clean)
        if team_b:
            team_b_clean = str(team_b).strip()
            if has_balls and team_b_clean != existing["team_b"]:
                return False, "Cannot change team names after deliveries have been recorded"
            updates.append("team_b = ?")
            params.append(team_b_clean)
        if venue:
            updates.append("venue = ?")
            params.append(str(venue).strip())
        if match_date:
            updates.append("match_date = ?")
            params.append(str(match_date).strip())
        if total_overs:
            ov = int(total_overs)
            if ov <= 0:
                return False, "Total overs must be greater than 0"
            updates.append("total_overs = ?")
            params.append(ov)
        if format_name:
            updates.append("format_name = ?")
            params.append(str(format_name).strip())
        if players_per_team:
            ppt = int(players_per_team)
            if ppt <= 0:
                return False, "Players per team must be greater than 0"
            updates.append("players_per_team = ?")
            params.append(ppt)
        if balls_per_over:
            bpo = int(balls_per_over)
            if bpo <= 0:
                bpo = 6
            updates.append("balls_per_over = ?")
            params.append(bpo)
        if status:
            st = str(status).strip().upper()
            updates.append("status = ?")
            params.append(st)
        if league_id is not None:
            updates.append("league_id = ?")
            params.append(int(league_id))

        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(match_id)
            cursor.execute(f"UPDATE matches SET {', '.join(updates)} WHERE id = ?", params)
            conn.commit()

    new_league_id = int(league_id) if league_id is not None else old_league_id
    recalculate_standings(old_league_id)
    if new_league_id != old_league_id:
        recalculate_standings(new_league_id)
    return True, get_match_by_id(match_id)

def save_match_setup(match_id, playing_xi_a, playing_xi_b, captain_a, captain_b, wicketkeeper_a=None, wicketkeeper_b=None, toss_winner=None, toss_decision=None):
    """Validates and saves Playing XI, Captain, Wicketkeeper, and Toss for a match."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
        m = cursor.fetchone()
        if not m:
            return False, "Match not found"

        total_overs = m["total_overs"] or 10
        req_players = m["players_per_team"] or (8 if total_overs == 6 else 11)

        # Validate Team A XI
        if not isinstance(playing_xi_a, list) or len(playing_xi_a) != req_players:
            return False, f"{m['team_a']} requires exactly {req_players} players in Playing XI (got {len(playing_xi_a) if isinstance(playing_xi_a, list) else 0})"

        # Validate Team B XI
        if not isinstance(playing_xi_b, list) or len(playing_xi_b) != req_players:
            return False, f"{m['team_b']} requires exactly {req_players} players in Playing XI (got {len(playing_xi_b) if isinstance(playing_xi_b, list) else 0})"

        # Validate Captains
        if not captain_a or captain_a not in playing_xi_a:
            return False, f"Captain for {m['team_a']} must be selected from the Playing XI"
        if not captain_b or captain_b not in playing_xi_b:
            return False, f"Captain for {m['team_b']} must be selected from the Playing XI"

        # Validate Wicketkeepers if provided
        if wicketkeeper_a and wicketkeeper_a not in playing_xi_a:
            return False, f"Wicketkeeper for {m['team_a']} must be selected from the Playing XI"
        if wicketkeeper_b and wicketkeeper_b not in playing_xi_b:
            return False, f"Wicketkeeper for {m['team_b']} must be selected from the Playing XI"

        # Validate Toss if provided
        if toss_winner and toss_winner not in (m["team_a"], m["team_b"]):
            return False, f"Toss winner must be {m['team_a']} or {m['team_b']}"
        if toss_decision and str(toss_decision).upper() not in ("BAT", "BOWL"):
            return False, "Toss decision must be BAT or BOWL"

        cursor.execute("""
        UPDATE matches
        SET playing_xi_a = ?, playing_xi_b = ?, captain_a = ?, captain_b = ?,
            wicketkeeper_a = ?, wicketkeeper_b = ?, toss_winner = ?, toss_decision = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """, (
            json.dumps(playing_xi_a),
            json.dumps(playing_xi_b),
            str(captain_a),
            str(captain_b),
            str(wicketkeeper_a or ""),
            str(wicketkeeper_b or ""),
            str(toss_winner or ""),
            str(toss_decision or "").upper(),
            match_id
        ))
        conn.commit()

    return True, get_match_by_id(match_id)

def get_match_players_for_scoring(match_id, innings_id=None):
    """Returns available batters, bowlers, and fielders restricted strictly to the match Playing XI."""
    m = get_match_by_id(match_id)
    if not m:
        return {"batters": [], "bowlers": [], "fielders": []}
    
    inns = m.get("innings") or []
    inn = next((i for i in inns if i["id"] == innings_id), None) if innings_id else (inns[-1] if inns else None)

    batting_team = inn["batting_team"] if inn else m["team_a"]
    bowling_team = inn["bowling_team"] if inn else m["team_b"]

    bat_xi = m["playing_xi_a"] if batting_team == m["team_a"] else m["playing_xi_b"]
    bowl_xi = m["playing_xi_b"] if batting_team == m["team_a"] else m["playing_xi_a"]

    if not bat_xi:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM players WHERE team_id = (SELECT id FROM teams WHERE name = ?)", (batting_team,))
            bat_xi = [r["name"] for r in cursor.fetchall()]
    if not bowl_xi:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM players WHERE team_id = (SELECT id FROM teams WHERE name = ?)", (bowling_team,))
            bowl_xi = [r["name"] for r in cursor.fetchall()]

    dismissed = set()
    currently_batting = set()
    if inn:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT player_name, is_out FROM batting_scores WHERE innings_id = ?", (inn["id"],))
            for r in cursor.fetchall():
                if r["is_out"] == 1:
                    dismissed.add(r["player_name"])
                else:
                    currently_batting.add(r["player_name"])

    available_batters = [p for p in bat_xi if p not in dismissed and p not in currently_batting]

    return {
        "batting_team": batting_team,
        "bowling_team": bowling_team,
        "batting_xi": bat_xi,
        "bowling_xi": bowl_xi,
        "available_batters": available_batters,
        "bowlers": bowl_xi,
        "fielders": bowl_xi
    }

def abandon_match(match_id, reason="Match Abandoned"):
    """Marks a match as Abandoned / No Result."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
        m = cursor.fetchone()
        if not m:
            return False, "Match not found"
        
        cursor.execute("""
        UPDATE matches 
        SET status = 'COMPLETED', winner = 'No Result', result_margin = ?, updated_at = CURRENT_TIMESTAMP 
        WHERE id = ?
        """, (reason or "Match Abandoned", match_id))
        conn.commit()

    recalculate_standings(m["league_id"] or 1)
    return True, get_match_by_id(match_id)

def delete_match(match_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT league_id FROM matches WHERE id = ?", (match_id,))
        row = cursor.fetchone()
        if not row:
            return False, "Match not found"
        lid = row["league_id"] or 1
        cursor.execute("DELETE FROM matches WHERE id = ?", (match_id,))
        conn.commit()

    recalculate_standings(lid)
    return True, f"Match {match_id} deleted successfully"

def start_match(match_id):
    """Starts a match, setting it to LIVE, completing any other live match, and initializing 1st innings using Toss and Playing XI."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
        target = cursor.fetchone()
        if not target:
            return False, f"Match {match_id} not found"

        total_overs = target["total_overs"] or 10
        req_players = target["players_per_team"] or (8 if total_overs == 6 else 11)

        # Parse Playing XIs
        try:
            xi_a = json.loads(target["playing_xi_a"]) if target["playing_xi_a"] else []
        except Exception:
            xi_a = []
        try:
            xi_b = json.loads(target["playing_xi_b"]) if target["playing_xi_b"] else []
        except Exception:
            xi_b = []

        # If not populated, auto-populate from squad players for convenience/backward-compat
        if len(xi_a) != req_players:
            cursor.execute("SELECT name FROM players WHERE team_id = (SELECT id FROM teams WHERE name = ?) LIMIT ?", (target["team_a"], req_players))
            rows = cursor.fetchall()
            xi_a = [r["name"] for r in rows]
            cursor.execute("UPDATE matches SET playing_xi_a = ? WHERE id = ?", (json.dumps(xi_a), match_id))

        if len(xi_b) != req_players:
            cursor.execute("SELECT name FROM players WHERE team_id = (SELECT id FROM teams WHERE name = ?) LIMIT ?", (target["team_b"], req_players))
            rows = cursor.fetchall()
            xi_b = [r["name"] for r in rows]
            cursor.execute("UPDATE matches SET playing_xi_b = ? WHERE id = ?", (json.dumps(xi_b), match_id))

        # Complete any other match currently marked LIVE
        cursor.execute("UPDATE matches SET status = 'COMPLETED' WHERE status = 'LIVE' AND id != ?", (match_id,))
        cursor.execute("UPDATE matches SET status = 'LIVE', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (match_id,))

        # Determine 1st innings batting and bowling teams based on toss
        toss_w = target["toss_winner"]
        toss_d = (target["toss_decision"] or "").upper()
        if toss_w == target["team_a"]:
            batting_team = target["team_a"] if toss_d != "BOWL" else target["team_b"]
            bowling_team = target["team_b"] if toss_d != "BOWL" else target["team_a"]
        elif toss_w == target["team_b"]:
            batting_team = target["team_b"] if toss_d != "BOWL" else target["team_a"]
            bowling_team = target["team_a"] if toss_d != "BOWL" else target["team_b"]
        else:
            batting_team = target["team_a"]
            bowling_team = target["team_b"]

        # Check if innings exists
        cursor.execute("SELECT * FROM innings WHERE match_id = ? AND innings_number = 1", (match_id,))
        inn = cursor.fetchone()
        if not inn:
            cursor.execute("""
            INSERT INTO innings (match_id, innings_number, batting_team, bowling_team, runs, wickets, overs, balls)
            VALUES (?, 1, ?, ?, 0, 0, 0, 0)
            """, (match_id, batting_team, bowling_team))
            inn_id = cursor.lastrowid
            
            # Select top 2 from batting team XI
            bat_xi = xi_a if batting_team == target["team_a"] else xi_b
            bowl_xi = xi_b if batting_team == target["team_a"] else xi_a

            b1_name = bat_xi[0] if len(bat_xi) > 0 else "Striker 1"
            b2_name = bat_xi[1] if len(bat_xi) > 1 else "Striker 2"
            bw_name = bowl_xi[0] if len(bowl_xi) > 0 else "Bowler"

            cursor.execute("INSERT INTO batting_scores (innings_id, player_name, is_on_strike, batting_order) VALUES (?, ?, 1, 1)", (inn_id, b1_name))
            cursor.execute("INSERT INTO batting_scores (innings_id, player_name, is_on_strike, batting_order) VALUES (?, ?, 0, 2)", (inn_id, b2_name))
            cursor.execute("INSERT INTO bowling_scores (innings_id, player_name, is_current_bowler) VALUES (?, ?, 1)", (inn_id, bw_name))

        conn.commit()

    recalculate_standings(target["league_id"] or 1)
    return True, get_live_match_details(match_id=match_id) or get_match_by_id(match_id)

def get_players_by_team(team_name):
    """Returns list of players belonging to a team (by name)."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT p.*, t.name as team_name
        FROM players p
        JOIN teams t ON p.team_id = t.id
        WHERE LOWER(t.name) = LOWER(?)
        ORDER BY p.id ASC
        """, (str(team_name).strip(),))
        return [dict(r) for r in cursor.fetchall()]

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

    lid = m["league_id"] or 1
    recalculate_standings(lid)
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
    players_per_team = match_info["players_per_team"] if (match_info and match_info["players_per_team"]) else (8 if total_overs == 6 else 11)
    balls_per_over = match_info["balls_per_over"] if (match_info and match_info["balls_per_over"]) else 6
    max_wickets = max(1, players_per_team - 1)

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
        current_over_idx = legal_balls_count // balls_per_over

        # Calculate runs
        ball_total_runs = runs + ev["extras"]
        total_runs += ball_total_runs

        # Bowler runs conceded (byes and leg byes don't count against bowler)
        bowler_conceded = 0
        if extra in ("WIDE", "NO BALL"):
            bowler_conceded = runs + ev["extras"]
        elif extra in ("BYE", "LEG BYE"):
            bowler_conceded = 0
        else:
            bowler_conceded = runs
        bowlers_stats[bw_name]["runs"] += bowler_conceded
        bowlers_stats[bw_name]["overs_dict"].setdefault(current_over_idx, 0)
        bowlers_stats[bw_name]["overs_dict"][current_over_idx] += bowler_conceded

        # Batsman runs and balls faced
        if extra != "WIDE":
            batsmen_stats[b_name]["balls"] += 1
        batsmen_stats[b_name]["runs"] += runs
        if runs == 4:
            batsmen_stats[b_name]["fours"] += 1
        elif runs == 6:
            batsmen_stats[b_name]["sixes"] += 1

        # Legal delivery check
        is_legal = extra not in ("WIDE", "NO BALL")
        if is_legal:
            legal_balls_count += 1
            bowlers_stats[bw_name]["legal_balls"] += 1

        # Wicket processing
        if is_wicket:
            total_wickets += 1
            # Bowler wicket attribution: Run out and Retired Hurt do NOT credit bowler
            if w_type in ("BOWLED", "CAUGHT", "LBW", "STUMPED", "HIT WICKET", "HIT_WICKET"):
                bowlers_stats[bw_name]["wickets"] += 1

            fielder = ev.get("fielder_name")
            if w_type == "CAUGHT":
                if fielder and fielder.strip() and fielder.strip().lower() != bw_name.strip().lower():
                    dismissal_str = f"c {fielder} b {bw_name}"
                else:
                    dismissal_str = f"c & b {bw_name}"
            elif w_type == "BOWLED":
                dismissal_str = f"b {bw_name}"
            elif w_type == "LBW":
                dismissal_str = f"lbw b {bw_name}"
            elif w_type == "STUMPED":
                dismissal_str = f"st {fielder or 'wk'} b {bw_name}"
            elif w_type == "RUN OUT":
                dismissal_str = f"run out ({fielder or 'direct'})"
            elif w_type == "HIT WICKET":
                dismissal_str = f"hit wicket b {bw_name}"
            elif w_type == "RETIRED HURT":
                dismissal_str = "retired hurt"
            else:
                dismissal_str = f"{w_type.lower()} b {bw_name}"

            if out_player in batsmen_stats:
                batsmen_stats[out_player]["is_out"] = 1
                batsmen_stats[out_player]["dismissal"] = dismissal_str

            # Next batsman replaces out player
            if out_player == striker_name:
                striker_name = None
            elif out_player == non_striker_name:
                non_striker_name = None

        # Strike rotation:
        # If batsman ran odd runs off bat OR odd byes/leg-byes were run:
        running_runs = runs if extra not in ("BYE", "LEG BYE") else ev["extras"]
        if running_runs % 2 == 1 and striker_name and non_striker_name:
            striker_name, non_striker_name = non_striker_name, striker_name

        # Over completion check
        if is_legal and (legal_balls_count % balls_per_over == 0):
            # End of over: switch strike
            if striker_name and non_striker_name:
                striker_name, non_striker_name = non_striker_name, striker_name

    # Calculate maidens for bowlers
    for bw_name, b_data in bowlers_stats.items():
        completed_overs = b_data["legal_balls"] // balls_per_over
        maidens = 0
        for ov_idx, ov_runs in b_data["overs_dict"].items():
            if ov_runs == 0 and completed_overs > 0:
                maidens += 1
        b_data["maidens"] = maidens

    # Compute overs and balls for innings
    completed_overs = legal_balls_count // balls_per_over
    balls_in_over = legal_balls_count % balls_per_over

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
        b_ov = round(bw_info["legal_balls"] // balls_per_over + (bw_info["legal_balls"] % balls_per_over) / 10.0, 1)
        econ = round(bw_info["runs"] / (bw_info["legal_balls"] / float(balls_per_over)), 2) if bw_info["legal_balls"] > 0 else 0.0
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
            remaining_w = max_wickets - total_wickets
            margin = f"by {remaining_w} wicket{'s' if remaining_w != 1 else ''}"
            cursor.execute("UPDATE matches SET status = 'COMPLETED', winner = ?, result_margin = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (winner_team, margin, inn["match_id"]))
        elif (completed_overs >= total_overs) or (total_wickets >= max_wickets):
            if total_runs == inn["target"] - 1:
                cursor.execute("UPDATE matches SET status = 'COMPLETED', winner = 'Match Tied', result_margin = '', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (inn["match_id"],))
            else:
                winner_team = inn["bowling_team"]
                margin = f"by {inn['target'] - 1 - total_runs} runs"
                cursor.execute("UPDATE matches SET status = 'COMPLETED', winner = ?, result_margin = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (winner_team, margin, inn["match_id"]))

# ==============================================================================
# COMMENTARY GENERATION (DETERMINISTIC TEMPLATES)
# ==============================================================================

def generate_ball_commentary(runs, extras, extra_type, wicket, wicket_type,
                              batsman_name, bowler_name, out_player_name=None, fielder_name=None):
    """Generates deterministic, readable commentary from ball event data."""
    b_short = (batsman_name or "Batter").split()[0]  # first name only for brevity
    bw_short = (bowler_name or "Bowler").split()[0]
    out_short = (out_player_name or batsman_name or "Batter").split()[0]
    f_short = (fielder_name or "Fielder").split()[0] if fielder_name else ""

    if wicket:
        wt = (wicket_type or "OUT").upper()
        if wt == "BOWLED":
            return f"WICKET! {out_short} is clean bowled by {bw_short}!"
        elif wt == "CAUGHT":
            if fielder_name and fielder_name.strip() and fielder_name.strip().lower() != bowler_name.strip().lower():
                return f"WICKET! {out_short} caught by {f_short}, bowled by {bw_short}!"
            return f"WICKET! {out_short} caught & bowled by {bw_short}!"
        elif wt == "LBW":
            return f"WICKET! {out_short} is plumb LBW to {bw_short}!"
        elif wt == "RUN OUT":
            if fielder_name and fielder_name.strip():
                return f"WICKET! {out_short} is run out by {f_short}!"
            return f"WICKET! {out_short} is run out — brilliant fielding!"
        elif wt == "STUMPED":
            if fielder_name and fielder_name.strip():
                return f"WICKET! {out_short} is stumped by {f_short} off {bw_short}!"
            return f"WICKET! {out_short} is stumped off {bw_short}!"
        elif wt == "HIT WICKET":
            return f"WICKET! {out_short} hits their own wicket!"
        elif wt == "RETIRED HURT":
            return f"{out_short} retires hurt."
        else:
            return f"WICKET! {out_short} is out — {wt.lower()} off {bw_short}!"

    et = (extra_type or "").upper()
    if et == "WIDE":
        return f"Wide! Ball drifts down the leg side. {extras} penalty run(s)."
    elif et == "NO BALL":
        total_on_nb = runs + extras
        if runs == 4:
            return f"No ball! FOUR off the free hit — {total_on_nb} runs!"
        elif runs == 6:
            return f"No ball! SIX off the free hit — {total_on_nb} runs!"
        elif runs > 0:
            return f"No ball! {b_short} picks up {runs} run(s). Free hit coming up."
        else:
            return f"No ball from {bw_short}. A free hit to follow."
    elif et == "BYE":
        return f"Bye! Ball sneaks through, {extras} run(s) to the extras."
    elif et == "LEG BYE":
        return f"Leg bye! Flicks off the pads, {extras} run(s)."

    total_runs = runs + extras
    if total_runs == 0:
        return f"Dot ball. {bw_short} beats {b_short} outside off."
    elif total_runs == 1:
        return f"{b_short} nudges it fine for a single."
    elif total_runs == 2:
        return f"{b_short} drives to the gap — two runs."
    elif total_runs == 3:
        return f"Three! {b_short} finds the deep and they run hard."
    elif total_runs == 4:
        return f"FOUR! {b_short} finds the boundary — beautifully timed!"
    elif total_runs == 6:
        return f"SIX! {b_short} launches it clear over the ropes!"
    else:
        return f"{b_short} scores {total_runs} runs off {bw_short}."


def record_ball(match_id, runs=0, extra=None, batsman_name=None, bowler_name=None):
    """
    Authoritative Delivery Recorder with full ACID database transaction.
    """
    with get_db() as conn:
        cursor = conn.cursor()

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

        runs = int(runs or 0)
        extras = 0
        extra_type = extra.strip().upper() if extra else None

        if extra_type == "WIDE":
            extras = 1 + runs
            runs = 0
        elif extra_type == "NO BALL":
            extras = 1
        elif extra_type in ("BYE", "LEG BYE"):
            extras = runs if runs > 0 else 1
            runs = 0

        over_num = inn["overs"]
        ball_num = inn["balls"] + 1 if extra_type not in ("WIDE", "NO BALL") else inn["balls"]

        # Generate commentary
        commentary_text = generate_ball_commentary(
            runs, extras, extra_type, 0, None, batsman_name, bowler_name
        )

        # Insert ball_event
        cursor.execute("""
        INSERT INTO ball_events (innings_id, over_number, ball_number, batsman_name, bowler_name, runs, extras, extra_type, wicket, commentary, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, CURRENT_TIMESTAMP)
        """, (inn_id, over_num, ball_num, batsman_name, bowler_name, runs, extras, extra_type, commentary_text))

        # Re-calculate pure state from events
        recalculate_innings_state(inn_id, conn)
        conn.commit()

    return True, get_live_match_details(match_id)

def record_wicket(match_id, new_batter_name="Next Batter", wicket_type="BOWLED", out_batter_name=None, bowler_name=None, fielder_name=None):
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

        wt = (wicket_type or "BOWLED").upper()
        over_num = inn["overs"]
        ball_num = inn["balls"] + 1

        # Generate wicket commentary
        wkt_commentary = generate_ball_commentary(
            0, 0, None, 1, wt, out_batter_name, bowler_name, out_batter_name, fielder_name
        )

        # Insert wicket ball_event
        cursor.execute("""
        INSERT INTO ball_events (innings_id, over_number, ball_number, batsman_name, bowler_name, runs, extras, wicket, wicket_type, out_player_name, fielder_name, commentary, timestamp)
        VALUES (?, ?, ?, ?, ?, 0, 0, 1, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (inn_id, over_num, ball_num, out_batter_name, bowler_name, wt, out_batter_name, fielder_name, wkt_commentary))

        # Add new batter into batting scores
        if new_batter_name and new_batter_name.strip():
            cursor.execute("SELECT COUNT(*) AS count FROM batting_scores WHERE innings_id = ?", (inn_id,))
            b_count = cursor.fetchone()["count"]
            cursor.execute("""
            INSERT INTO batting_scores (innings_id, player_name, runs, balls, fours, sixes, strike_rate, is_out, batting_order, is_on_strike)
            VALUES (?, ?, 0, 0, 0, 0, 0.0, 0, ?, 1)
            """, (inn_id, new_batter_name.strip(), b_count + 1))

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

def edit_last_ball(match_id, runs=0, extra_type=None, wicket=0, wicket_type=None, batsman_name=None, bowler_name=None, commentary=None):
    """
    Manual correction of the last ball event and authoritative re-projection.
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
        m = cursor.fetchone()
        if not m:
            return False, "Match not found"

        curr_inn = m["current_innings"]
        cursor.execute("SELECT id FROM innings WHERE match_id = ? AND innings_number = ?", (match_id, curr_inn))
        inn = cursor.fetchone()
        if not inn:
            return False, "Active innings not found"

        inn_id = inn["id"]
        cursor.execute("SELECT * FROM ball_events WHERE innings_id = ? ORDER BY id DESC LIMIT 1", (inn_id,))
        last_ev = cursor.fetchone()
        if not last_ev:
            return False, "No ball event found to edit"

        runs = int(runs or 0)
        extras = 0
        et = (extra_type or "").strip().upper() or None
        if et == "WIDE":
            extras = 1 + runs
            runs = 0
        elif et == "NO BALL":
            extras = 1
        elif et in ("BYE", "LEG BYE"):
            extras = runs if runs > 0 else 1
            runs = 0

        b_name = batsman_name or last_ev["batsman_name"]
        bw_name = bowler_name or last_ev["bowler_name"]
        w = 1 if wicket else 0
        wt = (wicket_type or "").upper() if w else None

        comm = commentary
        if not comm:
            comm = generate_ball_commentary(runs, extras, et, w, wt, b_name, bw_name, b_name if w else None)

        cursor.execute("""
        UPDATE ball_events
        SET runs = ?, extras = ?, extra_type = ?, wicket = ?, wicket_type = ?,
            batsman_name = ?, bowler_name = ?, commentary = ?
        WHERE id = ?
        """, (runs, extras, et, w, wt, b_name, bw_name, comm, last_ev["id"]))

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

def swap_strike(match_id):
    """Manually swap on-strike batter and non-striker in the active innings."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
        m = cursor.fetchone()
        if not m:
            return False, "Match not found"

        curr_inn = m["current_innings"]
        cursor.execute("SELECT id FROM innings WHERE match_id = ? AND innings_number = ?", (match_id, curr_inn))
        inn = cursor.fetchone()
        if not inn:
            return False, "Active innings not found"

        inn_id = inn["id"]
        cursor.execute("SELECT id, player_name, is_on_strike FROM batting_scores WHERE innings_id = ? AND is_out = 0 ORDER BY is_on_strike DESC, batting_order ASC LIMIT 2", (inn_id,))
        batters = [dict(r) for r in cursor.fetchall()]
        if len(batters) < 2:
            return False, "Two active batters required on pitch to swap strike"

        b1, b2 = batters[0], batters[1]
        new_b1_strike = 0 if b1["is_on_strike"] else 1
        new_b2_strike = 1 if new_b1_strike == 0 else 0

        cursor.execute("UPDATE batting_scores SET is_on_strike = ? WHERE id = ?", (new_b1_strike, b1["id"]))
        cursor.execute("UPDATE batting_scores SET is_on_strike = ? WHERE id = ?", (new_b2_strike, b2["id"]))
        conn.commit()

    return True, get_live_match_details(match_id)

def set_current_striker(match_id, player_name):
    """Explicitly assign on-strike batter."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
        m = cursor.fetchone()
        if not m:
            return False, "Match not found"

        curr_inn = m["current_innings"]
        cursor.execute("SELECT id FROM innings WHERE match_id = ? AND innings_number = ?", (match_id, curr_inn))
        inn = cursor.fetchone()
        if not inn:
            return False, "Active innings not found"

        inn_id = inn["id"]
        cursor.execute("UPDATE batting_scores SET is_on_strike = 0 WHERE innings_id = ?", (inn_id,))
        cursor.execute("UPDATE batting_scores SET is_on_strike = 1 WHERE innings_id = ? AND player_name = ?", (inn_id, player_name))
        conn.commit()

    return True, get_live_match_details(match_id)

def set_current_bowler(match_id, player_name):
    """Explicitly assign active bowler."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
        m = cursor.fetchone()
        if not m:
            return False, "Match not found"

        curr_inn = m["current_innings"]
        cursor.execute("SELECT id FROM innings WHERE match_id = ? AND innings_number = ?", (match_id, curr_inn))
        inn = cursor.fetchone()
        if not inn:
            return False, "Active innings not found"

        inn_id = inn["id"]
        cursor.execute("UPDATE bowling_scores SET is_current_bowler = 0 WHERE innings_id = ?", (inn_id,))
        cursor.execute("SELECT id FROM bowling_scores WHERE innings_id = ? AND player_name = ?", (inn_id, player_name))
        bw_row = cursor.fetchone()
        if bw_row:
            cursor.execute("UPDATE bowling_scores SET is_current_bowler = 1 WHERE id = ?", (bw_row["id"],))
        else:
            cursor.execute("""
            INSERT INTO bowling_scores (innings_id, player_name, overs, legal_balls, maidens, runs, wickets, economy, is_current_bowler)
            VALUES (?, ?, 0.0, 0, 0, 0, 0, 0.0, 1)
            """, (inn_id, player_name))
        conn.commit()

    return True, get_live_match_details(match_id)

def resume_match(match_id):
    """Resume a paused match back to LIVE state."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE matches SET status = 'LIVE', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (match_id,))
        conn.commit()

    return True, get_live_match_details(match_id)

# ==============================================================================
# LIVE SCORECARD & PUBLIC API AGGREGATION
# ==============================================================================

def get_live_match_details(match_id=None, league_id=None):
    """Returns the comprehensive real-time live match state for Home and Admin panels."""
    with get_db() as conn:
        cursor = conn.cursor()

        if match_id:
            cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
        elif league_id:
            cursor.execute("SELECT * FROM matches WHERE status = 'LIVE' AND league_id = ? ORDER BY id DESC LIMIT 1", (int(league_id),))
        else:
            cursor.execute("SELECT * FROM matches WHERE status = 'LIVE' ORDER BY id DESC LIMIT 1")
        
        m_row = cursor.fetchone()
        if not m_row:
            # Fallback to any recent match if none marked LIVE
            if league_id:
                cursor.execute("SELECT * FROM matches WHERE league_id = ? ORDER BY id DESC LIMIT 1", (int(league_id),))
            else:
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
            "league_id": match.get("league_id") or 1,
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

            # Fall of wickets with progressive score and exact overs
            cursor.execute("""
            SELECT * FROM ball_events 
            WHERE innings_id = ? 
            ORDER BY id ASC
            """, (inn_id,))
            all_inn_evs = [dict(r) for r in cursor.fetchall()]

            fow_events = []
            running_runs = 0
            running_wkts = 0
            for ev in all_inn_evs:
                running_runs += (ev["runs"] or 0) + (ev["extras"] or 0)
                if ev["wicket"]:
                    running_wkts += 1
                    fow_events.append({
                        "id": ev["id"],
                        "innings_id": inn_id,
                        "wicket_number": running_wkts,
                        "runs": running_runs,
                        "batsman_name": ev["out_player_name"] or ev["batsman_name"],
                        "over_number": ev["over_number"],
                        "ball_number": ev["ball_number"],
                        "overs": f"{ev['over_number']}.{ev['ball_number']}",
                        "wicket_type": ev["wicket_type"],
                        "bowler_name": ev["bowler_name"],
                        "fielder_name": ev.get("fielder_name"),
                        "commentary": ev["commentary"]
                    })
            
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

def recalculate_standings(league_id=None):
    """Computes tournament points table from completed matches for a specific league (or all leagues).
    Calculates P, W, L, T, NR, Pts, and NRR (accounting for all-out full overs quota).
    Persists results to league_standings and returns sorted standings."""
    with get_db() as conn:
        cursor = conn.cursor()
        if league_id is not None:
            league_ids = [int(league_id)]
        else:
            cursor.execute("SELECT id FROM leagues WHERE status = 'active'")
            league_ids = [r["id"] for r in cursor.fetchall()]
            if not league_ids:
                league_ids = [1]

        final_result = []
        for lid in league_ids:
            # 1. Get all teams relevant to this league
            cursor.execute("""
            SELECT DISTINCT t.id, t.name, t.color, t.captain FROM (
                SELECT id, name, color, captain FROM teams WHERE league_id = ?
                UNION
                SELECT t.id, t.name, t.color, t.captain FROM teams t
                JOIN matches m ON (m.team_a = t.name OR m.team_b = t.name)
                WHERE m.league_id = ?
            ) t
            """, (lid, lid))
            league_teams = [dict(r) for r in cursor.fetchall()]

            cursor.execute("""
            SELECT DISTINCT team_a AS name FROM matches WHERE league_id = ?
            UNION
            SELECT DISTINCT team_b AS name FROM matches WHERE league_id = ?
            """, (lid, lid))
            match_team_names = [r["name"] for r in cursor.fetchall()]
            known_names = {t["name"] for t in league_teams}
            for m_name in match_team_names:
                if m_name and m_name not in known_names:
                    league_teams.append({
                        "id": m_name.replace(" ", "_"),
                        "name": m_name,
                        "color": "#1a73e8",
                        "captain": "N/A"
                    })
                    known_names.add(m_name)

            standings_map = {}
            for t in league_teams:
                standings_map[t["name"]] = {
                    "league_id": lid,
                    "team_id": t["id"],
                    "team": t["name"],
                    "captain": t.get("captain", "N/A"),
                    "color": t.get("color", "#1a73e8"),
                    "p": 0, "w": 0, "l": 0, "t": 0, "nr": 0, "pts": 0,
                    "runs_scored": 0,
                    "legal_balls_faced": 0,
                    "runs_conceded": 0,
                    "legal_balls_bowled": 0,
                    "nrr_val": 0.0,
                    "nrr": "+0.00"
                }

            # 2. Query completed matches for this league ONLY
            cursor.execute("SELECT * FROM matches WHERE league_id = ? AND status = 'COMPLETED'", (lid,))
            completed_matches = [dict(r) for r in cursor.fetchall()]

            for m in completed_matches:
                tA = m["team_a"]
                tB = m["team_b"]
                winner = (m["winner"] or "").strip()
                margin = (m["result_margin"] or "").strip().lower()
                match_overs = m.get("total_overs") or 10

                if tA not in standings_map:
                    standings_map[tA] = {
                        "league_id": lid, "team_id": tA.replace(" ", "_"), "team": tA,
                        "captain": "N/A", "color": "#1a73e8",
                        "p": 0, "w": 0, "l": 0, "t": 0, "nr": 0, "pts": 0,
                        "runs_scored": 0, "legal_balls_faced": 0,
                        "runs_conceded": 0, "legal_balls_bowled": 0,
                        "nrr_val": 0.0, "nrr": "+0.00"
                    }
                if tB not in standings_map:
                    standings_map[tB] = {
                        "league_id": lid, "team_id": tB.replace(" ", "_"), "team": tB,
                        "captain": "N/A", "color": "#1a73e8",
                        "p": 0, "w": 0, "l": 0, "t": 0, "nr": 0, "pts": 0,
                        "runs_scored": 0, "legal_balls_faced": 0,
                        "runs_conceded": 0, "legal_balls_bowled": 0,
                        "nrr_val": 0.0, "nrr": "+0.00"
                    }

                standings_map[tA]["p"] += 1
                standings_map[tB]["p"] += 1

                # Result points
                if "tied" in margin or "tie" in winner.lower():
                    standings_map[tA]["t"] += 1
                    standings_map[tA]["pts"] += 1
                    standings_map[tB]["t"] += 1
                    standings_map[tB]["pts"] += 1
                elif "no result" in margin or not winner:
                    standings_map[tA]["nr"] += 1
                    standings_map[tA]["pts"] += 1
                    standings_map[tB]["nr"] += 1
                    standings_map[tB]["pts"] += 1
                elif tA in winner:
                    standings_map[tA]["w"] += 1
                    standings_map[tA]["pts"] += 2
                    standings_map[tB]["l"] += 1
                elif tB in winner:
                    standings_map[tB]["w"] += 1
                    standings_map[tB]["pts"] += 2
                    standings_map[tA]["l"] += 1
                else:
                    standings_map[tA]["nr"] += 1
                    standings_map[tA]["pts"] += 1
                    standings_map[tB]["nr"] += 1
                    standings_map[tB]["pts"] += 1

                # Inning scores for NRR
                cursor.execute("SELECT * FROM innings WHERE match_id = ? ORDER BY innings_number ASC", (m["id"],))
                inns = [dict(r) for r in cursor.fetchall()]
                inn1 = next((i for i in inns if i["innings_number"] == 1), None)
                inn2 = next((i for i in inns if i["innings_number"] == 2), None)

                for inn, opp_inn in [(inn1, inn2), (inn2, inn1)]:
                    if not inn:
                        continue
                    bat_team = inn["batting_team"]
                    bowl_team = inn["bowling_team"]

                    runs = inn.get("runs", 0)
                    wickets = inn.get("wickets", 0)
                    overs = inn.get("overs", 0)
                    balls = inn.get("balls", 0)

                    # All-out rule: if 10 wickets down, overs faced = full quota of match
                    if wickets >= 10:
                        balls_faced = match_overs * 6
                    else:
                        balls_faced = (overs * 6) + balls

                    if bat_team in standings_map:
                        standings_map[bat_team]["runs_scored"] += runs
                        standings_map[bat_team]["legal_balls_faced"] += balls_faced

                    if bowl_team in standings_map:
                        standings_map[bowl_team]["runs_conceded"] += runs
                        standings_map[bowl_team]["legal_balls_bowled"] += balls_faced

            # 3. Compute NRR for each team
            league_res = list(standings_map.values())
            for s in league_res:
                rr_for = (s["runs_scored"] / (s["legal_balls_faced"] / 6.0)) if s["legal_balls_faced"] > 0 else 0.0
                rr_against = (s["runs_conceded"] / (s["legal_balls_bowled"] / 6.0)) if s["legal_balls_bowled"] > 0 else 0.0
                nrr_val = round(rr_for - rr_against, 2)
                s["nrr_val"] = nrr_val
                s["nrr"] = f"{nrr_val:+.2f}"

            # 4. Sort standings by Points DESC, NRR DESC, Name ASC
            league_res.sort(key=lambda x: (-x["pts"], -x["nrr_val"], x["team"]))
            for idx, s in enumerate(league_res):
                s["pos"] = idx + 1
                s["qualified"] = (idx < 2)

                # Persist to league_standings table
                cursor.execute("""
                INSERT INTO league_standings (
                    league_id, team_name, played, wins, losses, ties, no_results, points,
                    runs_scored, overs_faced, runs_conceded, overs_bowled, net_run_rate, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(league_id, team_name) DO UPDATE SET
                    played = excluded.played,
                    wins = excluded.wins,
                    losses = excluded.losses,
                    ties = excluded.ties,
                    no_results = excluded.no_results,
                    points = excluded.points,
                    runs_scored = excluded.runs_scored,
                    overs_faced = excluded.overs_faced,
                    runs_conceded = excluded.runs_conceded,
                    overs_bowled = excluded.overs_bowled,
                    net_run_rate = excluded.net_run_rate,
                    updated_at = CURRENT_TIMESTAMP
                """, (
                    lid, s["team"], s["p"], s["w"], s["l"], s["t"], s["nr"], s["pts"],
                    s["runs_scored"], s["legal_balls_faced"] / 6.0,
                    s["runs_conceded"], s["legal_balls_bowled"] / 6.0,
                    s["nrr_val"]
                ))

            conn.commit()
            if league_id is not None:
                return league_res
            final_result.extend(league_res)

        return final_result

# ==============================================================================
# MATCH CENTER — COMMENTARY, OVERS, INFO QUERIES
# ==============================================================================

def get_match_commentary(match_id):
    """Returns ball-by-ball commentary for all innings of a match, newest first."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
        m = cursor.fetchone()
        if not m:
            return None

        cursor.execute("SELECT * FROM innings WHERE match_id = ? ORDER BY innings_number ASC", (match_id,))
        innings_list = [dict(r) for r in cursor.fetchall()]

        result = []
        for inn in innings_list:
            cursor.execute("""
            SELECT * FROM ball_events WHERE innings_id = ?
            ORDER BY id DESC
            """, (inn["id"],))
            events = []
            for ev in cursor.fetchall():
                ev_dict = dict(ev)
                # Build or regenerate commentary if missing
                if not ev_dict.get("commentary"):
                    ev_dict["commentary"] = generate_ball_commentary(
                        ev_dict["runs"], ev_dict["extras"], ev_dict["extra_type"],
                        ev_dict["wicket"], ev_dict["wicket_type"],
                        ev_dict["batsman_name"], ev_dict["bowler_name"],
                        ev_dict["out_player_name"]
                    )
                # Build label
                if ev_dict["wicket"]:
                    ev_dict["label"] = "WICKET"
                elif ev_dict["extra_type"] == "WIDE":
                    ev_dict["label"] = "WD"
                elif ev_dict["extra_type"] == "NO BALL":
                    ev_dict["label"] = "NB"
                elif ev_dict["extra_type"] in ("BYE", "LEG BYE"):
                    ev_dict["label"] = ev_dict["extra_type"][:2]
                elif ev_dict["runs"] == 4:
                    ev_dict["label"] = "FOUR"
                elif ev_dict["runs"] == 6:
                    ev_dict["label"] = "SIX"
                elif ev_dict["runs"] == 0:
                    ev_dict["label"] = "DOT"
                else:
                    ev_dict["label"] = str(ev_dict["runs"])
                ev_dict["over_ball"] = f"{ev_dict['over_number']}.{ev_dict['ball_number']}"
                events.append(ev_dict)
            result.append({
                "innings_number": inn["innings_number"],
                "batting_team": inn["batting_team"],
                "bowling_team": inn["bowling_team"],
                "events": events
            })
        return result


def get_match_overs(match_id):
    """Returns ball events grouped by innings and over number."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
        m = cursor.fetchone()
        if not m:
            return None

        cursor.execute("SELECT * FROM innings WHERE match_id = ? ORDER BY innings_number ASC", (match_id,))
        innings_list = [dict(r) for r in cursor.fetchall()]

        result = []
        for inn in innings_list:
            cursor.execute("""
            SELECT * FROM ball_events WHERE innings_id = ? ORDER BY id ASC
            """, (inn["id"],))
            events = [dict(r) for r in cursor.fetchall()]

            overs_dict = {}
            for ev in events:
                ov = ev["over_number"]
                if ov not in overs_dict:
                    overs_dict[ov] = {"over_number": ov, "runs": 0, "wickets": 0,
                                      "extras": 0, "legal_balls": 0, "balls": []}
                o = overs_dict[ov]
                total_ev_runs = ev["runs"] + ev["extras"]
                o["runs"] += total_ev_runs
                o["wickets"] += ev["wicket"]
                o["extras"] += ev["extras"]
                is_legal = ev["extra_type"] not in ("WIDE", "NO BALL")
                if is_legal:
                    o["legal_balls"] += 1
                # Build display label for each ball
                if ev["wicket"]:
                    display = "W"
                elif ev["extra_type"] == "WIDE":
                    display = "Wd"
                elif ev["extra_type"] == "NO BALL":
                    display = "Nb"
                elif ev["extra_type"] == "BYE":
                    display = f"B{ev['extras']}"
                elif ev["extra_type"] == "LEG BYE":
                    display = f"Lb{ev['extras']}"
                else:
                    display = str(ev["runs"])
                o["balls"].append({
                    "display": display,
                    "runs": ev["runs"],
                    "extras": ev["extras"],
                    "extra_type": ev["extra_type"],
                    "wicket": ev["wicket"],
                    "is_legal": is_legal,
                    "batsman": ev["batsman_name"],
                    "bowler": ev["bowler_name"]
                })

            result.append({
                "innings_number": inn["innings_number"],
                "batting_team": inn["batting_team"],
                "bowling_team": inn["bowling_team"],
                "total_runs": inn["runs"],
                "total_wickets": inn["wickets"],
                "overs": sorted(overs_dict.values(), key=lambda x: x["over_number"], reverse=True)
            })
        return result


def get_match_info(match_id):
    """Returns structured match metadata for the Info tab."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT m.*, l.name as league_name, l.short_name as league_short_name
        FROM matches m LEFT JOIN leagues l ON m.league_id = l.id
        WHERE m.id = ?
        """, (match_id,))
        row = cursor.fetchone()
        if not row:
            return None
        m = dict(row)

        cursor.execute("SELECT * FROM innings WHERE match_id = ? ORDER BY innings_number ASC", (match_id,))
        inns = [dict(r) for r in cursor.fetchall()]
        inn1 = next((i for i in inns if i["innings_number"] == 1), None)
        inn2 = next((i for i in inns if i["innings_number"] == 2), None)

        return {
            "id": m["id"],
            "match_name": m["match_name"],
            "league": m.get("league_name", "—"),
            "league_id": m.get("league_id"),
            "team_a": m["team_a"],
            "team_b": m["team_b"],
            "venue": m.get("venue", "—"),
            "date": m.get("match_date", "—"),
            "status": m["status"],
            "total_overs": m["total_overs"],
            "winner": m.get("winner", ""),
            "result_margin": m.get("result_margin", ""),
            "toss": None,  # placeholder for future
            "innings_count": len(inns),
            "inn1_summary": (
                f"{inn1['batting_team']} {inn1['runs']}/{inn1['wickets']} ({inn1['overs']}.{inn1['balls']} ov)"
                if inn1 else None
            ),
            "inn2_summary": (
                f"{inn2['batting_team']} {inn2['runs']}/{inn2['wickets']} ({inn2['overs']}.{inn2['balls']} ov)"
                if inn2 else None
            ),
        }


# Initialize on module import
init_db()

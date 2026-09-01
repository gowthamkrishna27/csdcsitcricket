import os
import json
import copy
import time
from dotenv import load_dotenv
from pymongo import MongoClient
import certifi

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI")
DB_NAME = "hpl_cricket_db"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_FILE = os.path.join(DATA_DIR, "hpl_database.json")

os.makedirs(DATA_DIR, exist_ok=True)

_cached_client = None
_atlas_status = {"available": False, "last_checked": 0, "error": None}

def get_client():
    global _cached_client
    if _cached_client is None:
        if not MONGODB_URI:
            raise ValueError("MONGODB_URI is not defined in .env")
        _cached_client = MongoClient(
            MONGODB_URI,
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=1000,
            connectTimeoutMS=1000,
            socketTimeoutMS=1000
        )
    return _cached_client

def get_mongo_db():
    global _atlas_status
    now = time.time()
    if not _atlas_status["available"] and (now - _atlas_status["last_checked"]) < 30:
        return None
    try:
        client = get_client()
        db = client[DB_NAME]
        db.command("ping")
        _atlas_status["available"] = True
        _atlas_status["last_checked"] = now
        _atlas_status["error"] = None
        return db
    except Exception as e:
        _atlas_status["available"] = False
        _atlas_status["last_checked"] = now
        _atlas_status["error"] = str(e)
        return None

def test_connection():
    db = get_mongo_db()
    if db is not None:
        return True, "Connected successfully to MongoDB Atlas"
    err = _atlas_status.get("error") or "Atlas cluster unreachable"
    return False, err

from werkzeug.security import generate_password_hash, check_password_hash

# --------------------------------------------------------------------------
# PERSISTENT STORAGE
# --------------------------------------------------------------------------
EMPTY_SCHEMA = {
    "teams": [],
    "players": [],
    "matches": [],
    "standings": [],
    "admins": [],
    "settings": {
        "tournamentName": "House Premiere League",
        "season": "HPL 2026",
        "format": "T10",
        "ptsWin": 2,
        "ptsNr": 1
    }
}

DEFAULT_HPL_SEED = {
    "teams": [
        {"id": "T1", "name": "House Vayu", "short": "VAY", "captain": "Rahul Sharma", "color": "#2980b9"},
        {"id": "T2", "name": "House Agni", "short": "AGN", "captain": "Rohit Verma", "color": "#e67e22"},
        {"id": "T3", "name": "House Akasha", "short": "AKA", "captain": "Siddharth Roy", "color": "#8e44ad"},
        {"id": "T4", "name": "House Jala", "short": "JAL", "captain": "Vikram Patel", "color": "#16a085"},
        {"id": "T5", "name": "House Prithvi", "short": "PRI", "captain": "Aditya Rao", "color": "#27ae60"}
    ],
    "players": [
        {"id": "P01", "name": "Rahul Sharma", "team": "House Vayu", "role": "Batsman", "jersey": 7},
        {"id": "P02", "name": "Arjun Varma", "team": "House Vayu", "role": "All-Rounder", "jersey": 18},
        {"id": "P03", "name": "Rohit Verma", "team": "House Agni", "role": "Batsman", "jersey": 10},
        {"id": "P04", "name": "Sai Krishna", "team": "House Agni", "role": "Bowler", "jersey": 23},
        {"id": "P05", "name": "Siddharth Roy", "team": "House Akasha", "role": "All-Rounder", "jersey": 3},
        {"id": "P06", "name": "Vikram Patel", "team": "House Jala", "role": "Batsman", "jersey": 9},
        {"id": "P07", "name": "Aditya Rao", "team": "House Prithvi", "role": "All-Rounder", "jersey": 1}
    ],
    "matches": [
        {
            "id": "M08",
            "matchNo": "08",
            "teamA": "House Vayu",
            "teamB": "House Agni",
            "date": "Today",
            "time": "02:00 PM",
            "venue": "College Ground",
            "overs": 10,
            "status": "LIVE",
            "scoreA": "128/5",
            "oversA": "8.3",
            "scoreB": "Yet to Bat",
            "oversB": "0.0",
            "winner": "",
            "liveScorecard": {
                "runs": 128,
                "wickets": 5,
                "oversCompleted": 8,
                "ballsInOver": 3,
                "striker": {"name": "Rahul Kumar", "runs": 48, "balls": 29},
                "nonStriker": {"name": "Arjun Reddy", "runs": 21, "balls": 14},
                "bowler": {"name": "Sai Krishna", "wickets": 2, "runs": 24},
                "currentOverBalls": ["1", "4", "2"]
            }
        },
        {
            "id": "M09",
            "matchNo": "09",
            "teamA": "House Jala",
            "teamB": "House Prithvi",
            "date": "15 SEP",
            "time": "04:00 PM",
            "venue": "College Ground",
            "overs": 10,
            "status": "UPCOMING",
            "scoreA": "",
            "oversA": "",
            "scoreB": "",
            "oversB": "",
            "winner": ""
        }
    ],
    "standings": [
        {"pos": 1, "team": "House Vayu", "p": 4, "w": 3, "l": 1, "nr": 0, "pts": 6, "nrr": "+1.245"},
        {"pos": 2, "team": "House Agni", "p": 4, "w": 3, "l": 1, "nr": 0, "pts": 6, "nrr": "+0.890"},
        {"pos": 3, "team": "House Akasha", "p": 4, "w": 2, "l": 2, "nr": 0, "pts": 4, "nrr": "+0.150"},
        {"pos": 4, "team": "House Jala", "p": 3, "w": 1, "l": 2, "nr": 0, "pts": 2, "nrr": "-0.420"},
        {"pos": 5, "team": "House Prithvi", "p": 3, "w": 0, "l": 3, "nr": 0, "pts": 0, "nrr": "-1.865"}
    ],
    "settings": {
        "tournamentName": "House Premiere League",
        "season": "HPL 2026",
        "format": "T10",
        "ptsWin": 2,
        "ptsNr": 1
    }
}

def load_local_db():
    if not os.path.exists(DB_FILE):
        save_local_db(EMPTY_SCHEMA)
        return copy.deepcopy(EMPTY_SCHEMA)
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            for k in EMPTY_SCHEMA:
                if k not in data:
                    data[k] = copy.deepcopy(EMPTY_SCHEMA[k])
            return data
    except Exception:
        return copy.deepcopy(EMPTY_SCHEMA)

def save_local_db(data):
    try:
        # Guarantee admins are never accidentally dropped
        if "admins" not in data or not data["admins"]:
            if os.path.exists(DB_FILE):
                try:
                    with open(DB_FILE, "r", encoding="utf-8") as f_prev:
                        prev = json.load(f_prev)
                        if prev.get("admins"):
                            data["admins"] = prev["admins"]
                except Exception:
                    pass
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error writing to local DB file: {e}")

def get_all_data():
    """Returns the entire database dictionary."""
    try:
        db = get_mongo_db()
        if db is not None:
            atlas_data = {}
            for col in ["teams", "players", "matches", "standings", "admins"]:
                items = list(db[col].find({}, {"_id": 0}))
                atlas_data[col] = items
            settings = db["settings"].find_one({}, {"_id": 0})
            if settings:
                atlas_data["settings"] = settings
            
            # Strictly preserve local admins if Atlas admins collection is empty or not yet synced
            local_admins = load_local_db().get("admins", [])
            if not atlas_data.get("admins"):
                atlas_data["admins"] = local_admins
                # Sync local admins to Atlas
                if local_admins:
                    try:
                        db["admins"].delete_many({})
                        db["admins"].insert_many(copy.deepcopy(local_admins))
                    except Exception:
                        pass

            if any(atlas_data.get(c) for c in ["teams", "players", "matches", "standings"]):
                save_local_db(atlas_data)
                return atlas_data, True
    except Exception:
        pass
    return load_local_db(), False

def get_collection(col_name):
    data, is_atlas = get_all_data()
    return data.get(col_name, []), is_atlas

def set_collection(col_name, items):
    data = load_local_db()
    data[col_name] = items
    save_local_db(data)

    synced_atlas = False
    try:
        db = get_mongo_db()
        if db is not None:
            db[col_name].delete_many({})
            if items:
                db[col_name].insert_many(copy.deepcopy(items))
            synced_atlas = True
    except Exception:
        pass

    return True, synced_atlas

def wipe_all_database():
    """Wipes all tournament data while preserving registered admin accounts."""
    data = load_local_db()
    admins = data.get("admins", [])
    
    empty = copy.deepcopy(EMPTY_SCHEMA)
    empty["admins"] = admins
    save_local_db(empty)

    synced_atlas = False
    try:
        db = get_mongo_db()
        if db is not None:
            for col in ["teams", "players", "matches", "standings"]:
                db[col].delete_many({})
            synced_atlas = True
    except Exception:
        pass

    return True, synced_atlas

def seed_database():
    """Seeds clean HPL tournament data while strictly preserving registered admin accounts."""
    data = load_local_db()
    admins = data.get("admins", [])
    if not admins:
        bootstrap_first_admin_if_empty()
        data = load_local_db()
        admins = data.get("admins", [])
    
    seed_data = copy.deepcopy(DEFAULT_HPL_SEED)
    seed_data["admins"] = copy.deepcopy(admins)
    save_local_db(seed_data)

    synced_atlas = False
    try:
        db = get_mongo_db()
        if db is not None:
            for col in ["teams", "players", "matches", "standings"]:
                db[col].delete_many({})
                if seed_data[col]:
                    db[col].insert_many(copy.deepcopy(seed_data[col]))
            db["settings"].delete_many({})
            db["settings"].insert_one(copy.deepcopy(seed_data["settings"]))
            synced_atlas = True
    except Exception:
        pass

    return True, synced_atlas

# --------------------------------------------------------------------------
# TEAM OPERATIONS (WITH VALIDATION & DEPENDENCY CHECKING)
# --------------------------------------------------------------------------
def create_team(name, short, captain, color="#1a73e8"):
    name = (name or "").strip()
    if not name:
        return False, "Team name cannot be empty"

    data = load_local_db()
    teams = data.get("teams", [])
    
    # Check duplicate
    for t in teams:
        if t["name"].lower() == name.lower():
            return False, f"Team '{name}' already exists"

    short = (short or "").strip().toUpperCase() if hasattr(short, "toUpperCase") else (short or "").strip().upper()
    if not short:
        short = name[:3].upper()

    team_id = f"T{int(time.time() * 1000) % 10000:04d}"
    new_team = {
        "id": team_id,
        "name": name,
        "short": short,
        "captain": (captain or "TBD").strip(),
        "color": color or "#1a73e8"
    }
    teams.append(new_team)
    set_collection("teams", teams)

    # Automatically add to standings
    recalculate_standings_internal()
    return True, new_team

def update_team(team_id, name, short, captain, color):
    data = load_local_db()
    teams = data.get("teams", [])
    found = None
    for t in teams:
        if t["id"] == team_id:
            found = t
            break
    if not found:
        return False, f"Team with ID {team_id} not found"

    old_name = found["name"]
    name = (name or old_name).strip()
    if not name:
        return False, "Team name cannot be empty"

    # Check duplicate if name changed
    if name.lower() != old_name.lower():
        for t in teams:
            if t["id"] != team_id and t["name"].lower() == name.lower():
                return False, f"Team '{name}' already exists"

    found["name"] = name
    found["short"] = (short or name[:3]).strip().upper()
    found["captain"] = (captain or found.get("captain", "TBD")).strip()
    if color:
        found["color"] = color

    set_collection("teams", teams)

    # Cascade rename if name changed
    if name != old_name:
        # Players
        players = data.get("players", [])
        for p in players:
            if p.get("team") == old_name:
                p["team"] = name
        set_collection("players", players)

        # Matches
        matches = data.get("matches", [])
        for m in matches:
            if m.get("teamA") == old_name:
                m["teamA"] = name
            if m.get("teamB") == old_name:
                m["teamB"] = name
        set_collection("matches", matches)

        recalculate_standings_internal()

    return True, found

def delete_team(team_id):
    data = load_local_db()
    teams = data.get("teams", [])
    found = None
    for t in teams:
        if t["id"] == team_id:
            found = t
            break
    if not found:
        return False, f"Team with ID {team_id} not found"

    team_name = found["name"]
    # Check dependencies: players and matches
    players = [p for p in data.get("players", []) if p.get("team") == team_name]
    matches = [m for m in data.get("matches", []) if m.get("teamA") == team_name or m.get("teamB") == team_name]

    if players or matches:
        p_cnt = len(players)
        m_cnt = len(matches)
        return False, f"Cannot delete '{team_name}': it has {p_cnt} players and {m_cnt} matches associated. Delete or reassign them first."

    teams = [t for t in teams if t["id"] != team_id]
    set_collection("teams", teams)

    # Remove from standings
    standings = [s for s in data.get("standings", []) if s.get("team") != team_name]
    set_collection("standings", standings)
    recalculate_standings_internal()

    return True, f"Team '{team_name}' deleted successfully"

# --------------------------------------------------------------------------
# PLAYER OPERATIONS
# --------------------------------------------------------------------------
def create_player(name, team, role, jersey):
    name = (name or "").strip()
    if not name:
        return False, "Player name cannot be empty"

    data = load_local_db()
    teams = [t["name"] for t in data.get("teams", [])]
    if team not in teams:
        return False, f"Team '{team}' does not exist"

    role = (role or "Batsman").strip()
    try:
        jersey = int(jersey)
    except (ValueError, TypeError):
        jersey = 0

    player_id = f"P{int(time.time() * 1000) % 10000:04d}"
    new_player = {
        "id": player_id,
        "name": name,
        "team": team,
        "role": role,
        "jersey": jersey
    }

    players = data.get("players", [])
    players.append(new_player)
    set_collection("players", players)
    return True, new_player

def delete_player(player_id):
    data = load_local_db()
    players = data.get("players", [])
    found = [p for p in players if p["id"] == player_id]
    if not found:
        return False, f"Player {player_id} not found"

    players = [p for p in players if p["id"] != player_id]
    set_collection("players", players)
    return True, f"Player {found[0]['name']} removed successfully"

# --------------------------------------------------------------------------
# MATCH SCHEDULING & AUTHORITATIVE SCORING
# --------------------------------------------------------------------------
def schedule_match(team_a, team_b, date, time_str, venue, overs=10):
    if not team_a or not team_b:
        return False, "Both Team A and Team B are required"
    if team_a == team_b:
        return False, "Team A and Team B cannot be the same"

    data = load_local_db()
    team_names = [t["name"] for t in data.get("teams", [])]
    if team_a not in team_names:
        return False, f"Team '{team_a}' does not exist"
    if team_b not in team_names:
        return False, f"Team '{team_b}' does not exist"

    matches = data.get("matches", [])
    match_no = f"{len(matches) + 1:02d}"
    match_id = f"M{match_no}"

    new_match = {
        "id": match_id,
        "matchNo": match_no,
        "teamA": team_a,
        "teamB": team_b,
        "date": date or "TBD",
        "time": time_str or "TBD",
        "venue": venue or "College Ground",
        "overs": int(overs) if overs else 10,
        "status": "UPCOMING",
        "scoreA": "",
        "oversA": "",
        "scoreB": "",
        "oversB": "",
        "winner": ""
    }

    matches.insert(0, new_match)
    set_collection("matches", matches)
    return True, new_match

def start_match(match_id):
    data = load_local_db()
    matches = data.get("matches", [])
    target = None
    for m in matches:
        if m["id"] == match_id:
            target = m
        elif m.get("status") == "LIVE":
            m["status"] = "COMPLETED"

    if not target:
        return False, f"Match {match_id} not found"

    players = data.get("players", [])
    squad_a = [p for p in players if p.get("team") == target["teamA"]]
    squad_b = [p for p in players if p.get("team") == target["teamB"]]

    striker_name = squad_a[0]["name"] if squad_a else "Striker"
    non_striker_name = squad_a[1]["name"] if len(squad_a) > 1 else "Non-Striker"
    bowler_name = squad_b[0]["name"] if squad_b else "Bowler"

    target["status"] = "LIVE"
    target["scoreA"] = "0/0"
    target["oversA"] = "0.0"
    target["scoreB"] = "Yet to Bat"
    target["oversB"] = "0.0"
    target["liveScorecard"] = {
        "runs": 0,
        "wickets": 0,
        "oversCompleted": 0,
        "ballsInOver": 0,
        "striker": {"name": striker_name, "runs": 0, "balls": 0},
        "nonStriker": {"name": non_striker_name, "runs": 0, "balls": 0},
        "bowler": {"name": bowler_name, "wickets": 0, "runs": 0},
        "currentOverBalls": []
    }

    set_collection("matches", matches)
    return True, target

def record_ball(match_id, runs=0, extra=None):
    """
    Authoritative backend delivery calculator.
    Guarantees tournament integrity.
    """
    data = load_local_db()
    matches = data.get("matches", [])
    target = None
    for m in matches:
        if m["id"] == match_id and m.get("status") == "LIVE":
            target = m
            break
    if not target:
        # Fallback: check any live match
        for m in matches:
            if m.get("status") == "LIVE":
                target = m
                break
    if not target:
        return False, "No active LIVE match found"

    sc = target.setdefault("liveScorecard", {
        "runs": 0, "wickets": 0, "oversCompleted": 0, "ballsInOver": 0,
        "striker": {"name": "Striker", "runs": 0, "balls": 0},
        "nonStriker": {"name": "Non-Striker", "runs": 0, "balls": 0},
        "bowler": {"name": "Bowler", "wickets": 0, "runs": 0},
        "currentOverBalls": []
    })

    runs = int(runs)
    added_runs = runs
    counts_as_ball = True

    if extra in ("WIDE", "NO BALL"):
        added_runs += 1
        counts_as_ball = False

    sc["runs"] += added_runs

    # Batter runs
    if extra not in ("WIDE", "BYE", "LEG BYE"):
        sc["striker"]["runs"] += runs
    if extra != "WIDE":
        sc["striker"]["balls"] += 1

    sc["bowler"]["runs"] += added_runs

    # Timeline marker
    marker = str(runs)
    if extra:
        marker = extra[0]
    sc["currentOverBalls"].append(marker)

    if counts_as_ball:
        sc["ballsInOver"] += 1
        if sc["ballsInOver"] == 6:
            sc["oversCompleted"] += 1
            sc["ballsInOver"] = 0
            sc["currentOverBalls"] = []
            # Over change: swap strike
            temp = sc["striker"]
            sc["striker"] = sc["nonStriker"]
            sc["nonStriker"] = temp
        elif runs % 2 == 1:
            temp = sc["striker"]
            sc["striker"] = sc["nonStriker"]
            sc["nonStriker"] = temp

    target["scoreA"] = f"{sc['runs']}/{sc['wickets']}"
    target["oversA"] = f"{sc['oversCompleted']}.{sc['ballsInOver']}"

    set_collection("matches", matches)
    return True, target

def record_wicket(match_id, new_batter_name):
    data = load_local_db()
    matches = data.get("matches", [])
    target = None
    for m in matches:
        if m["id"] == match_id and m.get("status") == "LIVE":
            target = m
            break
    if not target:
        for m in matches:
            if m.get("status") == "LIVE":
                target = m
                break
    if not target:
        return False, "No active LIVE match found"

    sc = target["liveScorecard"]
    sc["wickets"] += 1
    sc["bowler"]["wickets"] += 1
    sc["ballsInOver"] += 1
    sc["currentOverBalls"].append("W")

    sc["striker"] = {"name": new_batter_name or "Next Batter", "runs": 0, "balls": 0}

    if sc["ballsInOver"] == 6:
        sc["oversCompleted"] += 1
        sc["ballsInOver"] = 0
        sc["currentOverBalls"] = []

    target["scoreA"] = f"{sc['runs']}/{sc['wickets']}"
    target["oversA"] = f"{sc['oversCompleted']}.{sc['ballsInOver']}"

    set_collection("matches", matches)
    return True, target

def complete_match(match_id, winner_team, score_b="Yet to Bat", margin=""):
    data = load_local_db()
    matches = data.get("matches", [])
    target = None
    for m in matches:
        if m["id"] == match_id:
            target = m
            break
    if not target:
        for m in matches:
            if m.get("status") == "LIVE":
                target = m
                break
    if not target:
        return False, "Match not found"

    target["status"] = "COMPLETED"
    if score_b and score_b != "Yet to Bat":
        target["scoreB"] = score_b
    winner_team = (winner_team or target["teamA"]).strip()
    target["winner"] = f"{winner_team} won {margin}".strip()

    set_collection("matches", matches)
    # Recalculate standings automatically
    recalculate_standings_internal()
    return True, target

# --------------------------------------------------------------------------
# AUTOMATIC POINTS TABLE STANDINGS
# --------------------------------------------------------------------------
def recalculate_standings_internal():
    data = load_local_db()
    teams = data.get("teams", [])
    matches = data.get("matches", [])

    standings_map = {}
    for t in teams:
        standings_map[t["name"]] = {
            "pos": 1,
            "team": t["name"],
            "color": t.get("color", "#1a73e8"),
            "p": 0, "w": 0, "l": 0, "nr": 0, "pts": 0,
            "nrr": "+0.00"
        }

    for m in matches:
        if m.get("status") == "COMPLETED":
            tA = m.get("teamA")
            tB = m.get("teamB")
            winner = m.get("winner", "")

            if tA in standings_map:
                standings_map[tA]["p"] += 1
            if tB in standings_map:
                standings_map[tB]["p"] += 1

            if winner and tA and tA in winner:
                if tA in standings_map:
                    standings_map[tA]["w"] += 1
                    standings_map[tA]["pts"] += 2
                if tB in standings_map:
                    standings_map[tB]["l"] += 1
            elif winner and tB and tB in winner:
                if tB in standings_map:
                    standings_map[tB]["w"] += 1
                    standings_map[tB]["pts"] += 2
                if tA in standings_map:
                    standings_map[tA]["l"] += 1
            else:
                if tA in standings_map:
                    standings_map[tA]["nr"] += 1
                    standings_map[tA]["pts"] += 1
                if tB in standings_map:
                    standings_map[tB]["nr"] += 1
                    standings_map[tB]["pts"] += 1

    standings_list = list(standings_map.values())
    # Sort by Points desc, then name
    standings_list.sort(key=lambda x: (-x["pts"], x["team"]))
    for idx, s in enumerate(standings_list):
        s["pos"] = idx + 1

    set_collection("standings", standings_list)
    return standings_list

def get_live_match():
    matches, _ = get_collection("matches")
    for m in matches:
        if m.get("status") == "LIVE":
            return m
    return None

# --------------------------------------------------------------------------
# ADMINISTRATORS & AUTHENTICATION (SECURE SERVER-SIDE PASSWORD HASHING)
# --------------------------------------------------------------------------
def bootstrap_first_admin_if_empty():
    """Bootstraps the initial administrator if the admins collection is empty."""
    data = load_local_db()
    admins = data.get("admins", [])
    if not admins:
        default_email = os.getenv("ADMIN_EMAIL", "admin@hpl.cricket").strip().lower()
        default_pass = os.getenv("ADMIN_PASSWORD", "admin123")
        admin_obj = {
            "id": "A001",
            "name": "Tournament Admin",
            "email": default_email,
            "password_hash": generate_password_hash(default_pass),
            "role": "admin",
            "status": "active",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "last_login": None
        }
        admins.append(admin_obj)
        set_collection("admins", admins)
        print(f"[AUTH] Bootstrap initial administrator created: {default_email}")
        return admin_obj
    return None

def verify_admin_credentials(email, password):
    """Verifies email and password securely. Returns (True, admin_dict) or (False, error)."""
    email = (email or "").strip().lower()
    password = password or ""
    if not email or not password:
        return False, "Email and password are required"

    data = load_local_db()
    admins = data.get("admins", [])
    found = None
    for a in admins:
        if a.get("email", "").lower() == email:
            found = a
            break

    if not found:
        return False, "Invalid email or password"

    if found.get("status") != "active":
        return False, "Account is disabled. Contact system administrator."

    if not check_password_hash(found.get("password_hash", ""), password):
        return False, "Invalid email or password"

    # Update last_login
    found["last_login"] = time.strftime("%Y-%m-%d %H:%M:%S")
    set_collection("admins", admins)

    # Return safe admin dictionary without password_hash
    safe_admin = {
        "id": found["id"],
        "name": found["name"],
        "email": found["email"],
        "role": found.get("role", "admin"),
        "status": found.get("status", "active"),
        "last_login": found["last_login"]
    }
    return True, safe_admin

def get_all_admins():
    """Returns all administrators with password_hash strictly omitted."""
    data = load_local_db()
    admins = data.get("admins", [])
    safe_list = []
    for a in admins:
        safe_list.append({
            "id": a["id"],
            "name": a["name"],
            "email": a["email"],
            "role": a.get("role", "admin"),
            "status": a.get("status", "active"),
            "created_at": a.get("created_at"),
            "last_login": a.get("last_login")
        })
    return safe_list

def get_admin_by_id(admin_id):
    data = load_local_db()
    for a in data.get("admins", []):
        if a["id"] == admin_id:
            return {
                "id": a["id"],
                "name": a["name"],
                "email": a["email"],
                "role": a.get("role", "admin"),
                "status": a.get("status", "active")
            }
    return None

def create_admin(name, email, password, role="admin"):
    name = (name or "").strip()
    email = (email or "").strip().lower()
    password = password or ""

    if not name:
        return False, "Name cannot be empty"
    if not email or "@" not in email or "." not in email:
        return False, "Valid email address is required"
    if not password or len(password) < 6:
        return False, "Password must be at least 6 characters long"

    data = load_local_db()
    admins = data.get("admins", [])
    for a in admins:
        if a.get("email", "").lower() == email:
            return False, f"An administrator with email '{email}' already exists"

    admin_id = f"A{int(time.time() * 1000) % 10000:04d}"
    new_admin = {
        "id": admin_id,
        "name": name,
        "email": email,
        "password_hash": generate_password_hash(password),
        "role": role or "admin",
        "status": "active",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "last_login": None
    }
    admins.append(new_admin)
    set_collection("admins", admins)

    safe_admin = {
        "id": new_admin["id"],
        "name": new_admin["name"],
        "email": new_admin["email"],
        "role": new_admin["role"],
        "status": new_admin["status"]
    }
    return True, safe_admin

def update_admin_status(admin_id, new_status, current_admin_id=None):
    new_status = (new_status or "").strip().lower()
    if new_status not in ("active", "disabled"):
        return False, "Status must be 'active' or 'disabled'"

    data = load_local_db()
    admins = data.get("admins", [])
    found = None
    active_count = sum(1 for a in admins if a.get("status") == "active")

    for a in admins:
        if a["id"] == admin_id:
            found = a
            break

    if not found:
        return False, f"Admin {admin_id} not found"

    if new_status == "disabled" and found.get("status") == "active" and active_count <= 1:
        return False, "Cannot disable the only active administrator account"

    found["status"] = new_status
    found["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    set_collection("admins", admins)
    return True, f"Admin {found['name']} status changed to {new_status}"

def delete_admin(admin_id, current_admin_id=None):
    data = load_local_db()
    admins = data.get("admins", [])
    found = None
    active_count = sum(1 for a in admins if a.get("status") == "active")

    for a in admins:
        if a["id"] == admin_id:
            found = a
            break

    if not found:
        return False, f"Admin {admin_id} not found"

    if current_admin_id and admin_id == current_admin_id:
        return False, "Cannot delete your own active administrator account"

    if found.get("status") == "active" and active_count <= 1:
        return False, "Cannot delete the only active administrator account"

    admins = [a for a in admins if a["id"] != admin_id]
    set_collection("admins", admins)
    return True, f"Administrator {found['name']} deleted successfully"

def change_admin_password(admin_id, current_password, new_password):
    if not current_password or not new_password:
        return False, "Both current and new passwords are required"
    if len(new_password) < 6:
        return False, "New password must be at least 6 characters"

    data = load_local_db()
    admins = data.get("admins", [])
    found = None
    for a in admins:
        if a["id"] == admin_id:
            found = a
            break

    if not found:
        return False, "Administrator account not found"

    if not check_password_hash(found.get("password_hash", ""), current_password):
        return False, "Current password verification failed"

    found["password_hash"] = generate_password_hash(new_password)
    found["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    set_collection("admins", admins)
    return True, "Password updated successfully"

def update_admin_info(admin_id, name, email):
    name = (name or "").strip()
    email = (email or "").strip().lower()
    if not name:
        return False, "Name cannot be empty"
    if not email or "@" not in email or "." not in email:
        return False, "Valid email address is required"

    data = load_local_db()
    admins = data.get("admins", [])
    found = None
    for a in admins:
        if a["id"] == admin_id:
            found = a
            break

    if not found:
        return False, f"Admin {admin_id} not found"

    for a in admins:
        if a["id"] != admin_id and a.get("email", "").lower() == email:
            return False, f"Email '{email}' is already in use by another administrator"

    found["name"] = name
    found["email"] = email
    found["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    set_collection("admins", admins)
    return True, {
        "id": found["id"],
        "name": found["name"],
        "email": found["email"],
        "role": found.get("role", "admin"),
        "status": found.get("status", "active")
    }


import os
import time
import json
import queue
from datetime import timedelta
from functools import wraps
from flask import Flask, jsonify, request, send_from_directory, session, redirect, url_for, Response
from flask_cors import CORS
import cricket_db
from db import (
    get_all_data,
    get_collection,
    wipe_all_database,
    seed_database,
    create_team,
    update_team,
    delete_team,
    create_player,
    delete_player,
    schedule_match,
    start_match,
    record_ball,
    record_wicket,
    complete_match,
    recalculate_standings_internal,
    get_live_match,
    test_connection,
    bootstrap_first_admin_if_empty,
    verify_admin_credentials,
    get_all_admins,
    get_admin_by_id,
    create_admin,
    update_admin_status,
    update_admin_info,
    delete_admin,
    change_admin_password
)

app = Flask(__name__, static_folder=None)
app.secret_key = os.getenv("SECRET_KEY", "hpl_cricket_tournament_secure_session_key_2026_x891")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = False  # Set to True when using HTTPS in production

CORS(app, supports_credentials=True)

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))

# --------------------------------------------------------------------------
# REAL-TIME SERVER-SENT EVENTS (SSE) BROADCAST ENGINE
# --------------------------------------------------------------------------
_sse_subscribers = []

def broadcast_live_update(data=None):
    """Pushes the authoritative database state to all connected Home page clients."""
    if data is None:
        data = cricket_db.get_live_match_details()
    msg = f"data: {json.dumps({'type': 'live_score_update', 'match': data})}\n\n"
    dead = []
    for q in _sse_subscribers:
        try:
            q.put_nowait(msg)
        except Exception:
            dead.append(q)
    for q in dead:
        if q in _sse_subscribers:
            _sse_subscribers.remove(q)

def parse_match_id(m_id):
    if isinstance(m_id, int):
        return m_id
    s = str(m_id).strip()
    if s.upper().startswith("M"):
        digits = s[1:].lstrip("0")
        try:
            return int(digits) if digits else 1
        except ValueError:
            return s
    try:
        return int(s)
    except ValueError:
        return s


# --------------------------------------------------------------------------
# RATE LIMITING FOR LOGIN
# --------------------------------------------------------------------------
FAILED_ATTEMPTS = {}  # ip -> {"count": int, "blocked_until": float}
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION = 300  # 5 minutes

def is_ip_rate_limited(ip):
    now = time.time()
    record = FAILED_ATTEMPTS.get(ip)
    if not record:
        return False
    if record.get("blocked_until", 0) > now:
        return True
    if record.get("blocked_until", 0) <= now and record.get("count", 0) >= MAX_FAILED_ATTEMPTS:
        FAILED_ATTEMPTS.pop(ip, None)
    return False

def record_failed_attempt(ip):
    now = time.time()
    record = FAILED_ATTEMPTS.setdefault(ip, {"count": 0, "blocked_until": 0})
    record["count"] += 1
    if record["count"] >= MAX_FAILED_ATTEMPTS:
        record["blocked_until"] = now + LOCKOUT_DURATION

def clear_failed_attempts(ip):
    FAILED_ATTEMPTS.pop(ip, None)

# --------------------------------------------------------------------------
# AUTHENTICATION HELPERS & MIDDLEWARE
# --------------------------------------------------------------------------
def is_authenticated():
    admin_id = session.get("admin_id")
    if not admin_id:
        return False
    admin = get_admin_by_id(admin_id)
    if not admin or admin.get("status") != "active":
        session.clear()
        return False
    return True

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_authenticated():
            return jsonify({
                "success": False,
                "error": "Authentication required. Please sign in as an administrator."
            }), 401
        return f(*args, **kwargs)
    return decorated

# --------------------------------------------------------------------------
# HTML PAGES & ROUTE PROTECTION
# --------------------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(PROJECT_ROOT, "index.html")

@app.route("/admin/login", methods=["GET"])
def admin_login_page():
    if is_authenticated():
        return redirect("/admin")
    return send_from_directory(PROJECT_ROOT, "login.html")

@app.route("/admin", strict_slashes=False)
def admin_page():
    if not is_authenticated():
        return redirect("/admin/login")
    return send_from_directory(PROJECT_ROOT, "admin.html")

@app.route("/admin.html")
def admin_html_redirect():
    if not is_authenticated():
        return redirect("/admin/login")
    return send_from_directory(PROJECT_ROOT, "admin.html")

@app.route("/<path:filename>")
def static_files(filename):
    # Strictly block unauthenticated access to admin page or login source
    if filename in ("admin", "admin.html"):
        if not is_authenticated():
            return redirect("/admin/login")
        return send_from_directory(PROJECT_ROOT, "admin.html")
    if filename == "login.html":
        return redirect("/admin/login")
    return send_from_directory(PROJECT_ROOT, filename)

# --------------------------------------------------------------------------
# AUTHENTICATION API ENDPOINTS
# --------------------------------------------------------------------------
@app.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    ip = request.remote_addr or "127.0.0.1"
    if is_ip_rate_limited(ip):
        return jsonify({
            "success": False,
            "error": "Too many failed login attempts. Please wait 5 minutes before trying again."
        }), 429

    req = request.get_json(force=True, silent=True) or {}
    email = (req.get("email") or "").strip().lower()
    password = req.get("password") or ""

    ok, res = verify_admin_credentials(email, password)
    if not ok:
        record_failed_attempt(ip)
        # Generic login error message for security
        return jsonify({"success": False, "error": "Invalid email or password"}), 401

    clear_failed_attempts(ip)
    session.permanent = True
    session["admin_id"] = res["id"]
    session["admin_email"] = res["email"]
    session["admin_name"] = res["name"]
    session["admin_role"] = res.get("role", "admin")

    return jsonify({
        "success": True,
        "message": "Signed in successfully",
        "admin": res
    }), 200

@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    session.clear()
    return jsonify({"success": True, "message": "Signed out successfully"}), 200

@app.route("/api/auth/me", methods=["GET"])
def api_auth_me():
    if not is_authenticated():
        return jsonify({"success": True, "authenticated": False, "admin": None}), 200
    admin = get_admin_by_id(session["admin_id"])
    return jsonify({
        "success": True,
        "authenticated": True,
        "admin": admin
    }), 200

# --------------------------------------------------------------------------
# ADMINISTRATOR MANAGEMENT ENDPOINTS (PROTECTED)
# --------------------------------------------------------------------------
@app.route("/api/admins", methods=["GET"])
@require_auth
def api_get_admins():
    try:
        admins = get_all_admins()
        return jsonify({"success": True, "admins": admins}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admins", methods=["POST"])
@require_auth
def api_create_admin():
    try:
        req = request.get_json(force=True, silent=True) or {}
        name = req.get("name")
        email = req.get("email")
        password = req.get("password")
        role = req.get("role", "admin")

        ok, res = create_admin(name, email, password, role)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        return jsonify({"success": True, "admin": res}), 201
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admins/<admin_id>", methods=["PUT"])
@require_auth
def api_update_admin(admin_id):
    try:
        req = request.get_json(force=True, silent=True) or {}
        name = req.get("name")
        email = req.get("email")
        ok, res = update_admin_info(admin_id, name, email)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        if admin_id == session.get("admin_id"):
            session["admin_name"] = res["name"]
            session["admin_email"] = res["email"]
        return jsonify({"success": True, "admin": res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admins/<admin_id>/status", methods=["PUT"])
@require_auth
def api_update_admin_status(admin_id):
    try:
        req = request.get_json(force=True, silent=True) or {}
        status = req.get("status")
        current_admin = session.get("admin_id")
        ok, res = update_admin_status(admin_id, status, current_admin_id=current_admin)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        return jsonify({"success": True, "message": res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admins/<admin_id>", methods=["DELETE"])
@require_auth
def api_delete_admin(admin_id):
    try:
        current_admin = session.get("admin_id")
        ok, res = delete_admin(admin_id, current_admin_id=current_admin)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        return jsonify({"success": True, "message": res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/change-password", methods=["POST"])
@require_auth
def api_change_password():
    try:
        req = request.get_json(force=True, silent=True) or {}
        current_password = req.get("currentPassword")
        new_password = req.get("newPassword")
        current_admin = session.get("admin_id")

        ok, res = change_admin_password(current_admin, current_password, new_password)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        return jsonify({"success": True, "message": res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# --------------------------------------------------------------------------
# SYSTEM & TOURNAMENT STATE ENDPOINTS (PUBLIC READ-ONLY, PROTECTED WRITE)
# --------------------------------------------------------------------------
@app.route("/api/status", methods=["GET"])
def api_status():
    ok, msg = test_connection()
    return jsonify({
        "connected": ok,
        "database": "hpl_cricket_db",
        "message": msg
    }), 200

@app.route("/api/data", methods=["GET"])
def api_get_all_data():
    try:
        data, is_atlas = get_all_data()
        c_matches = cricket_db.get_all_matches()
        c_teams = cricket_db.get_all_teams()
        c_players = cricket_db.get_all_players()
        c_standings = cricket_db.recalculate_standings()

        # Strictly strip admins collection from public get_all_data response
        public_data = {
            "teams": c_teams if c_teams else data.get("teams", []),
            "players": c_players if c_players else data.get("players", []),
            "matches": c_matches if c_matches else data.get("matches", []),
            "standings": c_standings if c_standings else data.get("standings", []),
            "settings": data.get("settings", {})
        }
        return jsonify({
            "success": True,
            "data": public_data,
            "atlas_synced": is_atlas
        }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/wipe", methods=["POST"])
@require_auth
def api_wipe_database():
    try:
        ok, is_atlas = wipe_all_database()
        return jsonify({
            "success": True,
            "message": "All tournament data wiped clean from database.",
            "atlas_synced": is_atlas
        }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/seed", methods=["POST"])
@require_auth
def api_seed_database():
    try:
        ok, is_atlas = seed_database()
        return jsonify({
            "success": True,
            "message": "HPL tournament data seeded successfully.",
            "atlas_synced": is_atlas
        }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# --------------------------------------------------------------------------
# TEAMS ENDPOINTS (PUBLIC READ, PROTECTED WRITE)
# --------------------------------------------------------------------------
@app.route("/api/teams", methods=["GET"])
def api_get_teams():
    try:
        teams, is_atlas = get_collection("teams")
        return jsonify({"success": True, "teams": teams, "atlas_synced": is_atlas}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/teams", methods=["POST"])
@require_auth
def api_create_team():
    try:
        req = request.get_json(force=True, silent=True) or {}
        name = req.get("name")
        short = req.get("short")
        captain = req.get("captain")
        color = req.get("color")
        ok, res = create_team(name, short, captain, color)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        return jsonify({"success": True, "team": res}), 201
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/teams/<team_id>", methods=["PUT"])
@require_auth
def api_update_team(team_id):
    try:
        req = request.get_json(force=True, silent=True) or {}
        name = req.get("name")
        short = req.get("short")
        captain = req.get("captain")
        color = req.get("color")
        ok, res = update_team(team_id, name, short, captain, color)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        return jsonify({"success": True, "team": res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/teams/<team_id>", methods=["DELETE"])
@require_auth
def api_delete_team(team_id):
    try:
        ok, res = delete_team(team_id)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        return jsonify({"success": True, "message": res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# --------------------------------------------------------------------------
# PLAYERS ENDPOINTS (PUBLIC READ, PROTECTED WRITE)
# --------------------------------------------------------------------------
@app.route("/api/players", methods=["GET"])
def api_get_players():
    try:
        players, is_atlas = get_collection("players")
        return jsonify({"success": True, "players": players, "atlas_synced": is_atlas}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/players", methods=["POST"])
@require_auth
def api_create_player():
    try:
        req = request.get_json(force=True, silent=True) or {}
        name = req.get("name")
        team = req.get("team")
        role = req.get("role")
        jersey = req.get("jersey")
        ok, res = create_player(name, team, role, jersey)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        return jsonify({"success": True, "player": res}), 201
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/players/<player_id>", methods=["DELETE"])
@require_auth
def api_delete_player(player_id):
    try:
        ok, res = delete_player(player_id)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        return jsonify({"success": True, "message": res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# --------------------------------------------------------------------------
# MATCHES & AUTHORITATIVE LIVE SCORING (ADMIN & PUBLIC APIS)
# --------------------------------------------------------------------------

# --- 1. PUBLIC READ-ONLY APIS ---

@app.route("/api/matches", methods=["GET"])
def api_get_matches():
    """Public read-only: Lists all matches from the authoritative database."""
    try:
        matches = cricket_db.get_all_matches()
        return jsonify({"success": True, "matches": matches}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/matches/live", methods=["GET"])
def api_live_match():
    """Public read-only: Returns the authoritative current live match details."""
    try:
        live = cricket_db.get_live_match_details()
        if live:
            return jsonify({"success": True, "live": True, "match": live}), 200
        return jsonify({"success": True, "live": False, "match": None}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/matches/<match_id>", methods=["GET"])
def api_get_match_by_id(match_id):
    """Public read-only: Returns details for a specific match."""
    try:
        mid = parse_match_id(match_id)
        m = cricket_db.get_match_by_id(mid)
        if not m:
            return jsonify({"success": False, "error": f"Match {match_id} not found"}), 404
        return jsonify({"success": True, "match": m}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/matches/<match_id>/scorecard", methods=["GET"])
def api_get_match_scorecard(match_id):
    """Public read-only: Returns full scorecard (both innings, batting, bowling, fall of wickets)."""
    try:
        mid = parse_match_id(match_id)
        sc = cricket_db.get_match_full_scorecard(mid)
        if not sc:
            return jsonify({"success": False, "error": f"Scorecard for match {match_id} not found"}), 404
        return jsonify({"success": True, "scorecard": sc}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/matches/live/stream", methods=["GET"])
def api_live_stream():
    """Real-time Server-Sent Events (SSE) stream for zero-refresh live scorecard updates."""
    def event_stream():
        client_queue = queue.Queue()
        _sse_subscribers.append(client_queue)
        # Immediately push initial live state
        initial_match = cricket_db.get_live_match_details()
        yield f"data: {json.dumps({'type': 'init', 'match': initial_match})}\n\n"
        try:
            while True:
                try:
                    # Timeout after 15s to emit keepalive ping
                    msg = client_queue.get(timeout=15)
                    yield msg
                except queue.Empty:
                    yield ": keepalive\n\n"
        except GeneratorExit:
            if client_queue in _sse_subscribers:
                _sse_subscribers.remove(client_queue)

    return Response(event_stream(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive"
    })

# --- 2. ADMIN MATCH MANAGEMENT APIS (PROTECTED) ---

@app.route("/api/admin/matches", methods=["GET"])
@require_auth
def api_admin_get_matches():
    try:
        matches = cricket_db.get_all_matches()
        return jsonify({"success": True, "matches": matches}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/matches", methods=["POST"])
@app.route("/api/matches", methods=["POST"])
@require_auth
def api_admin_create_match():
    try:
        req = request.get_json(force=True, silent=True) or {}
        team_a = req.get("team_a") or req.get("teamA")
        team_b = req.get("team_b") or req.get("teamB")
        venue = req.get("venue") or "College Ground"
        match_date = req.get("match_date") or req.get("date") or "Today"
        total_overs = req.get("total_overs") or req.get("overs") or 10
        match_name = req.get("match_name") or f"{team_a} vs {team_b}"

        ok, res = cricket_db.create_match(team_a, team_b, venue, match_date, total_overs, match_name)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        
        broadcast_live_update()
        return jsonify({"success": True, "match": res}), 201
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/matches/<match_id>", methods=["GET"])
@require_auth
def api_admin_get_match(match_id):
    try:
        mid = parse_match_id(match_id)
        m = cricket_db.get_match_by_id(mid)
        if not m:
            return jsonify({"success": False, "error": f"Match {match_id} not found"}), 404
        return jsonify({"success": True, "match": m}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/matches/<match_id>", methods=["PUT"])
@require_auth
def api_admin_update_match(match_id):
    try:
        mid = parse_match_id(match_id)
        req = request.get_json(force=True, silent=True) or {}
        team_a = req.get("team_a") or req.get("teamA")
        team_b = req.get("team_b") or req.get("teamB")
        venue = req.get("venue")
        match_date = req.get("match_date") or req.get("date")
        total_overs = req.get("total_overs") or req.get("overs")
        status = req.get("status")

        ok, res = cricket_db.update_match(mid, team_a, team_b, venue, match_date, total_overs, status)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        
        broadcast_live_update()
        return jsonify({"success": True, "match": res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/matches/<match_id>", methods=["DELETE"])
@require_auth
def api_admin_delete_match(match_id):
    try:
        mid = parse_match_id(match_id)
        ok, res = cricket_db.delete_match(mid)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        
        broadcast_live_update()
        return jsonify({"success": True, "message": res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/matches/<match_id>/start", methods=["POST"])
@app.route("/api/matches/<match_id>/start", methods=["POST"])
@require_auth
def api_admin_start_match(match_id):
    try:
        mid = parse_match_id(match_id)
        ok, res = cricket_db.start_match(mid)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        
        broadcast_live_update(res)
        return jsonify({"success": True, "match": res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/matches/<match_id>/pause", methods=["POST"])
@require_auth
def api_admin_pause_match(match_id):
    try:
        mid = parse_match_id(match_id)
        ok, res = cricket_db.pause_match(mid)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        
        broadcast_live_update()
        return jsonify({"success": True, "match": res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/matches/<match_id>/complete", methods=["POST"])
@app.route("/api/matches/<match_id>/complete", methods=["POST"])
@require_auth
def api_admin_complete_match(match_id):
    try:
        mid = parse_match_id(match_id)
        req = request.get_json(force=True, silent=True) or {}
        winner = req.get("winner")
        margin = req.get("margin") or req.get("result_margin", "")
        ok, res = cricket_db.complete_match(mid, winner, margin)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        
        broadcast_live_update()
        return jsonify({"success": True, "match": res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# --- 3. ADMIN SCORING APIS (PROTECTED) ---

@app.route("/api/admin/matches/<match_id>/ball", methods=["POST"])
@app.route("/api/matches/<match_id>/ball", methods=["POST"])
@require_auth
def api_admin_record_ball(match_id):
    try:
        mid = parse_match_id(match_id)
        req = request.get_json(force=True, silent=True) or {}
        runs = req.get("runs", 0)
        extra = req.get("extra")
        batsman_name = req.get("batsman_name")
        bowler_name = req.get("bowler_name")

        ok, res = cricket_db.record_ball(mid, runs=runs, extra=extra, batsman_name=batsman_name, bowler_name=bowler_name)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        
        broadcast_live_update(res)
        return jsonify({"success": True, "match": res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/matches/<match_id>/wicket", methods=["POST"])
@app.route("/api/matches/<match_id>/wicket", methods=["POST"])
@require_auth
def api_admin_record_wicket(match_id):
    try:
        mid = parse_match_id(match_id)
        req = request.get_json(force=True, silent=True) or {}
        new_batter = req.get("newBatter") or req.get("new_batter") or "Next Batter"
        wicket_type = req.get("wicket_type") or req.get("type") or "BOWLED"
        out_batter = req.get("out_batter")
        bowler_name = req.get("bowler_name")

        ok, res = cricket_db.record_wicket(mid, new_batter_name=new_batter, wicket_type=wicket_type, out_batter_name=out_batter, bowler_name=bowler_name)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        
        broadcast_live_update(res)
        return jsonify({"success": True, "match": res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/matches/<match_id>/undo", methods=["POST"])
@require_auth
def api_admin_undo_ball(match_id):
    try:
        mid = parse_match_id(match_id)
        ok, res = cricket_db.undo_last_ball(mid)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        
        broadcast_live_update(res)
        return jsonify({"success": True, "match": res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/matches/<match_id>/score", methods=["POST", "PUT"])
@require_auth
def api_admin_set_score(match_id):
    try:
        mid = parse_match_id(match_id)
        req = request.get_json(force=True, silent=True) or {}
        runs = req.get("runs", 0)
        wickets = req.get("wickets", 0)
        overs = req.get("overs", "0.0")

        ok, res = cricket_db.set_live_score(mid, runs, wickets, overs)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        
        broadcast_live_update(res)
        return jsonify({"success": True, "match": res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/matches/<match_id>/innings/switch", methods=["POST"])
@require_auth
def api_admin_switch_innings(match_id):
    try:
        mid = parse_match_id(match_id)
        ok, res = cricket_db.switch_to_second_innings(mid)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        
        broadcast_live_update(res)
        return jsonify({"success": True, "match": res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# --------------------------------------------------------------------------
# STANDINGS (PUBLIC READ, PROTECTED RECALC)
# --------------------------------------------------------------------------
@app.route("/api/standings", methods=["GET"])
def api_get_standings():
    try:
        standings, is_atlas = get_collection("standings")
        if not standings:
            standings = cricket_db.recalculate_standings()
        return jsonify({"success": True, "standings": standings, "atlas_synced": is_atlas}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/standings/recalculate", methods=["POST"])
@require_auth
def api_recalc_standings():
    try:
        standings = recalculate_standings_internal()
        return jsonify({"success": True, "standings": standings}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/stats", methods=["GET"])
def api_stats():
    try:
        standings, is_atlas = get_collection("standings")
        matches, _ = get_collection("matches")
        completed = [m for m in matches if m.get("status") == "COMPLETED"]
        leader = standings[0]["team"] if standings else "N/A"
        leader_pts = standings[0].get("pts", 0) if standings else 0
        return jsonify({
            "success": True,
            "matches": len(completed),
            "houses": len(standings),
            "leader": leader,
            "leader_pts": leader_pts,
            "db_connected": is_atlas
        }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# --------------------------------------------------------------------------
# SERVER INITIALIZATION
# --------------------------------------------------------------------------
if __name__ == "__main__":
    # Ensure bootstrap admin exists
    bootstrapped = bootstrap_first_admin_if_empty()
    if bootstrapped:
        print(f"[AUTH] Initial administrator ready: {bootstrapped['email']}")

    ok, msg = test_connection()
    print(f"MongoDB Atlas connection: {'SUCCESS' if ok else 'OFFLINE'} - {msg}")
    print("Starting HPL Production Server on http://localhost:8080 ...")
    app.run(host="0.0.0.0", port=8080, debug=False)

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
app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "false").lower() in ("true", "1", "yes")

# Ensure bootstrap admin exists across any WSGI runner (Gunicorn, Waitress, etc.)
bootstrap_first_admin_if_empty()

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

@app.route("/match/<int:match_id>")
@app.route("/match/<int:match_id>/scorecard")
@app.route("/match/<int:match_id>/commentary")
@app.route("/match/<int:match_id>/overs")
@app.route("/match/<int:match_id>/info")
def match_center_page(match_id):
    """Serves the Match Center SPA for any match sub-route."""
    return send_from_directory(PROJECT_ROOT, "match.html")

@app.route("/team/<path:team_id>")
def team_page(team_id):
    """Serves the dedicated Team profile page."""
    return send_from_directory(PROJECT_ROOT, "team.html")

@app.route("/player/<path:player_id>")
def player_page(player_id):
    """Serves the dedicated Player profile page."""
    return send_from_directory(PROJECT_ROOT, "player.html")

@app.route("/api/health", methods=["GET"])
def api_health():
    """Production health check endpoint."""
    return jsonify({
        "success": True,
        "status": "healthy",
        "service": "hpl-cricket-platform"
    }), 200

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
    """Public read-only: Lists all matches, optionally filtered by league_id, status, date, team."""
    try:
        league_id = request.args.get("league_id")
        status = request.args.get("status")
        date = request.args.get("date")
        team = request.args.get("team")
        matches = cricket_db.get_all_matches(league_id=league_id, status=status, date=date, team=team)
        return jsonify({"success": True, "matches": matches}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/matches/live", methods=["GET"])
def api_live_match():
    """Public read-only: Returns the authoritative current live match details."""
    try:
        league_id = request.args.get("league_id")
        live = cricket_db.get_live_match_details(league_id=league_id)
        if live:
            return jsonify({"success": True, "live": True, "match": live}), 200
        return jsonify({"success": True, "live": False, "match": None}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/matches/upcoming", methods=["GET"])
def api_upcoming_matches():
    """Public read-only: Returns all UPCOMING matches."""
    try:
        league_id = request.args.get("league_id")
        matches = cricket_db.get_all_matches(league_id=league_id, status="UPCOMING")
        return jsonify({"success": True, "matches": matches}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/matches/completed", methods=["GET"])
def api_completed_matches():
    """Public read-only: Returns all COMPLETED matches."""
    try:
        league_id = request.args.get("league_id")
        matches = cricket_db.get_all_matches(league_id=league_id, status="COMPLETED")
        return jsonify({"success": True, "matches": matches}), 200
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

@app.route("/api/matches/<match_id>/commentary", methods=["GET"])
def api_get_match_commentary(match_id):
    """Public: Returns ball-by-ball commentary for a match."""
    try:
        mid = parse_match_id(match_id)
        data = cricket_db.get_match_commentary(mid)
        if data is None:
            return jsonify({"success": False, "error": f"Match {match_id} not found"}), 404
        return jsonify({"success": True, "commentary": data}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/matches/<match_id>/overs", methods=["GET"])
def api_get_match_overs(match_id):
    """Public: Returns over-by-over breakdown for a match."""
    try:
        mid = parse_match_id(match_id)
        data = cricket_db.get_match_overs(mid)
        if data is None:
            return jsonify({"success": False, "error": f"Match {match_id} not found"}), 404
        return jsonify({"success": True, "overs": data}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/matches/<match_id>/info", methods=["GET"])
def api_get_match_info(match_id):
    """Public: Returns match metadata for the Info tab."""
    try:
        mid = parse_match_id(match_id)
        data = cricket_db.get_match_info(mid)
        if data is None:
            return jsonify({"success": False, "error": f"Match {match_id} not found"}), 404
        return jsonify({"success": True, "info": data}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/matches/<match_id>/stream", methods=["GET"])
def api_match_stream(match_id):
    """Per-match SSE stream — pushes live updates whenever this specific match changes."""
    mid = parse_match_id(match_id)
    def event_stream():
        client_queue = queue.Queue()
        _sse_subscribers.append(client_queue)
        # Immediately push current match state
        initial = cricket_db.get_match_full_scorecard(mid)
        live = cricket_db.get_live_match_details(mid)
        payload = {"type": "init", "scorecard": initial, "live": live}
        yield f"data: {json.dumps(payload)}\n\n"
        try:
            while True:
                try:
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
        league_id = request.args.get("league_id")
        status = request.args.get("status")
        date = request.args.get("date")
        team = request.args.get("team")
        matches = cricket_db.get_all_matches(league_id=league_id, status=status, date=date, team=team)
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
        
        raw_overs = req.get("total_overs") if "total_overs" in req else req.get("overs")
        total_overs = 10 if raw_overs is None else raw_overs
        
        format_name = req.get("format_name") or req.get("format") or ("T6" if total_overs == 6 else ("T10" if total_overs == 10 else f"T{total_overs}"))
        players_per_team = req.get("players_per_team") or (8 if (total_overs == 6 or str(format_name).upper() == "T6") else 11)
        balls_per_over = req.get("balls_per_over") or 6

        match_name = req.get("match_name") or f"{team_a} vs {team_b}"
        league_id = req.get("league_id") or req.get("league") or 1

        ok, res = cricket_db.create_match(
            team_a, team_b, venue, match_date, total_overs, match_name, 
            league_id=league_id, format_name=format_name, 
            players_per_team=players_per_team, balls_per_over=balls_per_over
        )
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
        format_name = req.get("format_name") or req.get("format")
        players_per_team = req.get("players_per_team")
        balls_per_over = req.get("balls_per_over")
        status = req.get("status")
        league_id = req.get("league_id")

        ok, res = cricket_db.update_match(
            mid, team_a, team_b, venue, match_date, total_overs, status, 
            league_id=league_id, format_name=format_name, 
            players_per_team=players_per_team, balls_per_over=balls_per_over
        )
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        
        broadcast_live_update()
        return jsonify({"success": True, "match": res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/matches/<match_id>/setup", methods=["GET"])
@app.route("/api/admin/matches/<match_id>/setup", methods=["GET"])
def api_get_match_setup(match_id):
    try:
        mid = parse_match_id(match_id)
        m = cricket_db.get_match_by_id(mid)
        if not m:
            return jsonify({"success": False, "error": f"Match {match_id} not found"}), 404

        squad_a = cricket_db.get_players_by_team(m["team_a"])
        squad_b = cricket_db.get_players_by_team(m["team_b"])

        return jsonify({
            "success": True,
            "match_id": mid,
            "match_name": m["match_name"],
            "team_a": m["team_a"],
            "team_b": m["team_b"],
            "format_name": m["format_name"],
            "total_overs": m["total_overs"],
            "players_per_team": m["players_per_team"],
            "balls_per_over": m["balls_per_over"],
            "squad_a": squad_a,
            "squad_b": squad_b,
            "playing_xi_a": m["playing_xi_a"],
            "playing_xi_b": m["playing_xi_b"],
            "captain_a": m["captain_a"],
            "captain_b": m["captain_b"],
            "wicketkeeper_a": m["wicketkeeper_a"],
            "wicketkeeper_b": m["wicketkeeper_b"],
            "toss_winner": m["toss_winner"],
            "toss_decision": m["toss_decision"]
        }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/matches/<match_id>/setup", methods=["POST"])
@require_auth
def api_admin_save_match_setup(match_id):
    try:
        mid = parse_match_id(match_id)
        req = request.get_json(force=True, silent=True) or {}
        
        playing_xi_a = req.get("playing_xi_a") or req.get("playing_xi_A") or []
        playing_xi_b = req.get("playing_xi_b") or req.get("playing_xi_B") or []
        captain_a = req.get("captain_a") or req.get("captain_A")
        captain_b = req.get("captain_b") or req.get("captain_B")
        wicketkeeper_a = req.get("wicketkeeper_a") or req.get("wicketkeeper_A")
        wicketkeeper_b = req.get("wicketkeeper_b") or req.get("wicketkeeper_B")
        toss_winner = req.get("toss_winner")
        toss_decision = req.get("toss_decision")

        ok, res = cricket_db.save_match_setup(
            mid, playing_xi_a, playing_xi_b, captain_a, captain_b,
            wicketkeeper_a=wicketkeeper_a, wicketkeeper_b=wicketkeeper_b,
            toss_winner=toss_winner, toss_decision=toss_decision
        )
        if not ok:
            return jsonify({"success": False, "error": res}), 400

        broadcast_live_update()
        return jsonify({"success": True, "match": res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/matches/<match_id>/playing-xi", methods=["GET"])
def api_get_match_playing_xi(match_id):
    try:
        mid = parse_match_id(match_id)
        m = cricket_db.get_match_by_id(mid)
        if not m:
            return jsonify({"success": False, "error": f"Match {match_id} not found"}), 404

        return jsonify({
            "success": True,
            "match_id": mid,
            "format_name": m["format_name"],
            "total_overs": m["total_overs"],
            "required_players": m["players_per_team"],
            "team_a": {
                "name": m["team_a"],
                "playing_xi": m["playing_xi_a"],
                "captain": m["captain_a"],
                "wicketkeeper": m["wicketkeeper_a"]
            },
            "team_b": {
                "name": m["team_b"],
                "playing_xi": m["playing_xi_b"],
                "captain": m["captain_b"],
                "wicketkeeper": m["wicketkeeper_b"]
            },
            "toss": {
                "winner": m["toss_winner"],
                "decision": m["toss_decision"],
                "text": f"{m['toss_winner']} won the toss and elected to {m['toss_decision'].lower()}." if m["toss_winner"] and m["toss_decision"] else "Toss yet to take place"
            }
        }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/matches/<match_id>/players-for-scoring", methods=["GET"])
@require_auth
def api_get_players_for_scoring(match_id):
    try:
        mid = parse_match_id(match_id)
        innings_id = request.args.get("innings_id", type=int)
        data = cricket_db.get_match_players_for_scoring(mid, innings_id=innings_id)
        return jsonify({"success": True, **data}), 200
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
        fielder_name = req.get("fielder_name") or req.get("fielder")

        ok, res = cricket_db.record_wicket(
            mid, new_batter_name=new_batter, wicket_type=wicket_type,
            out_batter_name=out_batter, bowler_name=bowler_name, fielder_name=fielder_name
        )
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        
        broadcast_live_update(res)
        return jsonify({"success": True, "match": res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/matches/<match_id>/undo", methods=["POST"])
@app.route("/api/matches/<match_id>/undo", methods=["POST"])
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
@app.route("/api/matches/<match_id>/score", methods=["POST", "PUT"])
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
@app.route("/api/matches/<match_id>/innings/switch", methods=["POST"])
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

@app.route("/api/admin/matches/<match_id>/resume", methods=["POST"])
@require_auth
def api_admin_resume_match(match_id):
    try:
        mid = parse_match_id(match_id)
        ok, res = cricket_db.resume_match(mid)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        
        broadcast_live_update(res)
        return jsonify({"success": True, "match": res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/matches/<match_id>/edit-last-ball", methods=["POST"])
@require_auth
def api_admin_edit_last_ball(match_id):
    try:
        mid = parse_match_id(match_id)
        req = request.get_json(force=True, silent=True) or {}
        runs = req.get("runs", 0)
        extra_type = req.get("extra_type") or req.get("extra")
        wicket = req.get("wicket", 0)
        wicket_type = req.get("wicket_type")
        batsman_name = req.get("batsman_name")
        bowler_name = req.get("bowler_name")
        commentary = req.get("commentary")

        ok, res = cricket_db.edit_last_ball(
            mid, runs=runs, extra_type=extra_type, wicket=wicket,
            wicket_type=wicket_type, batsman_name=batsman_name,
            bowler_name=bowler_name, commentary=commentary
        )
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        
        broadcast_live_update(res)
        return jsonify({"success": True, "match": res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/matches/<match_id>/swap-strike", methods=["POST"])
@require_auth
def api_admin_swap_strike(match_id):
    try:
        mid = parse_match_id(match_id)
        ok, res = cricket_db.swap_strike(mid)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        
        broadcast_live_update(res)
        return jsonify({"success": True, "match": res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/matches/<match_id>/set-striker", methods=["POST"])
@require_auth
def api_admin_set_striker(match_id):
    try:
        mid = parse_match_id(match_id)
        req = request.get_json(force=True, silent=True) or {}
        player_name = req.get("player_name") or req.get("name")
        if not player_name:
            return jsonify({"success": False, "error": "player_name is required"}), 400
        ok, res = cricket_db.set_current_striker(mid, player_name)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        
        broadcast_live_update(res)
        return jsonify({"success": True, "match": res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/matches/<match_id>/set-bowler", methods=["POST"])
@require_auth
def api_admin_set_bowler(match_id):
    try:
        mid = parse_match_id(match_id)
        req = request.get_json(force=True, silent=True) or {}
        player_name = req.get("player_name") or req.get("name")
        if not player_name:
            return jsonify({"success": False, "error": "player_name is required"}), 400
        ok, res = cricket_db.set_current_bowler(mid, player_name)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        
        broadcast_live_update(res)
        return jsonify({"success": True, "match": res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# --------------------------------------------------------------------------
# LEAGUES API ENDPOINTS (ISOLATED TOURNAMENT DIVISIONS)
# --------------------------------------------------------------------------
@app.route("/api/leagues", methods=["GET"])
def api_get_leagues():
    try:
        leagues = cricket_db.get_all_leagues()
        return jsonify({"success": True, "leagues": leagues}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/leagues/<int:league_id>", methods=["GET"])
def api_get_league(league_id):
    try:
        league = cricket_db.get_league_by_id(league_id)
        if not league:
            return jsonify({"success": False, "error": f"League {league_id} not found"}), 404
        return jsonify({"success": True, "league": league}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/leagues", methods=["POST"])
@require_auth
def api_create_league():
    try:
        req = request.get_json(force=True, silent=True) or {}
        name = req.get("name")
        short_name = req.get("short_name")
        description = req.get("description", "")
        status = req.get("status", "active")
        ok, res = cricket_db.create_league(name, short_name, description, status)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        return jsonify({"success": True, "league": res}), 201
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/leagues/<int:league_id>", methods=["PUT"])
@require_auth
def api_update_league(league_id):
    try:
        req = request.get_json(force=True, silent=True) or {}
        name = req.get("name")
        short_name = req.get("short_name")
        description = req.get("description")
        status = req.get("status")
        ok, res = cricket_db.update_league(league_id, name=name, short_name=short_name, description=description, status=status)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        return jsonify({"success": True, "league": res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/leagues/<int:league_id>", methods=["DELETE"])
@require_auth
def api_delete_league(league_id):
    try:
        ok, res = cricket_db.delete_league(league_id)
        if not ok:
            return jsonify({"success": False, "error": res}), 400
        return jsonify({"success": True, "message": res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/leagues/<int:league_id>/matches", methods=["GET"])
def api_get_league_matches(league_id):
    try:
        status = request.args.get("status")
        matches = cricket_db.get_league_matches(league_id, status=status)
        return jsonify({"success": True, "league_id": league_id, "matches": matches}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/leagues/<int:league_id>/points-table", methods=["GET"])
def api_get_league_points_table(league_id):
    try:
        standings = cricket_db.recalculate_standings(league_id)
        return jsonify({"success": True, "league_id": league_id, "standings": standings}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/leagues/<int:league_id>/overview", methods=["GET"])
def api_get_league_overview(league_id):
    try:
        overview = cricket_db.get_league_overview(league_id)
        if not overview:
            return jsonify({"success": False, "error": f"League {league_id} not found"}), 404
        return jsonify({"success": True, "overview": overview}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/leagues/<int:league_id>/teams/<path:team_name>", methods=["GET"])
def api_get_league_team(league_id, team_name):
    try:
        details = cricket_db.get_league_team_details(league_id, team_name)
        return jsonify({"success": True, "team_details": details}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# --------------------------------------------------------------------------
# STANDINGS (PUBLIC READ, PROTECTED RECALC)
# --------------------------------------------------------------------------
@app.route("/api/standings", methods=["GET"])
def api_get_standings():
    try:
        league_id = request.args.get("league_id")
        if league_id is not None:
            standings = cricket_db.recalculate_standings(int(league_id))
            return jsonify({"success": True, "league_id": int(league_id), "standings": standings}), 200
        standings, is_atlas = get_collection("standings")
        if not standings:
            standings = cricket_db.recalculate_standings(1)
        return jsonify({"success": True, "standings": standings, "atlas_synced": is_atlas}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/standings/recalculate", methods=["POST"])
@require_auth
def api_recalc_standings():
    try:
        req = request.get_json(force=True, silent=True) or {}
        league_id = req.get("league_id")
        standings = recalculate_standings_internal(league_id)
        return jsonify({"success": True, "standings": standings}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/teams/<path:team_name_or_id>", methods=["GET"])
def api_get_team_profile(team_name_or_id):
    try:
        league_id = request.args.get("league_id", 1)
        details = cricket_db.get_league_team_details(int(league_id), team_name_or_id)
        return jsonify({"success": True, "team_details": details}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/players/<path:player_name_or_id>", methods=["GET"])
def api_get_player_profile(player_name_or_id):
    try:
        profile = cricket_db.get_player_profile(player_name_or_id)
        return jsonify({"success": True, "player": profile}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/leaderboards", methods=["GET"])
def api_leaderboards():
    try:
        league_id = request.args.get("league_id")
        lid = int(league_id) if league_id and str(league_id).isdigit() else None
        data = cricket_db.get_tournament_leaderboards(lid)
        return jsonify({"success": True, "leaderboards": data}), 200
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
# STATIC ASSETS SERVING
# --------------------------------------------------------------------------
@app.route("/css/<path:filename>")
def serve_css(filename):
    return send_from_directory(os.path.join(PROJECT_ROOT, "css"), filename)

@app.route("/js/<path:filename>")
def serve_js(filename):
    return send_from_directory(os.path.join(PROJECT_ROOT, "js"), filename)

@app.route("/images/<path:filename>")
def serve_images(filename):
    return send_from_directory(os.path.join(PROJECT_ROOT, "images"), filename)

@app.route("/font/<path:filename>")
def serve_fonts(filename):
    return send_from_directory(os.path.join(PROJECT_ROOT, "font"), filename)

@app.route("/favicon.ico")
@app.route("/favicon.png")
def serve_favicon():
    fav_path = os.path.join(PROJECT_ROOT, "images", "favicon.png")
    if os.path.exists(fav_path):
        return send_from_directory(os.path.join(PROJECT_ROOT, "images"), "favicon.png")
    return send_from_directory(PROJECT_ROOT, "favicon.png")

# --------------------------------------------------------------------------
# PRODUCTION ERROR HANDLERS
# --------------------------------------------------------------------------
@app.errorhandler(404)
def handle_404(e):
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "error": "Endpoint not found"}), 404
    return send_from_directory(PROJECT_ROOT, "index.html"), 404

@app.errorhandler(500)
def handle_500(e):
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "error": "Internal server error"}), 500
    return jsonify({"success": False, "error": "An unexpected error occurred"}), 500

# --------------------------------------------------------------------------
# SERVER INITIALIZATION
# --------------------------------------------------------------------------
if __name__ == "__main__":
    # Ensure bootstrap admin exists
    bootstrapped = bootstrap_first_admin_if_empty()
    if bootstrapped:
        print(f"[AUTH] Initial administrator ready: {bootstrapped['email']}")

    ok, msg = test_connection()
    port = int(os.getenv("PORT", 8080))
    print(f"MongoDB Atlas connection: {'SUCCESS' if ok else 'OFFLINE'} - {msg}")
    print(f"Starting HPL Production Server on port {port} ...")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)

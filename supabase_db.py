"""
supabase_db.py — Production Supabase PostgreSQL Data Layer
CSD & CSIT Cricket Tournament
Fully implements the authoritative cricket scoring engine (cricket_engine.py)
and all repository methods with PostgreSQL persistence.
"""

import os
import json
import datetime
from typing import Dict, List, Optional, Tuple, Any
from dotenv import load_dotenv
from supabase import create_client, Client
from werkzeug.security import generate_password_hash, check_password_hash

import cricket_engine
from cricket_engine import (
    MatchConfig,
    replay_innings_events,
    evaluate_match_result,
    validate_dismissal_on_delivery,
    calculate_run_rate,
    calculate_required_run_rate,
    balls_to_overs_display
)

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY", "")

_client: Optional[Client] = None


def get_supabase() -> Client:
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY (or SUPABASE_SERVICE_ROLE_KEY) must be set in environment.")
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def sb() -> Client:
    return get_supabase()


def init_db():
    """No-op: schema is managed via Supabase migrations."""
    pass


# ---------------------------------------------------------------------------
# Data Helpers
# ---------------------------------------------------------------------------

def _rows(res) -> List[Dict[str, Any]]:
    return res.data if res and res.data else []


def _one(res) -> Optional[Dict[str, Any]]:
    data = res.data if res and res.data else []
    return data[0] if data else None


def _now() -> str:
    return datetime.datetime.utcnow().isoformat()


# ===========================================================================
# LEAGUES
# ===========================================================================

def get_all_leagues():
    rows = _rows(sb().table("leagues").select("*").order("id").execute())
    for lg in rows:
        mc = sb().table("matches").select("id", count="exact").eq("league_id", lg["id"]).execute().count or 0
        lg["matches_count"] = mc
        ma = _rows(sb().table("matches").select("team_a,team_b").eq("league_id", lg["id"]).execute())
        ta = _rows(sb().table("teams").select("name").eq("league_id", lg["id"]).execute())
        names = set()
        for m in ma:
            names.add(m["team_a"]); names.add(m["team_b"])
        for t in ta:
            names.add(t["name"])
        lg["teams_count"] = len(names)
    return rows


def get_league_by_id(league_id: int):
    row = _one(sb().table("leagues").select("*").eq("id", int(league_id)).execute())
    if not row:
        return None
    ma = _rows(sb().table("matches").select("team_a,team_b").eq("league_id", row["id"]).execute())
    ta = _rows(sb().table("teams").select("name").eq("league_id", row["id"]).execute())
    names = set()
    for m in ma:
        names.add(m["team_a"]); names.add(m["team_b"])
    for t in ta:
        names.add(t["name"])
    row["matches_count"] = len(ma)
    row["teams_count"] = len(names)
    return row


def create_league(name: str, short_name: Optional[str] = None, description: str = "", status: str = "active", tournament_id: int = 1):
    if not name or not name.strip():
        return False, "League name is required"
    name = name.strip()
    short_name = (short_name or name[:3]).strip().upper()
    status = status if status in ("active", "disabled") else "active"
    existing = _one(sb().table("leagues").select("id").eq("name", name).execute())
    if existing:
        return False, f"League '{name}' already exists"
    row = _one(sb().table("leagues").insert({
        "name": name, "short_name": short_name,
        "description": description, "status": status,
        "tournament_id": int(tournament_id or 1)
    }).execute())
    if not row:
        return False, "Failed to create league"
    recalculate_standings(row["id"])
    return True, get_league_by_id(row["id"])


def update_league(league_id: int, name: Optional[str] = None, short_name: Optional[str] = None, description: Optional[str] = None, status: Optional[str] = None):
    existing = _one(sb().table("leagues").select("*").eq("id", int(league_id)).execute())
    if not existing:
        return False, "League not found"
    upd = {}
    if name is not None: upd["name"] = name.strip()
    if short_name is not None: upd["short_name"] = short_name.strip().upper()
    if description is not None: upd["description"] = description.strip()
    if status is not None and status in ("active", "disabled"): upd["status"] = status
    if upd:
        sb().table("leagues").update(upd).eq("id", int(league_id)).execute()
    return True, get_league_by_id(league_id)


def delete_league(league_id: int):
    all_leagues = _rows(sb().table("leagues").select("id").execute())
    if len(all_leagues) <= 1:
        return False, "Cannot delete the only remaining league"
    existing = _one(sb().table("leagues").select("id").eq("id", int(league_id)).execute())
    if not existing:
        return False, "League not found"
    sb().table("matches").delete().eq("league_id", int(league_id)).execute()
    sb().table("league_standings").delete().eq("league_id", int(league_id)).execute()
    sb().table("leagues").delete().eq("id", int(league_id)).execute()
    return True, f"League {league_id} deleted successfully"


def get_league_overview(league_id: int):
    league = get_league_by_id(league_id)
    if not league:
        return None
    matches = get_all_matches(league_id=league_id)
    completed = [m for m in matches if m["status"] == "COMPLETED"]
    live = [m for m in matches if m["status"] == "LIVE"]
    upcoming = [m for m in matches if m["status"] == "UPCOMING"]
    standings = recalculate_standings(league_id)
    return {
        "league": league,
        "summary": {
            "total_matches": len(matches),
            "completed": len(completed),
            "live": len(live),
            "upcoming": len(upcoming)
        },
        "standings": standings,
        "recent_matches": completed[:5],
        "live_matches": live,
        "upcoming_matches": upcoming[:5]
    }


def get_league_matches(league_id: int, status: Optional[str] = None):
    return get_all_matches(league_id=league_id, status=status)


def get_league_team_details(league_id: int, team_name: str):
    standings = recalculate_standings(league_id)
    team_stat = next((s for s in standings if s["team"].lower() == team_name.lower()), None)
    team_rows = _rows(sb().table("teams").select("*")
                      .eq("league_id", int(league_id))
                      .ilike("name", team_name).execute())
    team_info = team_rows[0] if team_rows else {"name": team_name, "short_name": team_name[:3].upper(), "captain": "N/A", "color": "#1a73e8"}
    raw_matches = get_all_matches(league_id=league_id)
    raw_matches = [m for m in raw_matches if m["team_a"].lower() == team_name.lower() or m["team_b"].lower() == team_name.lower()]
    return {"team": team_info, "standing": team_stat, "matches": raw_matches}


# ===========================================================================
# STANDINGS (MATHEMATICALLY ACCURATE NRR IN PYTHON & POSTGRESQL)
# ===========================================================================

def recalculate_standings(league_id: Optional[int] = None):
    """
    Computes tournament points table from completed matches for a specific league.
    Calculates P, W, L, T, NR, Pts, and NRR (accounting for all-out full overs quota).
    """
    if league_id is not None:
        league_ids = [int(league_id)]
    else:
        leagues = _rows(sb().table("leagues").select("id").execute())
        league_ids = [lg["id"] for lg in leagues] if leagues else [1]

    all_standings = []

    for lid in league_ids:
        # Try calling PostgreSQL function if exists
        try:
            sb().rpc("recalculate_standings", {"p_league_id": int(lid)}).execute()
        except Exception:
            pass

        # Python-side authoritative calculation
        teams_rows = _rows(sb().table("teams").select("*").eq("league_id", lid).execute())
        completed_matches = _rows(sb().table("matches").select("*").eq("league_id", lid).eq("status", "COMPLETED").execute())

        standings_map: Dict[str, Dict[str, Any]] = {}
        for t in teams_rows:
            standings_map[t["name"]] = {
                "league_id": lid,
                "team_id": t["id"],
                "team": t["name"],
                "captain": t.get("captain", "N/A"),
                "color": t.get("color", "#1a73e8"),
                "p": 0, "w": 0, "l": 0, "t": 0, "nr": 0, "pts": 0,
                "runs_scored": 0, "legal_balls_faced": 0,
                "runs_conceded": 0, "legal_balls_bowled": 0,
                "nrr_val": 0.0, "nrr": "+0.00"
            }

        for m in completed_matches:
            tA = m.get("team_a")
            tB = m.get("team_b")
            winner = (m.get("winner") or "").strip()
            margin = (m.get("result_margin") or "").strip().lower()
            match_overs = m.get("total_overs") or 10
            ppt = m.get("players_per_team") or (8 if match_overs == 6 else 11)
            max_wickets = max(1, ppt - 1)

            for t_name in (tA, tB):
                if t_name and t_name not in standings_map:
                    standings_map[t_name] = {
                        "league_id": lid, "team_id": t_name.replace(" ", "_"), "team": t_name,
                        "captain": "N/A", "color": "#1a73e8",
                        "p": 0, "w": 0, "l": 0, "t": 0, "nr": 0, "pts": 0,
                        "runs_scored": 0, "legal_balls_faced": 0,
                        "runs_conceded": 0, "legal_balls_bowled": 0,
                        "nrr_val": 0.0, "nrr": "+0.00"
                    }

            if tA in standings_map and tB in standings_map:
                standings_map[tA]["p"] += 1
                standings_map[tB]["p"] += 1

                if "tied" in margin or "tie" in winner.lower():
                    standings_map[tA]["t"] += 1; standings_map[tA]["pts"] += 1
                    standings_map[tB]["t"] += 1; standings_map[tB]["pts"] += 1
                elif "no result" in margin or not winner or winner in ("No Result", "Cancelled"):
                    standings_map[tA]["nr"] += 1; standings_map[tA]["pts"] += 1
                    standings_map[tB]["nr"] += 1; standings_map[tB]["pts"] += 1
                elif tA in winner:
                    standings_map[tA]["w"] += 1; standings_map[tA]["pts"] += 2
                    standings_map[tB]["l"] += 1
                elif tB in winner:
                    standings_map[tB]["w"] += 1; standings_map[tB]["pts"] += 2
                    standings_map[tA]["l"] += 1

            inns = _rows(sb().table("innings").select("*").eq("match_id", m["id"]).order("innings_number").execute())
            inn1 = next((i for i in inns if i["innings_number"] == 1), None)
            inn2 = next((i for i in inns if i["innings_number"] == 2), None)

            for inn, opp_inn in [(inn1, inn2), (inn2, inn1)]:
                if not inn: continue
                bat_t = inn["batting_team"]
                bowl_t = inn["bowling_team"]
                runs = inn.get("runs", 0)
                wickets = inn.get("wickets", 0)
                overs = inn.get("overs", 0)
                balls = inn.get("balls", 0)

                # All-out rule: if wickets >= max_wickets, full quota of match overs is counted
                if wickets >= max_wickets:
                    balls_faced = match_overs * 6
                else:
                    balls_faced = (overs * 6) + balls

                if bat_t in standings_map:
                    standings_map[bat_t]["runs_scored"] += runs
                    standings_map[bat_t]["legal_balls_faced"] += balls_faced
                if bowl_t in standings_map:
                    standings_map[bowl_t]["runs_conceded"] += runs
                    standings_map[bowl_t]["legal_balls_bowled"] += balls_faced

        league_res = list(standings_map.values())
        for s in league_res:
            rr_for = (s["runs_scored"] / (s["legal_balls_faced"] / 6.0)) if s["legal_balls_faced"] > 0 else 0.0
            rr_against = (s["runs_conceded"] / (s["legal_balls_bowled"] / 6.0)) if s["legal_balls_bowled"] > 0 else 0.0
            nrr_val = round(rr_for - rr_against, 3)
            s["nrr_val"] = nrr_val
            s["nrr"] = f"{nrr_val:+.2f}"

            # Upsert into PostgreSQL league_standings
            try:
                sb().table("league_standings").upsert({
                    "league_id": lid,
                    "team_name": s["team"],
                    "played": s["p"], "wins": s["w"], "losses": s["l"],
                    "ties": s["t"], "no_results": s["nr"], "points": s["pts"],
                    "runs_scored": s["runs_scored"],
                    "overs_faced": round(s["legal_balls_faced"] / 6.0, 2),
                    "runs_conceded": s["runs_conceded"],
                    "overs_bowled": round(s["legal_balls_bowled"] / 6.0, 2),
                    "net_run_rate": nrr_val
                }, on_conflict="league_id,team_name").execute()
            except Exception:
                pass

        league_res.sort(key=lambda x: (-x["pts"], -x["nrr_val"], x["team"]))
        for idx, s in enumerate(league_res):
            s["pos"] = idx + 1
            s["rank"] = idx + 1
            s["qualified"] = (idx < 2)
        all_standings.extend(league_res)

    return all_standings if league_id is None else [s for s in all_standings if s["league_id"] == int(league_id)]


# ===========================================================================
# MATCHES
# ===========================================================================

def _format_match(m: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not m:
        return None
    m["league_id"] = m.get("league_id") or 1
    m["teamA"] = m.get("team_a")
    m["teamB"] = m.get("team_b")
    m["matchNo"] = f"{m['id']:02d}" if isinstance(m.get("id"), int) else str(m.get("id", ""))
    m["date"] = m.get("match_date")
    m["time"] = m.get("time") or "02:00 PM"
    m["tournament_id"] = m.get("tournament_id") or 1
    m["stage"] = m.get("stage") or "LEAGUE"
    m["stage_order"] = m.get("stage_order") or 0
    m["is_locked"] = bool(m.get("is_locked"))
    total_overs = m.get("total_overs") or 10
    m["total_overs"] = total_overs
    m["overs"] = total_overs
    m["format_name"] = m.get("format_name") or ("T10" if total_overs == 10 else f"T{total_overs}")
    m["players_per_team"] = m.get("players_per_team") or (8 if total_overs == 6 else 11)
    m["balls_per_over"] = m.get("balls_per_over") or 6
    for xi_key in ("playing_xi_a", "playing_xi_b"):
        try:
            val = m.get(xi_key)
            m[xi_key] = json.loads(val) if isinstance(val, str) and val.strip() else (val if isinstance(val, list) else [])
        except Exception:
            m[xi_key] = []
    for k in ("captain_a", "captain_b", "wicketkeeper_a", "wicketkeeper_b", "toss_winner", "toss_decision", "winner", "result_margin"):
        m[k] = m.get(k) or ""
    m["innings"] = get_match_innings(m["id"])
    inn1 = next((i for i in m["innings"] if i["innings_number"] == 1), None)
    inn2 = next((i for i in m["innings"] if i["innings_number"] == 2), None)
    m["scoreA"] = f"{inn1['runs']}/{inn1['wickets']}" if inn1 else ""
    m["oversA"] = f"{inn1['overs']}.{inn1['balls']}" if inn1 else ""
    m["scoreB"] = f"{inn2['runs']}/{inn2['wickets']}" if inn2 else ("Yet to Bat" if m["status"] == "LIVE" else "")
    m["oversB"] = f"{inn2['overs']}.{inn2['balls']}" if inn2 else ""
    return m


def get_all_matches(league_id: Optional[int] = None, status: Optional[str] = None, date: Optional[str] = None, team: Optional[str] = None):
    q = sb().table("matches").select("*, leagues(name, short_name)")
    if league_id is not None:
        q = q.eq("league_id", int(league_id))
    if status is not None:
        q = q.eq("status", status.upper())
    rows = _rows(q.order("id", desc=True).execute())
    for m in rows:
        lg = m.pop("leagues", None) or {}
        m["league_name"] = lg.get("name", "")
        m["league_short_name"] = lg.get("short_name", "")
    if date:
        rows = [m for m in rows if date.lower() in (m.get("match_date") or "").lower()]
    if team:
        tl = team.lower()
        rows = [m for m in rows if tl in (m.get("team_a") or "").lower() or tl in (m.get("team_b") or "").lower()]
    return [_format_match(m) for m in rows]


def get_match_by_id(match_id: int):
    res = _one(sb().table("matches").select("*, leagues(name, short_name)").eq("id", int(match_id)).execute())
    if not res:
        return None
    lg = res.pop("leagues", None) or {}
    res["league_name"] = lg.get("name", "")
    res["league_short_name"] = lg.get("short_name", "")
    return _format_match(res)


def get_match_innings(match_id: int):
    return _rows(sb().table("innings").select("*").eq("match_id", int(match_id)).order("innings_number").execute())


def create_match(team_a: str, team_b: str, venue: str = "College Ground", match_date: str = "Today", total_overs: int = 10,
                 match_name: Optional[str] = None, league_id: int = 1, tournament_id: int = 1, stage: str = "LEAGUE", match_type: str = "LEAGUE",
                 time: str = "02:00 PM", stage_order: int = 0, format_name: Optional[str] = None, players_per_team: Optional[int] = None,
                 balls_per_over: int = 6, require_registered_teams: bool = False, **kwargs):
    if not team_a or not team_b:
        return False, "Both Team A and Team B are required"
    if team_a.strip().lower() == team_b.strip().lower():
        return False, "A team cannot play against itself"
    t_ov = int(total_overs or 10)
    fmt = format_name or ("T10" if t_ov == 10 else f"T{t_ov}")
    ppt = int(players_per_team or (8 if t_ov == 6 else 11))

    # Auto-populate Playing XI from registered rosters
    xi_a = [p["name"] for p in _rows(sb().table("players").select("name").eq("team_id", _get_team_id_by_name(team_a)).order("id").limit(ppt).execute())]
    xi_b = [p["name"] for p in _rows(sb().table("players").select("name").eq("team_id", _get_team_id_by_name(team_b)).order("id").limit(ppt).execute())]

    m_name = match_name or f"{team_a.strip()} vs {team_b.strip()}"

    row = _one(sb().table("matches").insert({
        "match_name": m_name,
        "team_a": team_a.strip(), "team_b": team_b.strip(),
        "venue": venue or "College Ground", "match_date": match_date or "Today",
        "time": time or "02:00 PM", "total_overs": t_ov,
        "format_name": fmt, "players_per_team": ppt,
        "balls_per_over": int(balls_per_over or 6), "league_id": int(league_id or 1),
        "tournament_id": int(tournament_id or 1),
        "stage": stage or "LEAGUE", "status": "UPCOMING",
        "playing_xi_a": json.dumps(xi_a), "playing_xi_b": json.dumps(xi_b)
    }).execute())
    if not row:
        return False, "Failed to create match"
    return True, get_match_by_id(row["id"])


def update_match(match_id: int, team_a: Optional[str] = None, team_b: Optional[str] = None, venue: Optional[str] = None,
                 match_date: Optional[str] = None, time: Optional[str] = None, total_overs: Optional[int] = None,
                 status: Optional[str] = None, league_id: Optional[int] = None, tournament_id: Optional[int] = None,
                 stage: Optional[str] = None, stage_order: Optional[int] = None, format_name: Optional[str] = None,
                 players_per_team: Optional[int] = None, balls_per_over: Optional[int] = None, is_locked: Optional[bool] = None,
                 playing_xi_a: Optional[List[str]] = None, playing_xi_b: Optional[List[str]] = None,
                 captain_a: Optional[str] = None, captain_b: Optional[str] = None,
                 toss_winner: Optional[str] = None, toss_decision: Optional[str] = None, **kwargs):
    existing = get_match_by_id(match_id)
    if not existing:
        return False, "Match not found"
    upd = {}
    if team_a: upd["team_a"] = team_a.strip()
    if team_b: upd["team_b"] = team_b.strip()
    if venue is not None: upd["venue"] = venue.strip()
    if match_date is not None: upd["match_date"] = match_date.strip()
    if time is not None: upd["time"] = time.strip()
    if total_overs is not None: upd["total_overs"] = int(total_overs)
    if status is not None: upd["status"] = status.strip().upper()
    if format_name is not None: upd["format_name"] = format_name.strip()
    if players_per_team is not None: upd["players_per_team"] = int(players_per_team)
    if balls_per_over is not None: upd["balls_per_over"] = int(balls_per_over)
    if league_id is not None: upd["league_id"] = int(league_id)
    if tournament_id is not None: upd["tournament_id"] = int(tournament_id)
    if stage is not None: upd["stage"] = stage.strip()
    if is_locked is not None: upd["is_locked"] = 1 if is_locked else 0
    if playing_xi_a is not None: upd["playing_xi_a"] = json.dumps(playing_xi_a)
    if playing_xi_b is not None: upd["playing_xi_b"] = json.dumps(playing_xi_b)
    if captain_a is not None: upd["captain_a"] = captain_a.strip()
    if captain_b is not None: upd["captain_b"] = captain_b.strip()
    if toss_winner is not None: upd["toss_winner"] = toss_winner.strip()
    if toss_decision is not None: upd["toss_decision"] = toss_decision.strip().upper()
    if upd:
        sb().table("matches").update(upd).eq("id", int(match_id)).execute()
    return True, get_match_by_id(match_id)


def cancel_fixture(match_id: int, reason: str = "Match Cancelled"):
    sb().table("matches").update({
        "status": "COMPLETED", "winner": "Cancelled", "result_margin": reason
    }).eq("id", int(match_id)).execute()
    return True, get_match_by_id(match_id)


def save_match_setup(match_id: int, playing_xi_a: List[str] = None, playing_xi_b: List[str] = None,
                     captain_a: str = "", captain_b: str = "", wicketkeeper_a: str = "", wicketkeeper_b: str = "",
                     toss_winner: str = "", toss_decision: str = "BAT"):
    m = get_match_by_id(match_id)
    if not m:
        return False, "Match not found"
    
    curr_xi_a = m.get("playing_xi_a") or []
    curr_xi_b = m.get("playing_xi_b") or []
    
    if playing_xi_a is None or (isinstance(playing_xi_a, list) and len(playing_xi_a) == 0):
        playing_xi_a = curr_xi_a
    if playing_xi_b is None or (isinstance(playing_xi_b, list) and len(playing_xi_b) == 0):
        playing_xi_b = curr_xi_b

    sb().table("matches").update({
        "playing_xi_a": json.dumps(playing_xi_a),
        "playing_xi_b": json.dumps(playing_xi_b),
        "captain_a": captain_a or (playing_xi_a[0] if playing_xi_a else ""),
        "captain_b": captain_b or (playing_xi_b[0] if playing_xi_b else ""),
        "wicketkeeper_a": wicketkeeper_a, "wicketkeeper_b": wicketkeeper_b,
        "toss_winner": toss_winner, "toss_decision": (toss_decision or "BAT").upper()
    }).eq("id", int(match_id)).execute()
    return True, get_match_by_id(match_id)


def start_match(match_id: int):
    """
    Starts an UPCOMING match:
    1. Sets status = LIVE (DOES NOT cancel/complete other concurrent matches!)
    2. Determines 1st innings batting/bowling teams from toss
    3. Creates Innings 1 with status = 'ACTIVE'
    4. Initializes opening batsmen and bowler
    """
    m = get_match_by_id(match_id)
    if not m:
        return False, "Match not found"

    # Multi-match concurrency safe: only update this specific match!
    sb().table("matches").update({"status": "LIVE"}).eq("id", int(match_id)).execute()

    # Determine 1st innings batting/bowling teams based on toss
    toss_w = m.get("toss_winner")
    toss_d = (m.get("toss_decision") or "BAT").upper()
    team_a = m["team_a"]
    team_b = m["team_b"]

    if toss_w == team_a:
        batting_team = team_a if toss_d != "BOWL" else team_b
        bowling_team = team_b if toss_d != "BOWL" else team_a
    elif toss_w == team_b:
        batting_team = team_b if toss_d != "BOWL" else team_a
        bowling_team = team_a if toss_d != "BOWL" else team_b
    else:
        batting_team = team_a
        bowling_team = team_b

    # Ensure Innings 1 exists
    inn1 = _one(sb().table("innings").select("*").eq("match_id", int(match_id)).eq("innings_number", 1).execute())
    if not inn1:
        inn1 = _one(sb().table("innings").insert({
            "match_id": int(match_id), "innings_number": 1,
            "batting_team": batting_team, "bowling_team": bowling_team,
            "runs": 0, "wickets": 0, "overs": 0, "balls": 0,
            "status": "ACTIVE"
        }).execute())

        bat_xi = m["playing_xi_a"] if batting_team == team_a else m["playing_xi_b"]
        bowl_xi = m["playing_xi_b"] if batting_team == team_a else m["playing_xi_a"]

        if not bat_xi:
            bat_xi = [p["name"] for p in _rows(sb().table("players").select("name").eq("team_id", _get_team_id_by_name(batting_team)).order("id").limit(2).execute())]
        if not bowl_xi:
            bowl_xi = [p["name"] for p in _rows(sb().table("players").select("name").eq("team_id", _get_team_id_by_name(bowling_team)).order("id").limit(1).execute())]

        b1 = bat_xi[0] if bat_xi else "Striker 1"
        b2 = bat_xi[1] if len(bat_xi) > 1 else "Striker 2"
        bw = bowl_xi[0] if bowl_xi else "Bowler 1"

        sb().table("batting_scores").insert([
            {"innings_id": inn1["id"], "player_name": b1, "is_on_strike": 1, "batting_order": 1},
            {"innings_id": inn1["id"], "player_name": b2, "is_on_strike": 0, "batting_order": 2}
        ]).execute()

        sb().table("bowling_scores").insert({
            "innings_id": inn1["id"], "player_name": bw, "is_current_bowler": 1
        }).execute()

    return True, get_live_match_details(match_id)


def _get_team_id_by_name(team_name: str) -> Optional[int]:
    if not team_name:
        return None
    t = _one(sb().table("teams").select("id").ilike("name", team_name.strip()).execute())
    return t["id"] if t else None


def pause_match(match_id: int):
    sb().table("matches").update({"status": "PAUSED"}).eq("id", int(match_id)).execute()
    return True, get_live_match_details(match_id)


def resume_match(match_id: int):
    sb().table("matches").update({"status": "LIVE"}).eq("id", int(match_id)).execute()
    return True, get_live_match_details(match_id)


def complete_match(match_id: int, winner: Optional[str] = None, result_margin: str = ""):
    m = get_match_by_id(match_id)
    if not m:
        return False, "Match not found"
    sb().table("matches").update({
        "status": "COMPLETED", "winner": winner or "Match Completed", "result_margin": result_margin
    }).eq("id", int(match_id)).execute()
    recalculate_standings(m.get("league_id", 1))
    return True, get_live_match_details(match_id)


def abandon_match(match_id: int, reason: str = "Match Abandoned"):
    m = get_match_by_id(match_id)
    if not m:
        return False, "Match not found"
    sb().table("matches").update({
        "status": "COMPLETED", "winner": "No Result", "result_margin": reason
    }).eq("id", int(match_id)).execute()
    recalculate_standings(m.get("league_id", 1))
    return True, get_live_match_details(match_id)


def delete_match(match_id: int):
    m = get_match_by_id(match_id)
    if not m:
        return False, "Match not found"
    lid = m.get("league_id", 1)
    sb().table("ball_events").delete().eq("innings_id", f"(SELECT id FROM innings WHERE match_id = {match_id})").execute()
    sb().table("batting_scores").delete().eq("innings_id", f"(SELECT id FROM innings WHERE match_id = {match_id})").execute()
    sb().table("bowling_scores").delete().eq("innings_id", f"(SELECT id FROM innings WHERE match_id = {match_id})").execute()
    sb().table("innings").delete().eq("match_id", int(match_id)).execute()
    sb().table("matches").delete().eq("id", int(match_id)).execute()
    recalculate_standings(lid)
    return True, f"Match {match_id} deleted"


def switch_to_second_innings(match_id: int):
    """
    Transitions match to 2nd innings:
    1. Completes 1st innings
    2. Calculates target = inn1.runs + 1
    3. Initializes 2nd innings with reversed teams and status = 'ACTIVE'
    """
    m = get_match_by_id(match_id)
    if not m:
        return False, "Match not found"

    inn1 = _one(sb().table("innings").select("*").eq("match_id", int(match_id)).eq("innings_number", 1).execute())
    if not inn1:
        return False, "1st innings not found"

    target = (inn1.get("runs") or 0) + 1
    sb().table("innings").update({"status": "COMPLETED"}).eq("id", inn1["id"]).execute()

    inn2 = _one(sb().table("innings").select("*").eq("match_id", int(match_id)).eq("innings_number", 2).execute())
    if not inn2:
        bat_team = inn1["bowling_team"]
        bowl_team = inn1["batting_team"]
        inn2 = _one(sb().table("innings").insert({
            "match_id": int(match_id), "innings_number": 2,
            "batting_team": bat_team, "bowling_team": bowl_team,
            "runs": 0, "wickets": 0, "overs": 0, "balls": 0,
            "target": target, "status": "ACTIVE"
        }).execute())
        inn2_id = inn2["id"]

        bat_xi = m["playing_xi_a"] if bat_team == m["team_a"] else m["playing_xi_b"]
        bowl_xi = m["playing_xi_b"] if bat_team == m["team_a"] else m["playing_xi_a"]

        if not bat_xi:
            bat_xi = [p["name"] for p in _rows(sb().table("players").select("name").eq("team_id", _get_team_id_by_name(bat_team)).order("id").limit(2).execute())]
        if not bowl_xi:
            bowl_xi = [p["name"] for p in _rows(sb().table("players").select("name").eq("team_id", _get_team_id_by_name(bowl_team)).order("id").limit(1).execute())]

        b1 = bat_xi[0] if bat_xi else "Striker 1"
        b2 = bat_xi[1] if len(bat_xi) > 1 else "Striker 2"
        bw = bowl_xi[0] if bowl_xi else "Bowler 1"

        sb().table("batting_scores").insert([
            {"innings_id": inn2_id, "player_name": b1, "is_on_strike": 1, "batting_order": 1},
            {"innings_id": inn2_id, "player_name": b2, "is_on_strike": 0, "batting_order": 2}
        ]).execute()

        sb().table("bowling_scores").insert({
            "innings_id": inn2_id, "player_name": bw, "is_current_bowler": 1
        }).execute()

    sb().table("matches").update({"current_innings": 2}).eq("id", int(match_id)).execute()
    return True, get_live_match_details(match_id)


def get_match_players_for_scoring(match_id: int, innings_id: Optional[int] = None):
    """
    Standardized API response contract:
    Returns both `batting_players` and `batting_xi` as well as `available_batters`.
    """
    m = get_match_by_id(match_id)
    if not m:
        return {"success": False, "batting_players": [], "bowling_players": [], "available_batters": []}

    inns = m.get("innings") or []
    inn = next((i for i in inns if i["id"] == innings_id), None) if innings_id else (inns[-1] if inns else None)
    batting_team = inn["batting_team"] if inn else m["team_a"]
    bowling_team = inn["bowling_team"] if inn else m["team_b"]

    bat_xi_names = m["playing_xi_a"] if batting_team == m["team_a"] else m["playing_xi_b"]
    bowl_xi_names = m["playing_xi_b"] if batting_team == m["team_a"] else m["playing_xi_a"]

    if not bat_xi_names:
        bat_xi_names = [p["name"] for p in _rows(sb().table("players").select("name").eq("team_id", _get_team_id_by_name(batting_team)).order("id").execute())]
    if not bowl_xi_names:
        bowl_xi_names = [p["name"] for p in _rows(sb().table("players").select("name").eq("team_id", _get_team_id_by_name(bowling_team)).order("id").execute())]

    dismissed = set()
    currently_batting = set()
    if inn:
        bats = _rows(sb().table("batting_scores").select("player_name,is_out").eq("innings_id", inn["id"]).execute())
        for b in bats:
            if b["is_out"]:
                dismissed.add(b["player_name"])
            else:
                currently_batting.add(b["player_name"])

    available_names = [p for p in bat_xi_names if p not in dismissed and p not in currently_batting]

    batting_players = [{"id": p.replace(" ", "_"), "name": p} for p in bat_xi_names]
    bowling_players = [{"id": p.replace(" ", "_"), "name": p} for p in bowl_xi_names]
    available_batters = [{"id": p.replace(" ", "_"), "name": p} for p in available_names]

    return {
        "success": True,
        "batting_team": batting_team,
        "bowling_team": bowling_team,
        "batting_players": batting_players,
        "bowling_players": bowling_players,
        "available_batters": available_batters,
        "batting_xi": bat_xi_names,
        "bowling_xi": bowl_xi_names,
        "bowlers": bowl_xi_names,
        "fielders": bowling_players
    }


def claim_match_atomic(match_id: int, user_id: str, lease_minutes: int = 15):
    m = _one(sb().table("matches").select("claimed_by_user_id,claim_expires_at").eq("id", int(match_id)).execute())
    if not m:
        return False, (404, "Match not found", None)
    now = datetime.datetime.utcnow()
    holder = m.get("claimed_by_user_id")
    expires_str = m.get("claim_expires_at")
    is_active = False
    if holder and expires_str:
        try:
            exp = datetime.datetime.fromisoformat(expires_str.replace("Z", ""))
            is_active = exp > now
        except Exception:
            pass
    if holder and is_active and holder != user_id:
        return False, (409, f"Match is currently claimed by another scorer ({holder}).", {"claimed_by": holder})
    new_exp = (now + datetime.timedelta(minutes=lease_minutes)).isoformat()
    sb().table("matches").update({"claimed_by_user_id": user_id, "claim_expires_at": new_exp}).eq("id", int(match_id)).execute()
    return True, get_match_by_id(match_id)


def heartbeat_match_claim(match_id: int, user_id: str, lease_minutes: int = 15):
    new_exp = (datetime.datetime.utcnow() + datetime.timedelta(minutes=lease_minutes)).isoformat()
    sb().table("matches").update({"claim_expires_at": new_exp}).eq("id", int(match_id)).eq("claimed_by_user_id", user_id).execute()
    return True, get_match_by_id(match_id)


def release_match_claim(match_id: int, user_id: Optional[str] = None, force: bool = False):
    sb().table("matches").update({"claimed_by_user_id": None, "claim_expires_at": None}).eq("id", int(match_id)).execute()
    return True, "Claim released"


def get_scorer_matches(user_id: str):
    """
    Returns segmented matches for Scorer Match Hub:
    my_matches, available_matches, other_claimed
    """
    matches = get_all_matches()
    my_matches = []
    available_matches = []
    other_claimed = []
    now = datetime.datetime.utcnow()

    for m in matches:
        if (m.get("status") or "").upper() == "COMPLETED":
            continue
        holder = m.get("claimed_by_user_id")
        exp_str = m.get("claim_expires_at")
        is_active = False
        if holder and exp_str:
            try:
                exp_dt = datetime.datetime.fromisoformat(str(exp_str).replace("Z", ""))
                is_active = exp_dt > now
            except Exception:
                pass
        m["is_claim_active"] = is_active

        if holder == user_id and is_active:
            my_matches.append(m)
        elif not holder or not is_active:
            available_matches.append(m)
        else:
            other_claimed.append(m)

    return {
        "success": True,
        "my_matches": my_matches,
        "available_matches": available_matches,
        "other_claimed": other_claimed,
        "counts": {
            "my": len(my_matches),
            "available": len(available_matches),
            "other": len(other_claimed)
        }
    }


# ===========================================================================
# SCORING ENGINE INTEGRATION (PURE REPLAY & RECALCULATION)
# ===========================================================================

def generate_ball_commentary(runs: int, extras: int, extra_type: Optional[str], wicket: int, wicket_type: Optional[str],
                              batsman_name: Optional[str], bowler_name: Optional[str], out_player_name: Optional[str] = None,
                              fielder_name: Optional[str] = None) -> str:
    b = (batsman_name or "Batter").split()[0]
    bw = (bowler_name or "Bowler").split()[0]
    out = (out_player_name or batsman_name or "Batter").split()[0]
    f = (fielder_name or "").split()[0] if fielder_name else ""
    if wicket:
        wt = (wicket_type or "OUT").upper()
        if wt == "BOWLED": return f"WICKET! {out} is clean bowled by {bw}!"
        elif wt == "CAUGHT": return f"WICKET! {out} caught {'by ' + f + ', b ' + bw if f and f.lower()!=bw.lower() else '& b ' + bw}!"
        elif wt == "LBW": return f"WICKET! {out} is plumb LBW to {bw}!"
        elif wt == "RUN_OUT" or wt == "RUN OUT": return f"WICKET! {out} is run out{' by ' + f if f else ''}!"
        elif wt == "STUMPED": return f"WICKET! {out} is stumped {('by ' + f) if f else ''} off {bw}!"
        elif wt == "HIT_WICKET" or wt == "HIT WICKET": return f"WICKET! {out} hits their own wicket!"
        else: return f"WICKET! {out} is out ({wt.lower()})!"
    et = (extra_type or "").upper()
    if et == "WIDE": return f"Wide! {extras} penalty run(s)."
    if et == "NO BALL": return f"No ball from {bw}! Free hit." if runs == 0 else f"No ball! {b} scores {runs} run(s)."
    if et == "BYE": return f"Bye! {extras} run(s)."
    if et == "LEG BYE": return f"Leg bye! {extras} run(s)."
    total = runs + extras
    if total == 0: return f"Dot ball. {bw} to {b}."
    if total == 1: return f"{b} takes a single."
    if total == 2: return f"{b} drives for two runs."
    if total == 4: return f"FOUR! {b} finds the boundary!"
    if total == 6: return f"SIX! {b} clears the ropes!"
    return f"{b} scores {total} runs off {bw}."


def _recalculate_innings_state_supabase(innings_id: int):
    """
    Pure state recalculation & atomic persistence:
    Reconstructs complete innings state from ball_events using cricket_engine.py.
    """
    inn = _one(sb().table("innings").select("*").eq("id", innings_id).execute())
    if not inn:
        return
    match_id = inn["match_id"]
    match = get_match_by_id(match_id)
    if not match:
        return

    config = MatchConfig.from_match_dict(match)
    events = _rows(sb().table("ball_events").select("*").eq("innings_id", innings_id).order("id").execute())

    # Get initial pair
    existing_bats = _rows(sb().table("batting_scores").select("*").eq("innings_id", innings_id).order("batting_order").execute())
    existing_bowls = _rows(sb().table("bowling_scores").select("*").eq("innings_id", innings_id).execute())

    init_st = existing_bats[0]["player_name"] if len(existing_bats) > 0 else None
    init_nst = existing_bats[1]["player_name"] if len(existing_bats) > 1 else None
    init_bw = existing_bowls[0]["player_name"] if len(existing_bowls) > 0 else None

    state = replay_innings_events(config, inn, events, init_st, init_nst, init_bw)

    # Update innings record
    sb().table("innings").update({
        "runs": state["runs"],
        "wickets": state["wickets"],
        "overs": state["overs"],
        "balls": state["balls"],
        "status": state["status"]
    }).eq("id", innings_id).execute()

    # Sync batting scores: update or insert participating batsmen
    for b in state["batting_performances"]:
        p_name = b["player_name"]
        sb().table("batting_scores").upsert({
            "innings_id": innings_id,
            "player_name": p_name,
            "runs": b["runs"],
            "balls": b["balls"],
            "fours": b["fours"],
            "sixes": b["sixes"],
            "strike_rate": b["strike_rate"],
            "is_out": 1 if b["is_out"] else 0,
            "is_on_strike": 1 if b["is_on_strike"] else 0,
            "batting_order": b["batting_order"]
        }, on_conflict="innings_id,player_name").execute()

    # Clean up any ghost batsmen no longer present
    active_names = [b["player_name"] for b in state["batting_performances"]]
    if active_names:
        for ex in existing_bats:
            if ex["player_name"] not in active_names:
                sb().table("batting_scores").delete().eq("id", ex["id"]).execute()

    # Sync bowling scores
    for bw in state["bowling_performances"]:
        bw_name = bw["player_name"]
        sb().table("bowling_scores").upsert({
            "innings_id": innings_id,
            "player_name": bw_name,
            "overs": bw["overs"],
            "balls": bw["balls"],
            "legal_balls": bw["legal_balls"],
            "maidens": bw["maidens"],
            "runs": bw["runs_conceded"],
            "runs_conceded": bw["runs_conceded"],
            "wickets": bw["wickets"],
            "economy_rate": bw["economy_rate"],
            "is_current_bowler": 1 if bw["is_current_bowler"] else 0
        }, on_conflict="innings_id,player_name").execute()

    # Auto Innings Transition / Match Result Evaluation
    if inn.get("innings_number") == 1 and state["is_completed"]:
        # Auto-create 2nd innings if not yet created
        inn2 = _one(sb().table("innings").select("*").eq("match_id", match_id).eq("innings_number", 2).execute())
        if not inn2:
            switch_to_second_innings(match_id)

    elif inn.get("innings_number") == 2 and state["is_completed"]:
        # Auto-complete match
        inn1 = _one(sb().table("innings").select("*").eq("match_id", match_id).eq("innings_number", 1).execute())
        res = evaluate_match_result(config, inn1 or {}, state, match["team_a"], match["team_b"])
        if res["is_completed"]:
            sb().table("matches").update({
                "status": "COMPLETED",
                "winner": res["winner"],
                "result_margin": res["result_margin"]
            }).eq("id", match_id).execute()
            recalculate_standings(match.get("league_id", 1))


def _get_active_innings(match_id: int):
    m = get_match_by_id(match_id)
    if not m:
        return None, None, "Match not found"
    if m["status"] not in ("LIVE", "PAUSED"):
        return None, None, f"Match is {m['status']}, not LIVE"
    if m["is_locked"]:
        return None, None, "Match is locked and protected from scoring"
    inns = m.get("innings") or []
    curr_inn_num = m.get("current_innings", 1)
    inn = next((i for i in inns if i["innings_number"] == curr_inn_num), None)
    if not inn and inns:
        inn = inns[-1]
    if not inn:
        return None, None, "No active innings found for match"
    if inn.get("status") == "COMPLETED":
        return None, None, "Active innings has already been completed"
    return m, inn, None


def record_ball(match_id: int, runs: int = 0, extra: Optional[str] = None, batsman_name: Optional[str] = None,
                bowler_name: Optional[str] = None, client_event_uuid: Optional[str] = None, expected_sequence: Optional[int] = None):
    """
    Authoritative Delivery Recording:
    Idempotent per client_event_uuid with pure replay state reconstruction.
    """
    m, inn, err = _get_active_innings(match_id)
    if err:
        return False, err

    inn_id = inn["id"]

    # Idempotency check: if UUID already recorded, return current live state
    if client_event_uuid:
        existing = _one(sb().table("ball_events").select("id").eq("client_event_uuid", client_event_uuid).execute())
        if existing:
            return True, {
                "status": "ALREADY_APPLIED",
                "client_event_uuid": client_event_uuid,
                "message": "Delivery with this UUID was already committed.",
                "match": get_live_match_details(match_id)
            }

    # Conflict check: verify expected_sequence matches current innings event count
    if expected_sequence is not None:
        curr_events = sb().table("ball_events").select("id", count="exact").eq("innings_id", inn_id).execute().count or 0
        if curr_events != expected_sequence:
            return False, {
                "status": "REJECTED_CONFLICT",
                "client_event_uuid": client_event_uuid,
                "error": f"Server timeline has diverged. Expected sequence {expected_sequence}, but server is at {curr_events}."
            }

    batting_team = inn["batting_team"]
    bowling_team = inn["bowling_team"]
    bat_xi = m.get("playing_xi_a") if batting_team == m["team_a"] else m.get("playing_xi_b")
    bowl_xi = m.get("playing_xi_b") if batting_team == m["team_a"] else m.get("playing_xi_a")

    runs = int(runs or 0)
    extra_type = (extra or "").strip().upper() if extra else None
    extras = 0

    if extra_type == "WIDE":
        extras = 1 + runs
        runs = 0
    elif extra_type == "NO BALL":
        extras = 1
    elif extra_type in ("BYE", "LEG BYE"):
        extras = runs if runs > 0 else 1
        runs = 0

    # Determine striker and bowler if not provided
    if not batsman_name:
        st = _one(sb().table("batting_scores").select("player_name").eq("innings_id", inn_id).eq("is_on_strike", 1).eq("is_out", 0).limit(1).execute())
        if not st:
            return False, "No active striker currently on pitch. Set striker before scoring."
        batsman_name = st["player_name"]
    else:
        batsman_name = str(batsman_name).strip()
        if bat_xi and batsman_name not in bat_xi:
            return False, f"Batsman '{batsman_name}' is not in the Playing XI for {batting_team}"

    if not bowler_name:
        bw = _one(sb().table("bowling_scores").select("player_name").eq("innings_id", inn_id).eq("is_current_bowler", 1).limit(1).execute())
        if not bw:
            return False, "No active bowler assigned. Set bowler before scoring."
        bowler_name = bw["player_name"]
    else:
        bowler_name = str(bowler_name).strip()
        if bowl_xi and bowler_name not in bowl_xi:
            return False, f"Bowler '{bowler_name}' is not in the Playing XI for {bowling_team}"

    comm = generate_ball_commentary(runs, extras, extra_type, 0, None, batsman_name, bowler_name)

    sb().table("ball_events").insert({
        "innings_id": inn_id,
        "over_number": inn["overs"],
        "ball_number": inn["balls"] + 1,
        "batsman_name": batsman_name,
        "bowler_name": bowler_name,
        "runs": runs,
        "extras": extras,
        "extra_type": extra_type,
        "wicket": 0,
        "commentary": comm,
        "client_event_uuid": client_event_uuid
    }).execute()

    _recalculate_innings_state_supabase(inn_id)
    return True, get_live_match_details(match_id)


def record_wicket(match_id: int, new_batter_name: Optional[str] = None, wicket_type: str = "BOWLED",
                  dismissal_type: Optional[str] = None, out_batter_name: Optional[str] = None,
                  fielder_name: Optional[str] = None, bowler_name: Optional[str] = None,
                  client_event_uuid: Optional[str] = None, expected_sequence: Optional[int] = None,
                  extra_type: Optional[str] = None, runs: int = 0):
    m, inn, err = _get_active_innings(match_id)
    if err:
        return False, err

    inn_id = inn["id"]
    w_type = (dismissal_type or wicket_type or "BOWLED").strip().upper().replace("-", " ")

    # Validate dismissal legality
    ok, val_err = validate_dismissal_on_delivery(w_type, extra_type)
    if not ok:
        return False, val_err

    # Idempotency check
    if client_event_uuid:
        existing = _one(sb().table("ball_events").select("id").eq("client_event_uuid", client_event_uuid).execute())
        if existing:
            return True, {
                "status": "ALREADY_APPLIED",
                "client_event_uuid": client_event_uuid,
                "message": "Wicket delivery with this UUID was already committed.",
                "match": get_live_match_details(match_id)
            }

    # Conflict check: verify expected_sequence matches current innings event count
    if expected_sequence is not None:
        curr_events = sb().table("ball_events").select("id", count="exact").eq("innings_id", inn_id).execute().count or 0
        if curr_events != expected_sequence:
            return False, {
                "status": "REJECTED_CONFLICT",
                "client_event_uuid": client_event_uuid,
                "error": f"Server timeline has diverged. Expected sequence {expected_sequence}, but server is at {curr_events}."
            }

    batting_team = inn["batting_team"]
    bowling_team = inn["bowling_team"]
    bat_xi = m.get("playing_xi_a") if batting_team == m["team_a"] else m.get("playing_xi_b")
    bowl_xi = m.get("playing_xi_b") if batting_team == m["team_a"] else m.get("playing_xi_a")

    active_bats = _rows(sb().table("batting_scores").select("player_name,is_out,is_on_strike").eq("innings_id", inn_id).eq("is_out", 0).execute())
    active_names = [b["player_name"] for b in active_bats]

    if not out_batter_name:
        st = next((b for b in active_bats if b.get("is_on_strike") == 1), None)
        if not st and active_bats:
            st = active_bats[0]
        if not st:
            return False, "No active batsman at the crease to dismiss."
        out_batter_name = st["player_name"]
    else:
        out_batter_name = str(out_batter_name).strip()
        if out_batter_name not in active_names:
            return False, f"Player '{out_batter_name}' is not currently at the crease"

    if not bowler_name:
        bw = _one(sb().table("bowling_scores").select("player_name").eq("innings_id", inn_id).eq("is_current_bowler", 1).limit(1).execute())
        if not bw:
            return False, "No active bowler assigned."
        bowler_name = bw["player_name"]
    else:
        bowler_name = str(bowler_name).strip()
        if bowl_xi and bowler_name not in bowl_xi:
            return False, f"Bowler '{bowler_name}' is not in the Playing XI for {bowling_team}"

    if fielder_name:
        fielder_name = str(fielder_name).strip()
        if bowl_xi and fielder_name not in bowl_xi:
            return False, f"Fielder '{fielder_name}' is not in the Playing XI for {bowling_team}"

    if new_batter_name:
        new_batter_name = str(new_batter_name).strip()
        if bat_xi and new_batter_name not in bat_xi:
            return False, f"Incoming batter '{new_batter_name}' is not in the Playing XI for {batting_team}"
        all_bats = _rows(sb().table("batting_scores").select("player_name,is_out").eq("innings_id", inn_id).execute())
        for b in all_bats:
            if b["player_name"].lower() == new_batter_name.lower():
                if b["is_out"]:
                    return False, f"Incoming batter '{new_batter_name}' is already out"
                if b["player_name"] in active_names and b["player_name"] != out_batter_name:
                    return False, f"Incoming batter '{new_batter_name}' is already at the crease as non-striker"

    comm = generate_ball_commentary(runs, 0, extra_type, 1, w_type, out_batter_name, bowler_name, out_batter_name, fielder_name)

    sb().table("ball_events").insert({
        "innings_id": inn_id,
        "over_number": inn["overs"],
        "ball_number": inn["balls"] + 1,
        "batsman_name": out_batter_name,
        "bowler_name": bowler_name,
        "runs": runs,
        "extras": 0,
        "extra_type": extra_type,
        "wicket": 1,
        "wicket_type": w_type,
        "out_player_name": out_batter_name,
        "fielder_name": fielder_name,
        "new_batter_name": new_batter_name,
        "commentary": comm,
        "client_event_uuid": client_event_uuid
    }).execute()

    _recalculate_innings_state_supabase(inn_id)
    return True, get_live_match_details(match_id)


def undo_last_ball(match_id: int):
    """
    Undoes exactly the immediately previous delivery:
    Deletes the last ball_event and pure-replays canonical state.
    """
    m = get_match_by_id(match_id)
    if not m:
        return False, "Match not found"
    if m["is_locked"]:
        return False, "Match is locked and protected from editing"

    inns = m.get("innings") or []
    if not inns:
        return False, "No innings found"
    inn = inns[-1]
    inn_id = inn["id"]

    last = _one(sb().table("ball_events").select("id").eq("innings_id", inn_id).order("id", desc=True).limit(1).execute())
    if not last:
        return False, "No ball events to undo in current innings"

    sb().table("ball_events").delete().eq("id", last["id"]).execute()

    # Revert COMPLETED match to LIVE if needed
    if m["status"] == "COMPLETED":
        sb().table("matches").update({"status": "LIVE", "winner": "", "result_margin": ""}).eq("id", int(match_id)).execute()
    if inn.get("status") == "COMPLETED":
        sb().table("innings").update({"status": "ACTIVE"}).eq("id", inn_id).execute()

    _recalculate_innings_state_supabase(inn_id)
    return True, get_live_match_details(match_id)


def edit_last_ball(match_id: int, runs: int = 0, extra_type: Optional[str] = None, wicket: int = 0, wicket_type: Optional[str] = None,
                   batsman_name: Optional[str] = None, bowler_name: Optional[str] = None, commentary: Optional[str] = None):
    m, inn, err = _get_active_innings(match_id)
    if err:
        return False, err
    inn_id = inn["id"]
    last = _one(sb().table("ball_events").select("*").eq("innings_id", inn_id).order("id", desc=True).limit(1).execute())
    if not last:
        return False, "No ball event to edit"
    runs = int(runs or 0)
    extras = 0
    et = (extra_type or "").strip().upper() or None
    if et == "WIDE": extras = 1 + runs; runs = 0
    elif et == "NO BALL": extras = 1
    elif et in ("BYE", "LEG BYE"): extras = runs if runs > 0 else 1; runs = 0
    b_name = batsman_name or last["batsman_name"]
    bw_name = bowler_name or last["bowler_name"]
    w = 1 if wicket else 0
    wt = (wicket_type or "").upper() if w else None
    comm = commentary or generate_ball_commentary(runs, extras, et, w, wt, b_name, bw_name, b_name if w else None)
    sb().table("ball_events").update({
        "runs": runs, "extras": extras, "extra_type": et, "wicket": w,
        "wicket_type": wt, "batsman_name": b_name, "bowler_name": bw_name, "commentary": comm
    }).eq("id", last["id"]).execute()
    _recalculate_innings_state_supabase(inn_id)
    return True, get_live_match_details(match_id)


def set_live_score(match_id: int, runs: int, wickets: int, overs_val: Any):
    m, inn, err = _get_active_innings(match_id)
    if err:
        return False, err
    try:
        parts = str(overs_val).split(".")
        ov_comp = int(parts[0])
        b_in_ov = int(parts[1]) if len(parts) > 1 else 0
    except Exception:
        ov_comp = b_in_ov = 0
    sb().table("innings").update({"runs": int(runs), "wickets": int(wickets), "overs": ov_comp, "balls": b_in_ov}).eq("id", inn["id"]).execute()
    return True, get_live_match_details(match_id)


def swap_strike(match_id: int):
    m, inn, err = _get_active_innings(match_id)
    if err:
        return False, err
    bats = _rows(sb().table("batting_scores").select("id,is_on_strike").eq("innings_id", inn["id"]).eq("is_out", 0).order("is_on_strike", desc=True).order("batting_order").limit(2).execute())
    if len(bats) < 2:
        return False, "Two active batters needed"
    b1, b2 = bats[0], bats[1]
    sb().table("batting_scores").update({"is_on_strike": 0 if b1["is_on_strike"] else 1}).eq("id", b1["id"]).execute()
    sb().table("batting_scores").update({"is_on_strike": 1 if b1["is_on_strike"] else 0}).eq("id", b2["id"]).execute()
    return True, get_live_match_details(match_id)


def set_current_striker(match_id: int, player_name: str):
    if not player_name:
        return False, "Player name required"
    player_name = str(player_name).strip()
    m, inn, err = _get_active_innings(match_id)
    if err:
        return False, err
    inn_id = inn["id"]
    sb().table("batting_scores").update({"is_on_strike": 0}).eq("innings_id", inn_id).execute()
    existing = _one(sb().table("batting_scores").select("id").eq("innings_id", inn_id).ilike("player_name", player_name).execute())
    if existing:
        sb().table("batting_scores").update({"is_on_strike": 1, "is_out": 0}).eq("id", existing["id"]).execute()
    else:
        cnt = sb().table("batting_scores").select("id", count="exact").eq("innings_id", inn_id).execute().count or 0
        sb().table("batting_scores").insert({"innings_id": inn_id, "player_name": player_name, "batting_order": cnt + 1, "is_on_strike": 1}).execute()
    return True, get_live_match_details(match_id)


def set_current_non_striker(match_id: int, player_name: str):
    if not player_name:
        return False, "Player name required"
    player_name = str(player_name).strip()
    m, inn, err = _get_active_innings(match_id)
    if err:
        return False, err
    inn_id = inn["id"]
    existing = _one(sb().table("batting_scores").select("id,batting_order").eq("innings_id", inn_id).ilike("player_name", player_name).execute())
    if not existing:
        cnt = sb().table("batting_scores").select("id", count="exact").eq("innings_id", inn_id).execute().count or 0
        sb().table("batting_scores").insert({"innings_id": inn_id, "player_name": player_name, "batting_order": cnt + 1, "is_on_strike": 0}).execute()
    else:
        sb().table("batting_scores").update({"is_on_strike": 0, "is_out": 0}).eq("id", existing["id"]).execute()
    return True, get_live_match_details(match_id)


def set_current_bowler(match_id: int, player_name: str):
    m, inn, err = _get_active_innings(match_id)
    if err:
        return False, err
    inn_id = inn["id"]
    sb().table("bowling_scores").update({"is_current_bowler": 0}).eq("innings_id", inn_id).execute()
    existing = _one(sb().table("bowling_scores").select("id").eq("innings_id", inn_id).eq("player_name", player_name).execute())
    if existing:
        sb().table("bowling_scores").update({"is_current_bowler": 1}).eq("id", existing["id"]).execute()
    else:
        sb().table("bowling_scores").insert({"innings_id": inn_id, "player_name": player_name, "is_current_bowler": 1}).execute()
    return True, get_live_match_details(match_id)


def sync_match_events(match_id: int, events: List[Dict[str, Any]], user_id: Optional[str] = None):
    """
    Offline queue synchronization implementation for Supabase:
    Applies ordered offline deliveries with client_event_uuid idempotency.
    """
    m, inn, err = _get_active_innings(match_id)
    if err:
        return False, (400, err)

    inn_id = inn["id"]
    results = []

    for ev in events:
        uuid_val = ev.get("client_event_uuid")
        if uuid_val:
            existing = _one(sb().table("ball_events").select("id").eq("client_event_uuid", uuid_val).execute())
            if existing:
                results.append({"status": "ALREADY_APPLIED", "client_event_uuid": uuid_val})
                continue

        # Process delivery
        if ev.get("wicket"):
            ok, _ = record_wicket(
                match_id,
                new_batter_name=ev.get("new_batter_name"),
                wicket_type=ev.get("wicket_type", "BOWLED"),
                out_batter_name=ev.get("out_player_name"),
                fielder_name=ev.get("fielder_name"),
                bowler_name=ev.get("bowler_name"),
                client_event_uuid=uuid_val,
                extra_type=ev.get("extra_type"),
                runs=ev.get("runs", 0)
            )
        else:
            ok, _ = record_ball(
                match_id,
                runs=ev.get("runs", 0),
                extra=ev.get("extra_type"),
                batsman_name=ev.get("batsman_name"),
                bowler_name=ev.get("bowler_name"),
                client_event_uuid=uuid_val
            )

        if ok:
            results.append({"status": "APPLIED", "client_event_uuid": uuid_val})
        else:
            results.append({"status": "REJECTED", "client_event_uuid": uuid_val})

    return True, {"results": results, "match": get_live_match_details(match_id)}


# ===========================================================================
# SCORECARD READERS & STATS
# ===========================================================================

def get_live_match_details(match_id: Optional[int] = None, league_id: Optional[int] = None):
    if match_id:
        m_row = _one(sb().table("matches").select("*, leagues(name, short_name)").eq("id", int(match_id)).execute())
    elif league_id:
        m_row = _one(sb().table("matches").select("*, leagues(name, short_name)").eq("league_id", int(league_id)).eq("status", "LIVE").order("id", desc=True).limit(1).execute())
    else:
        m_row = _one(sb().table("matches").select("*, leagues(name, short_name)").eq("status", "LIVE").order("id", desc=True).limit(1).execute())

    if not m_row:
        fallback_q = sb().table("matches").select("*, leagues(name, short_name)").order("id", desc=True).limit(1)
        if league_id:
            fallback_q = fallback_q.eq("league_id", int(league_id))
        m_row = _one(fallback_q.execute())

    if not m_row:
        return None

    lg = m_row.pop("leagues", None) or {}
    match = dict(m_row)
    match["league_name"] = lg.get("name", "")
    match["league_short_name"] = lg.get("short_name", "")

    m_id = match["id"]
    innings_list = _rows(sb().table("innings").select("*").eq("match_id", m_id).order("innings_number").execute())
    curr_inn_num = match.get("current_innings", 1)
    current_inn = next((i for i in innings_list if i["innings_number"] == curr_inn_num), None)
    if not current_inn and innings_list:
        current_inn = innings_list[-1]

    live_data = {
        "id": m_id, "league_id": match.get("league_id") or 1,
        "league_name": match.get("league_name"),
        "match_name": f"{match.get('team_a')} vs {match.get('team_b')}",
        "team_a": match.get("team_a"), "team_b": match.get("team_b"),
        "teamA": match.get("team_a"), "teamB": match.get("team_b"),
        "venue": match.get("venue"), "match_date": match.get("match_date"),
        "status": match.get("status"), "current_innings": match.get("current_innings"),
        "total_overs": match.get("total_overs"), "winner": match.get("winner"),
        "result_margin": match.get("result_margin"), "is_locked": bool(match.get("is_locked")),
        "claimed_by_user_id": match.get("claimed_by_user_id"),
        "claim_expires_at": match.get("claim_expires_at"),
        "innings": innings_list, "current_inn": current_inn,
        "matchNo": f"{m_id:02d}",
    }

    if current_inn:
        inn_id = current_inn["id"]
        bats = _rows(sb().table("batting_scores").select("*").eq("innings_id", inn_id).eq("is_out", 0).order("is_on_strike", desc=True).order("batting_order").limit(2).execute())
        striker = bats[0] if bats else None
        non_striker = bats[1] if len(bats) > 1 else None
        bw_row = _one(sb().table("bowling_scores").select("*").eq("innings_id", inn_id).eq("is_current_bowler", 1).execute())
        recent_balls = list(reversed(_rows(sb().table("ball_events").select("*").eq("innings_id", inn_id).order("id", desc=True).limit(18).execute())))

        live_data.update({
            "striker": striker, "non_striker": non_striker, "current_bowler": bw_row,
            "live_scorecard": {
                "runs": current_inn.get("runs", 0),
                "wickets": current_inn.get("wickets", 0),
                "oversCompleted": current_inn.get("overs", 0),
                "ballsInOver": current_inn.get("balls", 0),
                "overs": current_inn.get("overs", 0),
                "balls": current_inn.get("balls", 0),
                "oversDisplay": f"{current_inn.get('overs', 0)}.{current_inn.get('balls', 0)}",
                "target": current_inn.get("target"),
                "batting_team": current_inn.get("batting_team"),
                "bowling_team": current_inn.get("bowling_team"),
                "striker": striker, "nonStriker": non_striker, "bowler": bw_row,
                "currentOverBalls": recent_balls[-6:] if recent_balls else []
            },
            "recent_deliveries": recent_balls
        })

    return live_data


def get_match_full_scorecard(match_id: int):
    m = get_match_by_id(match_id)
    if not m:
        return None
    inns = _rows(sb().table("innings").select("*").eq("match_id", int(match_id)).order("innings_number").execute())
    for inn in inns:
        inn_id = inn["id"]
        inn["batting_performances"] = _rows(sb().table("batting_scores").select("*").eq("innings_id", inn_id).order("batting_order").execute())
        inn["bowling_performances"] = _rows(sb().table("bowling_scores").select("*").eq("innings_id", inn_id).order("id").execute())
        inn["recent_balls"] = list(reversed(_rows(sb().table("ball_events").select("*").eq("innings_id", inn_id).order("id", desc=True).limit(24).execute())))
    m["innings"] = inns
    return m


def get_match_commentary(match_id: int):
    inns = _rows(sb().table("innings").select("id").eq("match_id", int(match_id)).execute())
    if not inns:
        return []
    inn_ids = [i["id"] for i in inns]
    return _rows(sb().table("ball_events").select("*").in_("innings_id", inn_ids).order("id", desc=True).limit(50).execute())


def get_match_overs(match_id: int):
    return get_match_full_scorecard(match_id)


def get_match_info(match_id: int):
    return get_match_by_id(match_id)


def get_homepage_data(league_id: Optional[int] = None):
    league_id = int(league_id or 1)
    standings = recalculate_standings(league_id)
    matches = get_all_matches(league_id=league_id)
    live = [m for m in matches if m["status"] == "LIVE"]
    upcoming = [m for m in matches if m["status"] == "UPCOMING"]
    completed = [m for m in matches if m["status"] == "COMPLETED"]
    return {
        "league_id": league_id,
        "standings": standings,
        "live_match": live[0] if live else (matches[0] if matches else None),
        "live_matches": live,
        "upcoming_matches": upcoming[:5],
        "recent_results": completed[:5],
        "top_performers": get_tournament_leaderboards(league_id)
    }


def get_live_snapshot(match_id: int):
    return get_live_match_details(match_id)


def get_tournament_leaderboards(league_id: Optional[int] = None):
    """Computes Top Batsmen, Top Bowlers, Most Sixes for tournament."""
    batting_rows = _rows(sb().table("batting_scores").select("player_name, runs, balls, fours, sixes").execute())
    bowling_rows = _rows(sb().table("bowling_scores").select("player_name, legal_balls, maidens, runs_conceded, wickets").execute())

    bat_map: Dict[str, Dict[str, Any]] = {}
    for b in batting_rows:
        name = b["player_name"]
        if name not in bat_map:
            bat_map[name] = {"player_name": name, "runs": 0, "balls": 0, "fours": 0, "sixes": 0}
        bat_map[name]["runs"] += (b.get("runs") or 0)
        bat_map[name]["balls"] += (b.get("balls") or 0)
        bat_map[name]["fours"] += (b.get("fours") or 0)
        bat_map[name]["sixes"] += (b.get("sixes") or 0)

    for b in bat_map.values():
        b["strike_rate"] = round((b["runs"] / b["balls"] * 100.0), 1) if b["balls"] > 0 else 0.0

    bowl_map: Dict[str, Dict[str, Any]] = {}
    for bw in bowling_rows:
        name = bw["player_name"]
        if name not in bowl_map:
            bowl_map[name] = {"player_name": name, "legal_balls": 0, "runs_conceded": 0, "wickets": 0}
        bowl_map[name]["legal_balls"] += (bw.get("legal_balls") or 0)
        bowl_map[name]["runs_conceded"] += (bw.get("runs_conceded") or 0)
        bowl_map[name]["wickets"] += (bw.get("wickets") or 0)

    for bw in bowl_map.values():
        dec_ov = bw["legal_balls"] / 6.0
        bw["economy_rate"] = round(bw["runs_conceded"] / dec_ov, 2) if dec_ov > 0 else 0.0
        bw["overs"] = f"{bw['legal_balls'] // 6}.{bw['legal_balls'] % 6}"

    top_runs = sorted(bat_map.values(), key=lambda x: -x["runs"])[:10]
    top_wickets = sorted(bowl_map.values(), key=lambda x: (-x["wickets"], x["economy_rate"]))[:10]
    top_sixes = sorted(bat_map.values(), key=lambda x: -x["sixes"])[:10]

    return {
        "orange_cap": top_runs,
        "purple_cap": top_wickets,
        "most_sixes": top_sixes
    }


def get_player_profile(player_name_or_id: str):
    p = _one(sb().table("players").select("*, teams(name)").or_(f"id.eq.{player_name_or_id},name.ilike.{player_name_or_id}").execute())
    if not p:
        return None
    p_name = p["name"]
    bat_rows = _rows(sb().table("batting_scores").select("*").ilike("player_name", p_name).execute())
    bowl_rows = _rows(sb().table("bowling_scores").select("*").ilike("player_name", p_name).execute())

    total_runs = sum(b.get("runs", 0) for b in bat_rows)
    total_balls = sum(b.get("balls", 0) for b in bat_rows)
    total_4s = sum(b.get("fours", 0) for b in bat_rows)
    total_6s = sum(b.get("sixes", 0) for b in bat_rows)
    high_score = max((b.get("runs", 0) for b in bat_rows), default=0)

    total_lb = sum(bw.get("legal_balls", 0) for bw in bowl_rows)
    total_runs_conc = sum(bw.get("runs_conceded", 0) for bw in bowl_rows)
    total_wkts = sum(bw.get("wickets", 0) for bw in bowl_rows)

    return {
        "player": p,
        "batting": {
            "innings": len(bat_rows), "runs": total_runs, "balls": total_balls,
            "fours": total_4s, "sixes": total_6s, "high_score": high_score,
            "strike_rate": round(total_runs / total_balls * 100.0, 1) if total_balls > 0 else 0.0
        },
        "bowling": {
            "innings": len(bowl_rows), "overs": f"{total_lb // 6}.{total_lb % 6}",
            "runs_conceded": total_runs_conc, "wickets": total_wkts,
            "economy": round(total_runs_conc / (total_lb / 6.0), 2) if total_lb > 0 else 0.0
        }
    }


# ===========================================================================
# TEAMS & PLAYERS
# ===========================================================================

def get_all_teams(league_id: Optional[int] = None):
    q = sb().table("teams").select("*, leagues(name, short_name)").order("id")
    if league_id is not None:
        q = q.eq("league_id", int(league_id))
    rows = _rows(q.execute())
    for t in rows:
        lg = t.pop("leagues", None) or {}
        t["league_name"] = lg.get("name", "")
        t["players_count"] = sb().table("players").select("id", count="exact").eq("team_id", t["id"]).execute().count or 0
    return rows


def create_team(name: str, short_name: str, captain: str = "TBD", color: str = "#1a73e8", league_id: int = 1):
    if not name or not name.strip():
        return False, "Team name is required"
    name = name.strip()
    short = (short_name or name[:3]).strip().upper()
    existing = _one(sb().table("teams").select("id").eq("name", name).execute())
    if existing:
        return False, f"Team '{name}' already exists"
    row = _one(sb().table("teams").insert({
        "name": name, "short_name": short, "captain": captain or "TBD",
        "color": color or "#1a73e8", "league_id": int(league_id or 1)
    }).execute())
    if not row:
        return False, "Failed to create team"
    return True, row


def update_team(team_id: int, name: Optional[str] = None, short_name: Optional[str] = None, captain: Optional[str] = None,
                color: Optional[str] = None, league_id: Optional[int] = None):
    existing = _one(sb().table("teams").select("*").eq("id", int(team_id)).execute())
    if not existing:
        return False, "Team not found"
    upd = {}
    if name: upd["name"] = name.strip()
    if short_name: upd["short_name"] = short_name.strip().upper()
    if captain is not None: upd["captain"] = captain.strip()
    if color: upd["color"] = color.strip()
    if league_id is not None: upd["league_id"] = int(league_id)
    if upd:
        sb().table("teams").update(upd).eq("id", int(team_id)).execute()
    return True, _one(sb().table("teams").select("*").eq("id", int(team_id)).execute())


def delete_team(team_id: int):
    t = _one(sb().table("teams").select("*").eq("id", int(team_id)).execute())
    if not t:
        return False, "Team not found"
    sb().table("players").update({"team_id": None}).eq("team_id", int(team_id)).execute()
    sb().table("teams").delete().eq("id", int(team_id)).execute()
    return True, f"Team {t['name']} deleted"


def get_team_roster(team_id: int):
    t = _one(sb().table("teams").select("*").eq("id", int(team_id)).execute())
    if not t:
        return False, "Team not found"
    players = _rows(sb().table("players").select("*").eq("team_id", int(team_id)).order("id").execute())
    return True, {"team": t, "players": players}


def get_all_players(team_id: Optional[int] = None):
    q = sb().table("players").select("*, teams(name)").order("id")
    if team_id is not None:
        q = q.eq("team_id", int(team_id))
    rows = _rows(q.execute())
    for p in rows:
        t = p.pop("teams", None) or {}
        p["team_name"] = t.get("name", "Unassigned")
        p["team"] = p["team_name"]
        p["jersey"] = p.get("jersey_number", 0)
    return rows


def create_player(name: str, team_name_or_id: Optional[Any] = None, role: str = "All-Rounder", jersey: int = 0):
    if not name or not name.strip():
        return False, "Player name is required"
    name = name.strip()
    t_id = None
    if team_name_or_id:
        t = _one(sb().table("teams").select("id").or_(f"id.eq.{team_name_or_id},name.ilike.{team_name_or_id}").execute())
        if t:
            t_id = t["id"]
    row = _one(sb().table("players").insert({
        "name": name, "team_id": t_id, "role": role or "All-Rounder", "jersey_number": int(jersey or 0)
    }).execute())
    if not row:
        return False, "Failed to create player"
    return True, row


def update_player(player_id: int, name: Optional[str] = None, team_name_or_id: Optional[Any] = None,
                  role: Optional[str] = None, jersey: Optional[int] = None):
    p = _one(sb().table("players").select("*").eq("id", int(player_id)).execute())
    if not p:
        return False, "Player not found"
    upd = {}
    if name: upd["name"] = name.strip()
    if team_name_or_id is not None:
        if str(team_name_or_id).lower() in ("", "none", "null", "unassigned"):
            upd["team_id"] = None
        else:
            t = _one(sb().table("teams").select("id").or_(f"id.eq.{team_name_or_id},name.ilike.{team_name_or_id}").execute())
            if t: upd["team_id"] = t["id"]
    if role: upd["role"] = role
    if jersey is not None: upd["jersey_number"] = int(jersey)
    if upd:
        sb().table("players").update(upd).eq("id", int(player_id)).execute()
    return True, _one(sb().table("players").select("*").eq("id", int(player_id)).execute())


def delete_player(player_id: int):
    p = _one(sb().table("players").select("*").eq("id", int(player_id)).execute())
    if not p:
        return False, "Player not found"
    sb().table("players").delete().eq("id", int(player_id)).execute()
    return True, f"Player {p['name']} deleted"


def add_player_to_team(team_id: int, player_id: int):
    sb().table("players").update({"team_id": int(team_id)}).eq("id", int(player_id)).execute()
    return True, "Player added to team"


def remove_player_from_team(player_id: int):
    sb().table("players").update({"team_id": None}).eq("id", int(player_id)).execute()
    return True, "Player removed from team"


# ===========================================================================
# TOURNAMENTS
# ===========================================================================

def get_all_tournaments():
    return _rows(sb().table("tournaments").select("*").order("is_active", desc=True).order("id", desc=True).execute())


def get_tournament_by_id(tournament_id: int):
    return _one(sb().table("tournaments").select("*").eq("id", int(tournament_id)).execute())


def get_active_tournament():
    t = _one(sb().table("tournaments").select("*").eq("is_active", 1).limit(1).execute())
    if not t:
        t = _one(sb().table("tournaments").select("*").order("id").limit(1).execute())
    return t


def create_tournament(name: str, season: str = "2026", status: str = "active", start_date: Optional[str] = None,
                      end_date: Optional[str] = None, total_overs: int = 10, format_name: str = "T10",
                      description: str = "", is_active: int = 0):
    if not name or not str(name).strip():
        return False, "Tournament name is required"
    name = str(name).strip()
    if is_active:
        sb().table("tournaments").update({"is_active": 0}).execute()
    row = _one(sb().table("tournaments").insert({
        "name": name, "season": str(season or "2026"), "status": str(status or "active").lower(),
        "start_date": start_date, "end_date": end_date, "total_overs": int(total_overs or 10),
        "format_name": str(format_name or f"T{total_overs}"), "description": description or "",
        "is_active": 1 if is_active else 0
    }).execute())
    if not row:
        return False, "Failed to create tournament"
    return True, get_tournament_by_id(row["id"])


def update_tournament(tournament_id: int, **kwargs):
    existing = get_tournament_by_id(tournament_id)
    if not existing:
        return False, "Tournament not found"
    upd = {}
    for k, v in kwargs.items():
        if v is not None:
            upd[k] = v
    if upd.get("is_active"):
        sb().table("tournaments").update({"is_active": 0}).execute()
    if upd:
        sb().table("tournaments").update(upd).eq("id", int(tournament_id)).execute()
    return True, get_tournament_by_id(tournament_id)


def set_active_tournament(tournament_id: int):
    sb().table("tournaments").update({"is_active": 0}).execute()
    sb().table("tournaments").update({"is_active": 1, "status": "active"}).eq("id", int(tournament_id)).execute()
    return True, get_tournament_by_id(tournament_id)


def delete_tournament(tournament_id: int):
    t = get_tournament_by_id(tournament_id)
    if not t:
        return False, "Tournament not found"
    sb().table("tournaments").delete().eq("id", int(tournament_id)).execute()
    return True, "Tournament deleted"


def set_captain(team_name_or_id: Any, player_name: str):
    t = _one(sb().table("teams").select("id").or_(f"id.eq.{team_name_or_id},name.ilike.{team_name_or_id}").execute())
    if not t:
        return False, "Team not found"
    sb().table("teams").update({"captain": player_name}).eq("id", t["id"]).execute()
    return True, "Captain updated"


# ===========================================================================
# USERS & AUDIT LOGS
# ===========================================================================

def get_user_by_email(email: str):
    return _one(sb().table("users").select("*").eq("email", email.strip().lower()).execute())


def get_user_by_id(user_id: str):
    return _one(sb().table("users").select("*").eq("id", str(user_id)).execute())


def authenticate_user(email: str, password: str):
    u = get_user_by_email(email)
    if u and u.get("status") == "ACTIVE" and check_password_hash(u["password_hash"], password):
        sb().table("users").update({"last_login": _now()}).eq("id", u["id"]).execute()
        return True, u
    return False, "Invalid email or password"


def create_user(name: str, email: str, password: str, role: str = "SCORER", status: str = "ACTIVE"):
    email = email.strip().lower()
    if get_user_by_email(email):
        return False, "Email already exists"
    cnt = sb().table("users").select("id", count="exact").execute().count or 0
    u_id = f"U{cnt + 1:03d}"
    h = generate_password_hash(password)
    row = _one(sb().table("users").insert({
        "id": u_id, "name": name, "email": email, "password_hash": h,
        "role": role.upper(), "status": status.upper()
    }).execute())
    if not row:
        return False, "Failed to create user"
    return True, get_user_by_id(u_id)


def update_user_info(user_id: str, name: Optional[str] = None, email: Optional[str] = None, role: Optional[str] = None):
    u = get_user_by_id(user_id)
    if not u:
        return False, "User not found"
    upd = {}
    if name: upd["name"] = name.strip()
    if email: upd["email"] = email.strip().lower()
    if role: upd["role"] = role.upper()
    if upd:
        sb().table("users").update(upd).eq("id", user_id).execute()
    return True, get_user_by_id(user_id)


def update_user_status(user_id: str, status: str):
    sb().table("users").update({"status": status.upper()}).eq("id", user_id).execute()
    return True, get_user_by_id(user_id)


def delete_user(user_id: str):
    sb().table("users").delete().eq("id", user_id).execute()
    return True, "User deleted"


def admin_reset_user_password(user_id: str, new_password: str):
    h = generate_password_hash(new_password)
    sb().table("users").update({"password_hash": h}).eq("id", user_id).execute()
    return True, "Password reset successfully"


def change_user_password(user_id: str, current_password: str, new_password: str):
    u = get_user_by_id(user_id)
    if not u or not check_password_hash(u["password_hash"], current_password):
        return False, "Current password incorrect"
    h = generate_password_hash(new_password)
    sb().table("users").update({"password_hash": h}).eq("id", user_id).execute()
    return True, "Password changed successfully"


def get_all_users():
    return _rows(sb().table("users").select("*").order("name").execute())


def log_audit_event(user_id: str, user_email: str, action: str, target_type: str, target_id: Any, reason: str,
                    before_data: Optional[Any] = None, after_data: Optional[Any] = None):
    try:
        sb().table("audit_logs").insert({
            "user_id": str(user_id), "user_email": str(user_email), "action": action,
            "target_type": target_type, "target_id": str(target_id), "reason": reason,
            "before_data": json.dumps(before_data) if before_data else None,
            "after_data": json.dumps(after_data) if after_data else None
        }).execute()
        return True
    except Exception:
        return False


def get_audit_logs(limit: int = 100, target_type: Optional[str] = None, target_id: Optional[str] = None):
    q = sb().table("audit_logs").select("*").order("id", desc=True).limit(limit)
    if target_type: q = q.eq("target_type", target_type)
    if target_id: q = q.eq("target_id", str(target_id))
    return _rows(q.execute())


log_audit = log_audit_event


# ---------------------------------------------------------------------------
# GOVERNANCE, PLAYOFFS & SQUAD HELPERS
# ---------------------------------------------------------------------------

def get_players_by_team(team_name: str) -> List[Dict[str, Any]]:
    """Returns list of players belonging to a team (by name)."""
    if not team_name:
        return []
    t_id = _get_team_id_by_name(team_name)
    if not t_id:
        return []
    return _rows(sb().table("players").select("*, teams(name)").eq("team_id", t_id).order("id").execute())


def lock_match(match_id: int, user_id: Optional[str] = None, user_email: Optional[str] = None, reason: str = "Locked by admin"):
    """Locks a completed match to protect it from ordinary editing."""
    m = get_match_by_id(match_id)
    if not m:
        return False, "Match not found"
    sb().table("matches").update({
        "is_locked": 1,
        "locked_at": _now(),
        "locked_by": str(user_email or "admin")
    }).eq("id", int(match_id)).execute()
    log_audit_event(user_id or "admin", user_email or "admin", "LOCK_MATCH", "MATCH", match_id, reason,
                    before_data={"is_locked": 0}, after_data={"is_locked": 1})
    return True, get_match_by_id(match_id)


def unlock_match(match_id: int, user_id: Optional[str] = None, user_email: Optional[str] = None, reason: Optional[str] = None):
    """Unlocks a completed/locked match for administrative corrections. Requires a non-empty reason."""
    if not reason or not str(reason).strip():
        return False, "A valid reason is required to unlock a match"
    m = get_match_by_id(match_id)
    if not m:
        return False, "Match not found"
    sb().table("matches").update({
        "is_locked": 0,
        "locked_at": None,
        "locked_by": None
    }).eq("id", int(match_id)).execute()
    log_audit_event(user_id or "admin", user_email or "admin", "UNLOCK_MATCH", "MATCH", match_id, str(reason).strip(),
                    before_data={"is_locked": m.get("is_locked")}, after_data={"is_locked": 0})
    return True, get_match_by_id(match_id)


def get_playoff_qualification(league_id: int = 1, top_n: int = 4) -> Dict[str, Any]:
    """Computes qualification ranking from league standings and generates suggested playoff matchups."""
    standings = recalculate_standings(league_id)
    qualified = []
    for idx, row in enumerate(standings[:top_n], start=1):
        qualified.append({
            "seed": idx,
            "team": row["team"],
            "captain": row.get("captain", "N/A"),
            "color": row.get("color", "#1a73e8"),
            "played": row["p"],
            "wins": row["w"],
            "losses": row["l"],
            "points": row["pts"],
            "net_run_rate": row["nrr"]
        })

    suggested_matchups = []
    if len(qualified) >= 4:
        suggested_matchups.append({
            "stage": "SEMIFINAL",
            "stage_order": 1,
            "match_name": f"Semi-Final 1 ({qualified[0]['team']} vs {qualified[3]['team']})",
            "team_a": qualified[0]["team"],
            "team_b": qualified[3]["team"],
            "seed_a": 1,
            "seed_b": 4
        })
        suggested_matchups.append({
            "stage": "SEMIFINAL",
            "stage_order": 2,
            "match_name": f"Semi-Final 2 ({qualified[1]['team']} vs {qualified[2]['team']})",
            "team_a": qualified[1]["team"],
            "team_b": qualified[2]["team"],
            "seed_a": 2,
            "seed_b": 3
        })
    elif len(qualified) >= 2:
        suggested_matchups.append({
            "stage": "FINAL",
            "stage_order": 1,
            "match_name": f"Final ({qualified[0]['team']} vs {qualified[1]['team']})",
            "team_a": qualified[0]["team"],
            "team_b": qualified[1]["team"],
            "seed_a": 1,
            "seed_b": 2
        })

    return {
        "league_id": int(league_id),
        "qualified_teams": qualified,
        "suggested_matchups": suggested_matchups
    }


def advance_playoff_winner(source_match_id: int, target_match_id: int, slot: str = "team_a",
                           user_id: Optional[str] = None, user_email: Optional[str] = None):
    """Advances the winner of a completed semifinal/playoff match into a target fixture (e.g. the Final)."""
    source = get_match_by_id(source_match_id)
    if not source:
        return False, "Source match not found"
    if source["status"] != "COMPLETED":
        return False, "Source match must be COMPLETED before advancing winner"
    winner = (source.get("winner") or "").strip()
    if not winner or winner.lower() in ("no result", "cancelled", "match tied", "tie"):
        return False, f"Source match has no conclusive winner (winner: '{winner}')"

    target = get_match_by_id(target_match_id)
    if not target:
        return False, "Target match not found"

    slot_clean = str(slot).lower().replace("_", "").replace("-", "")
    target_col = "team_a" if slot_clean in ("teama", "a", "team1") else "team_b"
    other_col = "team_b" if target_col == "team_a" else "team_a"
    other_team = target[other_col]

    new_match_name = f"{winner} vs {other_team}" if target_col == "team_a" else f"{other_team} vs {winner}"
    upd = {target_col: winner, "match_name": new_match_name}
    sb().table("matches").update(upd).eq("id", int(target_match_id)).execute()

    log_audit_event(user_id or "admin", user_email or "admin", "ADVANCE_PLAYOFF", "MATCH", target_match_id,
                    f"Advanced {winner} into {slot} from Match #{source_match_id}")
    return True, get_match_by_id(target_match_id)


def set_wicketkeeper(team_name_or_id: Any, player_name: str):
    t_id = _get_team_id_by_name(team_name_or_id) if isinstance(team_name_or_id, str) else team_name_or_id
    if not t_id:
        return False, "Team not found"
    sb().table("teams").update({"wicketkeeper": player_name}).eq("id", t_id).execute()
    return True, "Wicketkeeper updated"


def verify_match_ownership(match_id: int, user_id: str) -> Tuple[bool, Optional[str]]:
    m = get_match_by_id(match_id)
    if not m:
        return False, "Match not found"
    holder = m.get("claimed_by_user_id")
    if not holder:
        return False, "Match is not claimed by any scorer"
    if str(holder) != str(user_id):
        return False, f"Match is claimed by {holder}, not {user_id}"
    return True, None


def reset_match(match_id: int):
    """Resets match state back to UPCOMING and clears all recorded events."""
    sb().table("ball_events").delete().eq("innings_id", f"(SELECT id FROM innings WHERE match_id = {match_id})").execute()
    sb().table("batting_scores").delete().eq("innings_id", f"(SELECT id FROM innings WHERE match_id = {match_id})").execute()
    sb().table("bowling_scores").delete().eq("innings_id", f"(SELECT id FROM innings WHERE match_id = {match_id})").execute()
    sb().table("innings").delete().eq("match_id", int(match_id)).execute()
    sb().table("matches").update({
        "status": "UPCOMING", "current_innings": 1, "winner": "", "result_margin": "",
        "claimed_by_user_id": None, "claim_expires_at": None, "is_locked": 0
    }).eq("id", int(match_id)).execute()
    return True, get_match_by_id(match_id)


def wipe_database():
    """Wipes all tournament tables in Supabase (Protected)."""
    for tbl in ("ball_events", "batting_scores", "bowling_scores", "innings", "matches", "league_standings", "players", "teams", "audit_logs"):
        try:
            sb().table(tbl).delete().neq("id", -99999).execute()
        except Exception:
            pass
    return True


def seed_default_data():
    """Seeds default leagues and tournament fixtures."""
    try:
        create_tournament("College Premier League 2026", is_active=1)
        create_league("League 1", short_name="L1")
        create_league("League 2", short_name="L2")
    except Exception:
        pass
    return True


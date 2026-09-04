"""
CSD & CSIT Cricket — Authoritative Cricket Rules & Scoring Engine
Pure Python domain engine: encapsulates all cricket laws, state transitions,
delivery classifications, strike calculations, event replay, and result determinations.
"""

from typing import Dict, List, Optional, Tuple, Any
import math


class MatchConfig:
    def __init__(self, total_overs: int = 10, players_per_team: int = 11, balls_per_over: int = 6):
        self.total_overs = int(total_overs or 10)
        self.players_per_team = int(players_per_team or 11)
        self.balls_per_over = int(balls_per_over or 6)
        self.max_wickets = max(1, self.players_per_team - 1)
        self.max_legal_balls = self.total_overs * self.balls_per_over

    @classmethod
    def from_match_dict(cls, match: Dict[str, Any]) -> "MatchConfig":
        total_overs = match.get("total_overs") or match.get("overs") or 10
        players_per_team = match.get("players_per_team")
        if not players_per_team:
            players_per_team = 8 if total_overs == 6 else 11
        balls_per_over = match.get("balls_per_over") or 6
        return cls(total_overs=total_overs, players_per_team=players_per_team, balls_per_over=balls_per_over)


# Valid dismissal types according to MCC Laws of Cricket
VALID_DISMISSAL_TYPES = {
    "BOWLED", "CAUGHT", "LBW", "STUMPED", "RUN_OUT", "RUN OUT",
    "HIT_WICKET", "HIT WICKET", "RETIRED_HURT", "RETIRED HURT",
    "OBSTRUCTING_FIELD", "TIMED_OUT", "HANDLED_BALL"
}

# Dismissals where bowler gets credit
BOWLER_CREDITED_DISMISSALS = {
    "BOWLED", "CAUGHT", "LBW", "STUMPED", "HIT_WICKET", "HIT WICKET"
}

# Dismissals PERMITTED on a No Ball (MCC Law 21.18)
NO_BALL_PERMITTED_DISMISSALS = {
    "RUN_OUT", "RUN OUT", "OBSTRUCTING_FIELD", "RETIRED_HURT", "RETIRED HURT"
}


def normalize_extra_type(extra: Optional[str]) -> Optional[str]:
    if not extra:
        return None
    e = str(extra).strip().upper().replace("-", " ")
    if e in ("WD", "WIDE", "WIDES"):
        return "WIDE"
    if e in ("NB", "NO BALL", "NOBALL", "NO_BALL"):
        return "NO BALL"
    if e in ("B", "BYE", "BYES"):
        return "BYE"
    if e in ("LB", "LEG BYE", "LEGBYE", "LEG_BYE"):
        return "LEG BYE"
    if e in ("PENALTY", "PENALTY RUNS"):
        return "PENALTY"
    return None


def is_legal_delivery(extra_type: Optional[str]) -> bool:
    norm = normalize_extra_type(extra_type)
    return norm not in ("WIDE", "NO BALL")


def validate_dismissal_on_delivery(wicket_type: Optional[str], extra_type: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Validates whether a dismissal type is legally allowed given the delivery extra type."""
    if not wicket_type:
        return True, None
    wt = str(wicket_type).strip().upper().replace("-", " ")
    et = normalize_extra_type(extra_type)
    if wt not in VALID_DISMISSAL_TYPES:
        return False, f"Invalid dismissal type '{wicket_type}'"
    if et == "NO BALL" and wt not in NO_BALL_PERMITTED_DISMISSALS:
        return False, f"Batsman cannot be dismissed '{wicket_type}' off a No Ball (only Run Out / Obstructing Field allowed)"
    return True, None


def balls_to_overs_display(legal_balls: int, balls_per_over: int = 6) -> str:
    """Converts total legal balls into standard cricket overs string e.g. 58 -> '9.4'."""
    overs = legal_balls // balls_per_over
    rem = legal_balls % balls_per_over
    return f"{overs}.{rem}"


def balls_to_decimal_overs(legal_balls: int, balls_per_over: int = 6) -> float:
    """Converts total legal balls into mathematical decimal overs for run rates and NRR."""
    if legal_balls <= 0:
        return 0.0
    return legal_balls / float(balls_per_over)


def calculate_run_rate(runs: int, legal_balls: int, balls_per_over: int = 6) -> float:
    """Calculates Current Run Rate (CRR)."""
    dec_overs = balls_to_decimal_overs(legal_balls, balls_per_over)
    if dec_overs <= 0.0:
        return 0.0
    return round(runs / dec_overs, 2)


def calculate_required_run_rate(runs_needed: int, balls_remaining: int, balls_per_over: int = 6) -> float:
    """Calculates Required Run Rate (RRR)."""
    if runs_needed <= 0:
        return 0.0
    if balls_remaining <= 0:
        return 999.99
    dec_overs = balls_to_decimal_overs(balls_remaining, balls_per_over)
    return round(runs_needed / dec_overs, 2)


def replay_innings_events(
    match_config: MatchConfig,
    innings_info: Dict[str, Any],
    ball_events: List[Dict[str, Any]],
    initial_striker: Optional[str] = None,
    initial_non_striker: Optional[str] = None,
    initial_bowler: Optional[str] = None
) -> Dict[str, Any]:
    """
    Pure event-sourced replay engine:
    Reconstructs complete, authoritative innings state from chronological ball_events.
    """
    bpo = match_config.balls_per_over
    max_wickets = match_config.max_wickets
    max_legal_balls = match_config.max_legal_balls

    # 1. Initialize Batsmen & Bowlers Tracking
    batsmen: Dict[str, Dict[str, Any]] = {}
    bowlers: Dict[str, Dict[str, Any]] = {}
    batting_order = 0

    def get_or_create_batsman(name: str, p_id: Optional[Any] = None) -> Dict[str, Any]:
        nonlocal batting_order
        if name not in batsmen:
            batting_order += 1
            batsmen[name] = {
                "player_name": name,
                "player_id": p_id,
                "runs": 0,
                "balls": 0,
                "fours": 0,
                "sixes": 0,
                "strike_rate": 0.0,
                "is_out": False,
                "dismissal_info": "not out",
                "dismissal_type": None,
                "bowler_name": None,
                "fielder_name": None,
                "is_on_strike": False,
                "batting_order": batting_order
            }
        elif p_id and not batsmen[name].get("player_id"):
            batsmen[name]["player_id"] = p_id
        return batsmen[name]

    def get_or_create_bowler(name: str, p_id: Optional[Any] = None) -> Dict[str, Any]:
        if name not in bowlers:
            bowlers[name] = {
                "player_name": name,
                "player_id": p_id,
                "legal_balls": 0,
                "overs": 0,
                "balls": 0,
                "maidens": 0,
                "runs_conceded": 0,
                "wickets": 0,
                "economy_rate": 0.0,
                "is_current_bowler": False
            }
        elif p_id and not bowlers[name].get("player_id"):
            bowlers[name]["player_id"] = p_id
        return bowlers[name]

    # Pre-register opening pair if provided
    striker_name = initial_striker.strip() if initial_striker and initial_striker.strip() else None
    non_striker_name = initial_non_striker.strip() if initial_non_striker and initial_non_striker.strip() else None
    current_bowler_name = initial_bowler.strip() if initial_bowler and initial_bowler.strip() else None

    if striker_name:
        get_or_create_batsman(striker_name)
    if non_striker_name:
        get_or_create_batsman(non_striker_name)
    if current_bowler_name:
        get_or_create_bowler(current_bowler_name)

    total_runs = 0
    total_wickets = 0
    total_legal_balls = 0
    total_extras = 0
    extras_breakdown = {"wides": 0, "no_balls": 0, "byes": 0, "leg_byes": 0, "penalty": 0}

    # Tracking overs and maiden overs
    current_over_events: List[Dict[str, Any]] = []
    current_over_runs_conceded = 0
    recent_deliveries: List[Dict[str, Any]] = []

    # Target chase tracking for 2nd innings
    target = innings_info.get("target")
    is_second_innings = (innings_info.get("innings_number") == 2) or bool(target)

    # 2. Sequential Replay of Ball Events
    for ev in ball_events:
        b_name = (ev.get("batsman_name") or striker_name or "Striker").strip()
        bw_name = (ev.get("bowler_name") or current_bowler_name or "Bowler").strip()
        p_bat_id = ev.get("batsman_id") or ev.get("player_id")
        p_bowl_id = ev.get("bowler_id")

        b_stat = get_or_create_batsman(b_name, p_bat_id)
        bw_stat = get_or_create_bowler(bw_name, p_bowl_id)
        current_bowler_name = bw_name

        # Ensure active pair tracking
        if not striker_name:
            striker_name = b_name
        elif b_name != striker_name and b_name != non_striker_name:
            # If a different batter faces ball, update striker
            striker_name = b_name

        runs = int(ev.get("runs") or 0)
        extras = int(ev.get("extras") or 0)
        extra_type = normalize_extra_type(ev.get("extra_type"))
        is_wicket = bool(ev.get("wicket") or int(ev.get("wicket") or 0) == 1)
        w_type = (ev.get("wicket_type") or "").strip().upper().replace("-", " ") if is_wicket else None
        out_player = (ev.get("out_player_name") or b_name).strip() if is_wicket else None
        fielder_name = (ev.get("fielder_name") or "").strip() or None

        is_legal = is_legal_delivery(extra_type)

        # Runs computation
        team_score_for_ball = runs + extras
        total_runs += team_score_for_ball
        total_extras += extras

        # Bowler runs conceded (Byes and Leg-Byes are not charged to bowler)
        bowler_conceded_for_ball = 0
        if extra_type in ("BYE", "LEG BYE"):
            bowler_conceded_for_ball = 0
        else:
            bowler_conceded_for_ball = runs + extras
        bw_stat["runs_conceded"] += bowler_conceded_for_ball
        current_over_runs_conceded += bowler_conceded_for_ball

        # Extras breakdown
        if extra_type == "WIDE":
            extras_breakdown["wides"] += extras
        elif extra_type == "NO BALL":
            extras_breakdown["no_balls"] += extras
        elif extra_type == "BYE":
            extras_breakdown["byes"] += extras
        elif extra_type == "LEG BYE":
            extras_breakdown["leg_byes"] += extras
        elif extra_type == "PENALTY":
            extras_breakdown["penalty"] += extras

        # Batsman balls faced and runs
        if extra_type != "WIDE":
            b_stat["balls"] += 1

        if extra_type not in ("BYE", "LEG BYE", "WIDE"):
            b_stat["runs"] += runs
            if runs == 4:
                b_stat["fours"] += 1
            elif runs == 6:
                b_stat["sixes"] += 1

        # Legal balls count
        if is_legal:
            total_legal_balls += 1
            bw_stat["legal_balls"] += 1

        # Wicket processing
        incoming_batter_for_next = (ev.get("new_batter_name") or "").strip() or None
        if is_wicket:
            total_wickets += 1
            out_stat = get_or_create_batsman(out_player)
            out_stat["is_out"] = True
            out_stat["dismissal_type"] = w_type

            # Format dismissal string
            if w_type == "BOWLED":
                out_stat["dismissal_info"] = f"b {bw_name}"
            elif w_type == "CAUGHT":
                out_stat["dismissal_info"] = f"c {fielder_name} b {bw_name}" if fielder_name else f"c & b {bw_name}"
            elif w_type == "LBW":
                out_stat["dismissal_info"] = f"lbw b {bw_name}"
            elif w_type == "STUMPED":
                out_stat["dismissal_info"] = f"st {fielder_name} b {bw_name}" if fielder_name else f"st b {bw_name}"
            elif w_type in ("RUN_OUT", "RUN OUT"):
                out_stat["dismissal_info"] = f"run out ({fielder_name})" if fielder_name else "run out"
            elif w_type in ("HIT_WICKET", "HIT WICKET"):
                out_stat["dismissal_info"] = f"hit wicket b {bw_name}"
            elif w_type in ("RETIRED_HURT", "RETIRED HURT"):
                out_stat["dismissal_info"] = "retired hurt"
            else:
                out_stat["dismissal_info"] = f"{w_type.lower()}"

            out_stat["bowler_name"] = bw_name
            out_stat["fielder_name"] = fielder_name

            # Credit bowler if applicable
            if w_type in BOWLER_CREDITED_DISMISSALS:
                bw_stat["wickets"] += 1

            # Vacate the dismissed batter's end
            vacated_end = "striker" if out_player == striker_name else "non_striker"
            if vacated_end == "striker":
                striker_name = None
            else:
                non_striker_name = None

            # If an incoming batter was specified, assign immediately to vacated slot
            if incoming_batter_for_next and total_wickets < max_wickets:
                get_or_create_batsman(incoming_batter_for_next)
                if vacated_end == "striker":
                    striker_name = incoming_batter_for_next
                else:
                    non_striker_name = incoming_batter_for_next

        # 3. Strike Rotation Rules
        # Physical runs completed:
        # On Normal / No Ball: runs off bat
        # On Bye / Leg Bye: extras are the physical runs
        # On Wide: runs ran beyond the 1-wide penalty (ev.runs or extras - 1)
        physical_runs = 0
        if extra_type in ("BYE", "LEG BYE"):
            physical_runs = extras
        elif extra_type == "WIDE":
            physical_runs = max(0, team_score_for_ball - 1)
        else:
            physical_runs = runs

        if (physical_runs % 2 == 1) and striker_name and non_striker_name:
            striker_name, non_striker_name = non_striker_name, striker_name

        # 4. Over End Detection & Maiden Checks
        current_over_events.append(ev)
        if is_legal and (total_legal_balls % bpo == 0):
            # Over completed: check for maiden over
            if current_over_runs_conceded == 0 and len([e for e in current_over_events if is_legal_delivery(e.get("extra_type"))]) == bpo:
                bw_stat["maidens"] += 1
            current_over_runs_conceded = 0
            current_over_events = []

            # Swap strike at end of over (MCC Law 18.11)
            if striker_name and non_striker_name:
                striker_name, non_striker_name = non_striker_name, striker_name

        # Track display delivery string
        disp = str(runs)
        if is_wicket:
            disp = "W"
        elif extra_type == "WIDE":
            disp = f"Wd{'+' + str(physical_runs) if physical_runs > 0 else ''}"
        elif extra_type == "NO BALL":
            disp = f"Nb{'+' + str(runs) if runs > 0 else ''}"
        elif extra_type == "BYE":
            disp = f"B{extras}"
        elif extra_type == "LEG BYE":
            disp = f"Lb{extras}"

        recent_deliveries.append({
            "display": disp,
            "runs": runs,
            "extras": extras,
            "extra_type": extra_type,
            "wicket": is_wicket,
            "batsman": b_name,
            "bowler": bw_name
        })

    # 5. Finalize Stats (Strike Rates & Economy Rates)
    for b_name, b_info in batsmen.items():
        if b_info["balls"] > 0:
            b_info["strike_rate"] = round((b_info["runs"] / float(b_info["balls"])) * 100.0, 1)
        else:
            b_info["strike_rate"] = 0.0
        b_info["is_on_strike"] = bool(striker_name and b_name == striker_name and not b_info["is_out"])

    for bw_name, bw_info in bowlers.items():
        bw_lb = bw_info["legal_balls"]
        bw_info["overs"] = bw_lb // bpo
        bw_info["balls"] = bw_lb % bpo
        bw_dec_overs = balls_to_decimal_overs(bw_lb, bpo)
        if bw_dec_overs > 0.0:
            bw_info["economy_rate"] = round(bw_info["runs_conceded"] / bw_dec_overs, 2)
        else:
            bw_info["economy_rate"] = 0.0
        bw_info["is_current_bowler"] = bool(current_bowler_name and bw_name == current_bowler_name)

    # 6. Automatic Innings Completion Evaluation
    completed_overs = total_legal_balls // bpo
    balls_in_over = total_legal_balls % bpo
    overs_display = f"{completed_overs}.{balls_in_over}"

    is_completed = False
    completion_reason = None

    if is_second_innings and target is not None:
        if total_runs >= target:
            is_completed = True
            completion_reason = "TARGET_CHASED"
        elif total_wickets >= max_wickets:
            is_completed = True
            completion_reason = "ALL_OUT"
        elif total_legal_balls >= max_legal_balls:
            is_completed = True
            completion_reason = "OVERS_EXHAUSTED"
    else:
        if total_wickets >= max_wickets:
            is_completed = True
            completion_reason = "ALL_OUT"
        elif total_legal_balls >= max_legal_balls:
            is_completed = True
            completion_reason = "OVERS_EXHAUSTED"

    status = "COMPLETED" if is_completed else "ACTIVE"

    # Current over balls for display strip
    this_over_pills = recent_deliveries[-(balls_in_over if balls_in_over > 0 else (bpo if total_legal_balls > 0 else 0)):] if total_legal_balls > 0 else []

    # Sort batsmen by batting order
    sorted_batters = sorted(batsmen.values(), key=lambda x: x["batting_order"])
    sorted_bowlers = list(bowlers.values())

    active_striker_obj = next((b for b in sorted_batters if b["player_name"] == striker_name and not b["is_out"]), None)
    active_non_striker_obj = next((b for b in sorted_batters if b["player_name"] == non_striker_name and not b["is_out"]), None)
    active_bowler_obj = next((bw for bw in sorted_bowlers if bw["player_name"] == current_bowler_name), None)

    return {
        "runs": total_runs,
        "wickets": total_wickets,
        "legal_balls": total_legal_balls,
        "overs": completed_overs,
        "balls": balls_in_over,
        "overs_display": overs_display,
        "total_extras": total_extras,
        "extras_breakdown": extras_breakdown,
        "status": status,
        "is_completed": is_completed,
        "completion_reason": completion_reason,
        "target": target,
        "crr": calculate_run_rate(total_runs, total_legal_balls, bpo),
        "striker_name": striker_name,
        "non_striker_name": non_striker_name,
        "current_bowler_name": current_bowler_name,
        "striker": active_striker_obj,
        "non_striker": active_non_striker_obj,
        "current_bowler": active_bowler_obj,
        "batting_performances": sorted_batters,
        "bowling_performances": sorted_bowlers,
        "recent_deliveries": recent_deliveries[-12:],
        "current_over_balls": this_over_pills
    }


def evaluate_match_result(
    match_config: MatchConfig,
    inn1_summary: Dict[str, Any],
    inn2_summary: Optional[Dict[str, Any]],
    team_a: str,
    team_b: str
) -> Dict[str, Any]:
    """
    Evaluates final match outcome, winner, loser, and margin string.
    """
    if not inn2_summary or not inn2_summary.get("is_completed"):
        return {
            "status": "LIVE",
            "is_completed": False,
            "winner": None,
            "loser": None,
            "result_margin": "",
            "result_type": None
        }

    target = inn2_summary.get("target") or (inn1_summary.get("runs", 0) + 1)
    inn1_runs = inn1_summary.get("runs", 0)
    inn2_runs = inn2_summary.get("runs", 0)
    inn2_wickets = inn2_summary.get("wickets", 0)
    max_wickets = match_config.max_wickets

    batting_second_team = inn2_summary.get("batting_team") or team_b
    batting_first_team = inn1_summary.get("batting_team") or team_a

    if inn2_runs >= target:
        wickets_left = max(0, max_wickets - inn2_wickets)
        margin = f"by {wickets_left} wicket{'s' if wickets_left != 1 else ''}"
        return {
            "status": "COMPLETED",
            "is_completed": True,
            "winner": batting_second_team,
            "loser": batting_first_team,
            "result_margin": margin,
            "result_type": "WICKETS"
        }
    elif inn2_runs == (target - 1):
        return {
            "status": "COMPLETED",
            "is_completed": True,
            "winner": "Match Tied",
            "loser": None,
            "result_margin": "Match tied",
            "result_type": "TIE"
        }
    else:
        runs_diff = inn1_runs - inn2_runs
        margin = f"by {runs_diff} run{'s' if runs_diff != 1 else ''}"
        return {
            "status": "COMPLETED",
            "is_completed": True,
            "winner": batting_first_team,
            "loser": batting_second_team,
            "result_margin": margin,
            "result_type": "RUNS"
        }

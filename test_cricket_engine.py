"""
Unit tests for pure Python cricket_engine.py
"""

import unittest
from cricket_engine import (
    MatchConfig,
    is_legal_delivery,
    validate_dismissal_on_delivery,
    replay_innings_events,
    evaluate_match_result,
    balls_to_overs_display,
    balls_to_decimal_overs,
    calculate_run_rate,
    calculate_required_run_rate
)


class TestCricketEngine(unittest.TestCase):

    def setUp(self):
        self.config_t10 = MatchConfig(total_overs=10, players_per_team=11, balls_per_over=6)
        self.config_t6 = MatchConfig(total_overs=6, players_per_team=8, balls_per_over=6)

    def test_overs_display_and_decimal_math(self):
        self.assertEqual(balls_to_overs_display(58), "9.4")
        self.assertEqual(balls_to_overs_display(60), "10.0")
        self.assertEqual(balls_to_overs_display(0), "0.0")
        self.assertEqual(balls_to_overs_display(5), "0.5")

        # Decimal overs math: 58 balls is 9 + 4/6 = 9.666666...
        self.assertAlmostEqual(balls_to_decimal_overs(58), 9.666666, places=4)
        self.assertEqual(balls_to_decimal_overs(60), 10.0)

        # Run rate
        self.assertEqual(calculate_run_rate(80, 58), 8.28)
        self.assertEqual(calculate_run_rate(60, 36), 10.0)

        # RRR
        self.assertEqual(calculate_required_run_rate(20, 12), 10.0)

    def test_legal_delivery_classification(self):
        self.assertTrue(is_legal_delivery(None))
        self.assertTrue(is_legal_delivery(""))
        self.assertTrue(is_legal_delivery("BYE"))
        self.assertTrue(is_legal_delivery("LEG BYE"))
        self.assertFalse(is_legal_delivery("WIDE"))
        self.assertFalse(is_legal_delivery("NO BALL"))

    def test_dismissal_validation_on_no_ball(self):
        # Bowled on No Ball is INVALID
        ok, err = validate_dismissal_on_delivery("BOWLED", "NO BALL")
        self.assertFalse(ok)
        self.assertIn("No Ball", err)

        # Caught on No Ball is INVALID
        ok, err = validate_dismissal_on_delivery("CAUGHT", "NO BALL")
        self.assertFalse(ok)

        # LBW on No Ball is INVALID
        ok, err = validate_dismissal_on_delivery("LBW", "NO BALL")
        self.assertFalse(ok)

        # Stumped on No Ball is INVALID
        ok, err = validate_dismissal_on_delivery("STUMPED", "NO BALL")
        self.assertFalse(ok)

        # Run Out on No Ball is VALID
        ok, err = validate_dismissal_on_delivery("RUN_OUT", "NO BALL")
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_strike_rotation_and_boundaries(self):
        # Initial pair: Alice & Bob. Bowler: Charlie
        events = [
            {"batsman_name": "Alice", "bowler_name": "Charlie", "runs": 1, "extras": 0},  # 1 run -> Bob on strike
            {"batsman_name": "Bob", "bowler_name": "Charlie", "runs": 4, "extras": 0},    # 4 runs -> Bob stays on strike
            {"batsman_name": "Bob", "bowler_name": "Charlie", "runs": 2, "extras": 0},    # 2 runs -> Bob stays on strike
            {"batsman_name": "Bob", "bowler_name": "Charlie", "runs": 3, "extras": 0},    # 3 runs -> Alice on strike
            {"batsman_name": "Alice", "bowler_name": "Charlie", "runs": 0, "extras": 0},  # 0 run -> Alice stays on strike
            {"batsman_name": "Alice", "bowler_name": "Charlie", "runs": 1, "extras": 0},  # 1 run on ball 6 (over end):
            # Ball 6 has 1 run (Alice -> Bob), then over ends (Bob -> Alice). Alice is on strike for Over 2!
        ]
        res = replay_innings_events(self.config_t10, {"innings_number": 1}, events, "Alice", "Bob", "Charlie")

        self.assertEqual(res["runs"], 11)
        self.assertEqual(res["overs"], 1)
        self.assertEqual(res["balls"], 0)
        self.assertEqual(res["legal_balls"], 6)

        # Check Alice stats: faced ball 1 (1r), ball 5 (0r), ball 6 (1r) -> 2 runs off 3 balls
        alice = next(b for b in res["batting_performances"] if b["player_name"] == "Alice")
        self.assertEqual(alice["runs"], 2)
        self.assertEqual(alice["balls"], 3)

        # Check Bob stats: faced ball 2 (4r), ball 3 (2r), ball 4 (3r) -> 9 runs off 3 balls (1 four)
        bob = next(b for b in res["batting_performances"] if b["player_name"] == "Bob")
        self.assertEqual(bob["runs"], 9)
        self.assertEqual(bob["balls"], 3)
        self.assertEqual(bob["fours"], 1)

        # Alice is on strike for start of next over
        self.assertEqual(res["striker_name"], "Alice")
        self.assertEqual(res["non_striker_name"], "Bob")

    def test_extras_and_bowler_figures(self):
        events = [
            {"batsman_name": "Alice", "bowler_name": "Charlie", "runs": 0, "extras": 1, "extra_type": "WIDE"},    # 1 wide (illegal)
            {"batsman_name": "Alice", "bowler_name": "Charlie", "runs": 2, "extras": 1, "extra_type": "NO BALL"}, # 1 nb + 2 bat runs (illegal)
            {"batsman_name": "Alice", "bowler_name": "Charlie", "runs": 0, "extras": 2, "extra_type": "BYE"},     # 2 byes (legal)
            {"batsman_name": "Alice", "bowler_name": "Charlie", "runs": 0, "extras": 1, "extra_type": "LEG BYE"}, # 1 leg-bye (legal, strike swaps)
        ]
        res = replay_innings_events(self.config_t10, {"innings_number": 1}, events, "Alice", "Bob", "Charlie")

        # Total runs: 1(wd) + 3(nb+2) + 2(bye) + 1(lb) = 7 runs
        self.assertEqual(res["runs"], 7)
        self.assertEqual(res["legal_balls"], 2) # Only bye and leg-bye are legal

        # Bowler runs conceded: 1(wd) + 3(nb) = 4 runs (byes & leg byes are NOT charged)
        charlie = next(bw for bw in res["bowling_performances"] if bw["player_name"] == "Charlie")
        self.assertEqual(charlie["runs_conceded"], 4)
        self.assertEqual(charlie["legal_balls"], 2)

    def test_wickets_and_incoming_batter(self):
        events = [
            {"batsman_name": "Alice", "bowler_name": "Charlie", "runs": 0, "extras": 0},
            {
                "batsman_name": "Alice", "bowler_name": "Charlie", "runs": 0, "extras": 0,
                "wicket": 1, "wicket_type": "BOWLED", "out_player_name": "Alice",
                "new_batter_name": "David"
            }
        ]
        res = replay_innings_events(self.config_t10, {"innings_number": 1}, events, "Alice", "Bob", "Charlie")

        self.assertEqual(res["wickets"], 1)
        # Alice is out
        alice = next(b for b in res["batting_performances"] if b["player_name"] == "Alice")
        self.assertTrue(alice["is_out"])
        self.assertEqual(alice["dismissal_info"], "b Charlie")

        # David replaced Alice on strike
        self.assertEqual(res["striker_name"], "David")
        self.assertEqual(res["non_striker_name"], "Bob")
        david = next(b for b in res["batting_performances"] if b["player_name"] == "David")
        self.assertTrue(david["is_on_strike"])
        self.assertFalse(david["is_out"])

        # Bowler Charlie got 1 wicket
        charlie = next(bw for bw in res["bowling_performances"] if bw["player_name"] == "Charlie")
        self.assertEqual(charlie["wickets"], 1)

    def test_wicket_on_ball_6_strike_swap(self):
        # 5 dot balls, then Alice gets out on ball 6. David comes in.
        # Over ends on ball 6, so non-striker Bob must take strike for Over 2!
        events = [
            {"batsman_name": "Alice", "bowler_name": "Charlie", "runs": 0, "extras": 0},
            {"batsman_name": "Alice", "bowler_name": "Charlie", "runs": 0, "extras": 0},
            {"batsman_name": "Alice", "bowler_name": "Charlie", "runs": 0, "extras": 0},
            {"batsman_name": "Alice", "bowler_name": "Charlie", "runs": 0, "extras": 0},
            {"batsman_name": "Alice", "bowler_name": "Charlie", "runs": 0, "extras": 0},
            {
                "batsman_name": "Alice", "bowler_name": "Charlie", "runs": 0, "extras": 0,
                "wicket": 1, "wicket_type": "CAUGHT", "out_player_name": "Alice",
                "fielder_name": "Eve", "new_batter_name": "David"
            }
        ]
        res = replay_innings_events(self.config_t10, {"innings_number": 1}, events, "Alice", "Bob", "Charlie")
        self.assertEqual(res["overs"], 1)
        self.assertEqual(res["balls"], 0)
        # Because over ended, Bob is on strike and David is non-striker
        self.assertEqual(res["striker_name"], "Bob")
        self.assertEqual(res["non_striker_name"], "David")

    def test_run_out_non_striker(self):
        # Alice is on strike, Bob (non-striker) is run out
        events = [
            {
                "batsman_name": "Alice", "bowler_name": "Charlie", "runs": 1, "extras": 0,
                "wicket": 1, "wicket_type": "RUN_OUT", "out_player_name": "Bob",
                "fielder_name": "Eve", "new_batter_name": "David"
            }
        ]
        res = replay_innings_events(self.config_t10, {"innings_number": 1}, events, "Alice", "Bob", "Charlie")
        # 1 run was completed, so Alice crossed. Bob was run out.
        # David comes in at non-striker end.
        self.assertEqual(res["wickets"], 1)
        # Bowler Charlie is NOT credited with Run Out wicket
        charlie = next(bw for bw in res["bowling_performances"] if bw["player_name"] == "Charlie")
        self.assertEqual(charlie["wickets"], 0)

    def test_all_out_custom_team_size(self):
        # 8-player match -> max_wickets = 7
        self.assertEqual(self.config_t6.max_wickets, 7)

        events = []
        for i in range(7):
            events.append({
                "batsman_name": f"Player_{i+1}", "bowler_name": "Bowler_X", "runs": 0, "extras": 0,
                "wicket": 1, "wicket_type": "BOWLED", "out_player_name": f"Player_{i+1}",
                "new_batter_name": f"Player_{i+2}" if i < 6 else None
            })

        res = replay_innings_events(self.config_t6, {"innings_number": 1}, events, "Player_1", "Player_2", "Bowler_X")
        self.assertEqual(res["wickets"], 7)
        self.assertTrue(res["is_completed"])
        self.assertEqual(res["completion_reason"], "ALL_OUT")

    def test_match_result_evaluations(self):
        # Scenario 1: Chase won by wickets
        inn1 = {"runs": 80, "is_completed": True, "batting_team": "Team A"}
        inn2 = {"runs": 81, "wickets": 4, "target": 81, "is_completed": True, "batting_team": "Team B"}
        res = evaluate_match_result(self.config_t10, inn1, inn2, "Team A", "Team B")
        self.assertEqual(res["winner"], "Team B")
        self.assertEqual(res["result_margin"], "by 6 wickets") # 10 max wickets - 4 = 6 wickets

        # Scenario 2: Defending won by runs
        inn2_loss = {"runs": 65, "wickets": 10, "target": 81, "is_completed": True, "batting_team": "Team B"}
        res2 = evaluate_match_result(self.config_t10, inn1, inn2_loss, "Team A", "Team B")
        self.assertEqual(res2["winner"], "Team A")
        self.assertEqual(res2["result_margin"], "by 15 runs")

        # Scenario 3: Match Tied
        inn2_tie = {"runs": 80, "wickets": 10, "target": 81, "is_completed": True, "batting_team": "Team B"}
        res3 = evaluate_match_result(self.config_t10, inn1, inn2_tie, "Team A", "Team B")
        self.assertEqual(res3["winner"], "Match Tied")
        self.assertEqual(res3["result_type"], "TIE")


if __name__ == "__main__":
    unittest.main()

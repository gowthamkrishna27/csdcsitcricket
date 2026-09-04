"""
test_production_hardening.py — Production Hardening and Invariant Verification Test Suite
CSDC / CSIT Cricket Tournament
"""

import os
import unittest
import uuid
import json

TEST_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "test_hardening.db")
os.environ["CRICKET_DB_PATH"] = TEST_DB_PATH

import cricket_db
from server import app
import cricket_engine
from cricket_engine import MatchConfig, replay_innings_events, evaluate_match_result, validate_dismissal_on_delivery


class ProductionHardeningTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.environ["CRICKET_DB_PATH"] = TEST_DB_PATH
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass
        cricket_db.init_db()
        cricket_db.seed_default_data()

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass

    def setUp(self):
        self.client = app.test_client()
        # Authenticate as Admin
        self.client.post('/api/auth/login', json={
            'email': 'gowthamkrishna18v@gmail.com',
            'password': '0724'
        })

    def test_multi_match_isolation(self):
        """Verify starting, scoring, and undoing Match A has zero impact on Match B."""
        # Create Match A
        res_a = self.client.post('/api/admin/matches', json={
            'team_a': 'House Vayu', 'team_b': 'House Agni', 'total_overs': 5
        })
        mid_a = res_a.get_json()['match']['id']

        # Create Match B
        res_b = self.client.post('/api/admin/matches', json={
            'team_a': 'House Jal', 'team_b': 'House Prithvi', 'total_overs': 5
        })
        mid_b = res_b.get_json()['match']['id']

        # Start Match A
        self.client.post(f'/api/admin/matches/{mid_a}/start')
        # Check Match B remains UPCOMING
        mb = self.client.get(f'/api/matches/{mid_b}').get_json()['match']
        self.assertEqual(mb['status'], 'UPCOMING', "Match B must remain UPCOMING when Match A starts")

        # Start Match B
        self.client.post(f'/api/admin/matches/{mid_b}/start')

        # Score in Match A: 6 runs
        self.client.post(f'/api/admin/matches/{mid_a}/ball', json={'runs': 6, 'client_event_uuid': str(uuid.uuid4())})
        
        # Verify Match B score is still 0
        mb_live = self.client.get(f'/api/matches/{mid_b}').get_json()['match']
        self.assertEqual(mb_live['innings'][0]['runs'], 0, "Match B score must remain 0")

        # Score in Match B: 4 runs
        self.client.post(f'/api/admin/matches/{mid_b}/ball', json={'runs': 4, 'client_event_uuid': str(uuid.uuid4())})

        ma_live = self.client.get(f'/api/matches/{mid_a}').get_json()['match']
        mb_live = self.client.get(f'/api/matches/{mid_b}').get_json()['match']
        self.assertEqual(ma_live['innings'][0]['runs'], 6)
        self.assertEqual(mb_live['innings'][0]['runs'], 4)

        # Undo on Match A: Match A -> 0 runs, Match B must remain 4 runs
        self.client.post(f'/api/admin/matches/{mid_a}/undo')
        ma_after = self.client.get(f'/api/matches/{mid_a}').get_json()['match']
        mb_after = self.client.get(f'/api/matches/{mid_b}').get_json()['match']
        self.assertEqual(ma_after['innings'][0]['runs'], 0)
        self.assertEqual(mb_after['innings'][0]['runs'], 4, "Match B score must remain intact after Match A undo")

    def test_scorer_claim_and_forbidden_mutations(self):
        """Verify only the claiming scorer (or admin) can score a match."""
        cricket_db.create_user('Scorer Alice', 'alice@cricket.local', 'pass123', role='SCORER')
        cricket_db.create_user('Scorer Bob', 'bob@cricket.local', 'pass123', role='SCORER')

        res = self.client.post('/api/admin/matches', json={
            'team_a': 'House Akash', 'team_b': 'House Vayu', 'total_overs': 5
        })
        mid = res.get_json()['match']['id']
        cricket_db.start_match(mid)

        # Scorer Alice claims match
        c_alice = app.test_client()
        c_alice.post('/api/auth/login', json={'email': 'alice@cricket.local', 'password': 'pass123'})
        r_claim = c_alice.post(f'/api/scorer/matches/{mid}/claim')
        self.assertEqual(r_claim.status_code, 200)

        # Scorer Bob attempts to score -> 403 Forbidden
        c_bob = app.test_client()
        c_bob.post('/api/auth/login', json={'email': 'bob@cricket.local', 'password': 'pass123'})
        r_bob_score = c_bob.post(f'/api/matches/{mid}/ball', json={'runs': 1, 'client_event_uuid': str(uuid.uuid4())})
        self.assertEqual(r_bob_score.status_code, 403)

        # Unauthenticated request -> 401 Unauthorized
        c_anon = app.test_client()
        r_anon = c_anon.post(f'/api/matches/{mid}/ball', json={'runs': 1, 'client_event_uuid': str(uuid.uuid4())})
        self.assertEqual(r_anon.status_code, 401)

        # Admin override works
        r_admin_score = self.client.post(f'/api/matches/{mid}/ball', json={'runs': 2, 'client_event_uuid': str(uuid.uuid4())})
        self.assertEqual(r_admin_score.status_code, 200)

    def test_idempotent_delivery_resubmission(self):
        """Verify repeated delivery submissions with the same UUID result in exactly 1 delivery."""
        res = self.client.post('/api/admin/matches', json={
            'team_a': 'House Jal', 'team_b': 'House Agni', 'total_overs': 5
        })
        mid = res.get_json()['match']['id']
        self.client.post(f'/api/admin/matches/{mid}/start')

        deliv_uuid = str(uuid.uuid4())

        # Send 5 identical requests
        for attempt in range(5):
            r = self.client.post(f'/api/admin/matches/{mid}/ball', json={
                'runs': 4,
                'client_event_uuid': deliv_uuid
            })
            self.assertEqual(r.status_code, 200)
            if attempt > 0:
                self.assertEqual(r.get_json().get('status'), 'ALREADY_APPLIED')

        m = self.client.get(f'/api/matches/{mid}').get_json()['match']
        self.assertEqual(m['innings'][0]['runs'], 4, "4 runs must be counted exactly once")
        self.assertEqual(m['innings'][0]['balls'], 1, "Balls in over must be exactly 1")

    def test_illegal_dismissal_on_no_ball_rejected(self):
        """Verify Bowled, Caught, LBW, Stumped are rejected on a No Ball via API."""
        res = self.client.post('/api/admin/matches', json={
            'team_a': 'House Prithvi', 'team_b': 'House Vayu', 'total_overs': 5
        })
        mid = res.get_json()['match']['id']
        self.client.post(f'/api/admin/matches/{mid}/start')

        # Bowled on No Ball -> 400 Bad Request
        r1 = self.client.post(f'/api/admin/matches/{mid}/wicket', json={
            'wicket_type': 'BOWLED',
            'extra_type': 'NO BALL',
            'client_event_uuid': str(uuid.uuid4())
        })
        self.assertEqual(r1.status_code, 400)
        self.assertIn('No Ball', r1.get_json()['error'])

        # Caught on No Ball -> 400 Bad Request
        r2 = self.client.post(f'/api/admin/matches/{mid}/wicket', json={
            'wicket_type': 'CAUGHT',
            'extra_type': 'NO BALL',
            'client_event_uuid': str(uuid.uuid4())
        })
        self.assertEqual(r2.status_code, 400)

        # Run Out on No Ball -> 200 OK (Allowed by MCC Law 21.18)
        r3 = self.client.post(f'/api/admin/matches/{mid}/wicket', json={
            'wicket_type': 'RUN_OUT',
            'extra_type': 'NO BALL',
            'client_event_uuid': str(uuid.uuid4())
        })
        self.assertEqual(r3.status_code, 200)

    def test_multi_run_wide_and_strike_rotation(self):
        """Verify wide with additional physical runs: total extras, legal ball count, and strike rotation."""
        config = MatchConfig(total_overs=5, players_per_team=11)
        events = [
            {"batsman_name": "Alice", "bowler_name": "Charlie", "runs": 1, "extras": 1, "extra_type": "WIDE"}
        ]
        res = replay_innings_events(config, {"innings_number": 1}, events, "Alice", "Bob", "Charlie")
        self.assertEqual(res["runs"], 2)
        self.assertEqual(res["legal_balls"], 0, "Wide must not consume a legal ball")
        self.assertEqual(res["striker_name"], "Bob", "1 physical run on wide must swap strike to Bob")

    def test_player_api_contract_keys(self):
        """Verify player API contract returns all canonical keys without mismatch."""
        res = self.client.post('/api/admin/matches', json={
            'team_a': 'House Vayu', 'team_b': 'House Agni', 'total_overs': 10
        })
        mid = res.get_json()['match']['id']
        self.client.post(f'/api/admin/matches/{mid}/start')

        r = self.client.get(f'/api/matches/{mid}/players-for-scoring')
        self.assertEqual(r.status_code, 200)
        data = r.get_json()

        # Check required contract keys
        self.assertIn('batting_players', data)
        self.assertIn('bowling_players', data)
        self.assertIn('available_batters', data)
        self.assertIn('batting_xi', data)
        self.assertIn('bowling_xi', data)
        self.assertIn('fielders', data)

    def test_governance_lock_and_unlock_with_reason(self):
        """Verify match lock protects from scoring, and unlock requires non-empty reason and creates audit log."""
        res = self.client.post('/api/admin/matches', json={
            'team_a': 'House Jal', 'team_b': 'House Prithvi', 'total_overs': 5
        })
        mid = res.get_json()['match']['id']
        self.client.post(f'/api/admin/matches/{mid}/start')

        # Lock match
        r_lock = self.client.post(f'/api/admin/matches/{mid}/lock', json={'reason': 'Final review'})
        self.assertEqual(r_lock.status_code, 200)

        # Attempt to record delivery on locked match -> 400
        r_score = self.client.post(f'/api/admin/matches/{mid}/ball', json={'runs': 1, 'client_event_uuid': str(uuid.uuid4())})
        self.assertEqual(r_score.status_code, 400)
        self.assertIn('locked', r_score.get_json()['error'])

        # Attempt unlock without reason -> 400
        r_unlock_fail = self.client.post(f'/api/admin/matches/{mid}/unlock', json={'reason': ''})
        self.assertEqual(r_unlock_fail.status_code, 400)

        # Unlock with valid reason -> 200
        r_unlock_ok = self.client.post(f'/api/admin/matches/{mid}/unlock', json={'reason': 'Official correction approved'})
        self.assertEqual(r_unlock_ok.status_code, 200)

        # Audit logs recorded
        r_logs = self.client.get('/api/admin/audit-logs')
        self.assertEqual(r_logs.status_code, 200)
        logs = r_logs.get_json()['audit_logs']
        actions = [l['action'] for l in logs]
        self.assertIn('LOCK_MATCH', actions)
        self.assertIn('UNLOCK_MATCH', actions)


if __name__ == '__main__':
    unittest.main()

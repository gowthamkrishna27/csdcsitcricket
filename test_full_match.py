import os
import unittest
import uuid
import datetime

# Configure isolated test database environment
TEST_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "test_full_match.db")
os.environ["CRICKET_DB_PATH"] = TEST_DB_PATH

import cricket_db
from server import app
import cricket_engine
from cricket_engine import MatchConfig, replay_innings_events, evaluate_match_result

class FullMatchSimulationTest(unittest.TestCase):
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
        # Authenticate as admin for full test access
        self.client.post('/api/auth/login', json={
            'email': 'gowthamkrishna18v@gmail.com',
            'password': '0724'
        })

    def test_scenario_a_full_match_chase_win(self):
        """Scenario A: 1st innings completes, 2nd innings chases target successfully to win by wickets."""
        res_create = self.client.post('/api/admin/matches', json={
            'team_a': 'House Vayu',
            'team_b': 'House Agni',
            'venue': 'Finals Stadium',
            'match_date': 'Today',
            'total_overs': 2,
            'players_per_team': 11
        })
        mid = res_create.get_json()['match']['id']
        self.client.post(f'/api/admin/matches/{mid}/start')

        # 1st Innings: 12 balls, score 20 runs
        for i in range(12):
            self.client.post(f'/api/admin/matches/{mid}/ball', json={
                'runs': 1 if i % 2 == 0 else 2,
                'client_event_uuid': str(uuid.uuid4())
            })

        m = self.client.get(f'/api/matches/{mid}').get_json()['match']
        self.assertEqual(m['innings'][0]['runs'], 18)
        self.assertEqual(m['innings'][0]['overs'], 2)
        self.assertEqual(m['innings'][0]['balls'], 0)

        # 2nd innings should target 19 runs (target = 18 + 1)
        self.client.post(f'/api/admin/matches/{mid}/innings/switch')
        m2 = self.client.get(f'/api/matches/{mid}').get_json()['match']
        self.assertEqual(m2['current_innings'], 2)
        self.assertEqual(m2['innings'][1]['target'], 19)

        # 2nd Innings: score 6, 6, 4, 4 (20 runs in 4 balls) -> chase win
        for r in [6, 6, 4, 4]:
            self.client.post(f'/api/admin/matches/{mid}/ball', json={
                'runs': r,
                'client_event_uuid': str(uuid.uuid4())
            })

        m_fin = self.client.get(f'/api/matches/{mid}').get_json()['match']
        self.assertEqual(m_fin['status'], 'COMPLETED')
        self.assertEqual(m_fin['winner'], 'House Agni')
        self.assertEqual(m_fin['result_margin'], 'by 10 wickets')

    def test_scenario_b_defending_team_win(self):
        """Scenario B: 1st innings scores runs, 2nd innings fails to chase within overs limit."""
        res_create = self.client.post('/api/admin/matches', json={
            'team_a': 'House Jal',
            'team_b': 'House Prithvi',
            'venue': 'Championship Arena',
            'match_date': 'Today',
            'total_overs': 1,
            'players_per_team': 11
        })
        mid = res_create.get_json()['match']['id']
        self.client.post(f'/api/admin/matches/{mid}/start')

        # 1st Innings: 6 balls -> 6, 6, 6, 4, 4, 4 = 30 runs
        for r in [6, 6, 6, 4, 4, 4]:
            self.client.post(f'/api/admin/matches/{mid}/ball', json={'runs': r, 'client_event_uuid': str(uuid.uuid4())})

        self.client.post(f'/api/admin/matches/{mid}/innings/switch')

        # 2nd Innings: 6 balls -> 1, 1, 1, 1, 1, 1 = 6 runs
        for r in [1, 1, 1, 1, 1, 1]:
            self.client.post(f'/api/admin/matches/{mid}/ball', json={'runs': r, 'client_event_uuid': str(uuid.uuid4())})

        m_fin = self.client.get(f'/api/matches/{mid}').get_json()['match']
        self.assertEqual(m_fin['status'], 'COMPLETED')
        self.assertEqual(m_fin['winner'], 'House Jal')
        self.assertEqual(m_fin['result_margin'], 'by 24 runs')

    def test_scenario_c_match_tie(self):
        """Scenario C: 2nd innings matches 1st innings total exactly when overs exhaust -> Tied match."""
        res_create = self.client.post('/api/admin/matches', json={
            'team_a': 'House Akash',
            'team_b': 'House Vayu',
            'venue': 'Ground 1',
            'match_date': 'Today',
            'total_overs': 1,
            'players_per_team': 11
        })
        mid = res_create.get_json()['match']['id']
        self.client.post(f'/api/admin/matches/{mid}/start')

        # 1st Innings: 6 balls -> 12 runs (target = 13)
        for r in [2, 2, 2, 2, 2, 2]:
            self.client.post(f'/api/admin/matches/{mid}/ball', json={'runs': r, 'client_event_uuid': str(uuid.uuid4())})

        self.client.post(f'/api/admin/matches/{mid}/innings/switch')

        # 2nd Innings: 6 balls -> 12 runs (12 == target - 1)
        for r in [2, 2, 2, 2, 2, 2]:
            self.client.post(f'/api/admin/matches/{mid}/ball', json={'runs': r, 'client_event_uuid': str(uuid.uuid4())})

        m_fin = self.client.get(f'/api/matches/{mid}').get_json()['match']
        self.assertEqual(m_fin['status'], 'COMPLETED')
        self.assertEqual(m_fin['winner'], 'Match Tied')

    def test_scenario_d_eight_player_all_out_quota(self):
        """Scenario D: In an 8-player match, 7 wickets constitutes All Out."""
        res_create = self.client.post('/api/admin/matches', json={
            'team_a': 'House Vayu',
            'team_b': 'House Agni',
            'venue': 'T6 Arena',
            'match_date': 'Today',
            'total_overs': 6,
            'players_per_team': 8
        })
        mid = res_create.get_json()['match']['id']
        xi_8 = [f'Player {i}' for i in range(1, 9)]
        self.client.post(f'/api/admin/matches/{mid}/playing-xi', json={'team': 'House Vayu', 'playing_xi': xi_8})
        self.client.post(f'/api/admin/matches/{mid}/playing-xi', json={'team': 'House Agni', 'playing_xi': xi_8})
        self.client.post(f'/api/admin/matches/{mid}/start')

        # Record 7 wickets in 1st innings (all 8 players enter, 7 wickets = All Out)
        for w in range(1, 8):
            req_data = {
                'wicket_type': 'BOWLED',
                'client_event_uuid': str(uuid.uuid4())
            }
            if w < 7:
                req_data['new_batter'] = f'Player {w + 2}'
            res_w = self.client.post(f'/api/admin/matches/{mid}/wicket', json=req_data)
            self.assertEqual(res_w.status_code, 200, f"Wicket {w} failed: {res_w.get_json()}")

        m = self.client.get(f'/api/matches/{mid}').get_json()['match']
        self.assertEqual(m['innings'][0]['wickets'], 7)
        # All-out triggers automatic 2nd innings transition
        self.assertEqual(m['current_innings'], 2)

    def test_scenario_e_idempotent_delivery_and_undo(self):
        """Scenario E: Submitting duplicate UUID is idempotent and undo correctly restores state."""
        res_create = self.client.post('/api/admin/matches', json={
            'team_a': 'House Jal',
            'team_b': 'House Agni',
            'total_overs': 5,
            'players_per_team': 11
        })
        mid = res_create.get_json()['match']['id']
        self.client.post(f'/api/admin/matches/{mid}/start')

        u1 = str(uuid.uuid4())
        # First delivery
        r1 = self.client.post(f'/api/admin/matches/{mid}/ball', json={'runs': 6, 'client_event_uuid': u1})
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.get_json()['match']['innings'][0]['runs'], 6)

        # Duplicate delivery with same UUID -> must not double count
        r2 = self.client.post(f'/api/admin/matches/{mid}/ball', json={'runs': 6, 'client_event_uuid': u1})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.get_json()['status'], 'ALREADY_APPLIED')
        m_dup = self.client.get(f'/api/matches/{mid}').get_json()['match']
        self.assertEqual(m_dup['innings'][0]['runs'], 6, "Runs must not be 12 on duplicate UUID")

        # Undo delivery
        r_undo = self.client.post(f'/api/admin/matches/{mid}/undo')
        self.assertEqual(r_undo.status_code, 200)
        m_after_undo = self.client.get(f'/api/matches/{mid}').get_json()['match']
        self.assertEqual(m_after_undo['innings'][0]['runs'], 0)
        self.assertEqual(m_after_undo['innings'][0]['balls'], 0)

    def test_scenario_f_scorer_authorization_claim_protection(self):
        """Scenario F: A scorer cannot mutate another scorer's actively claimed match."""
        cricket_db.create_user('Scorer One', 'scorer_one@example.com', 'pass1', role='SCORER')
        cricket_db.create_user('Scorer Two', 'scorer_two@example.com', 'pass2', role='SCORER')

        res_create = self.client.post('/api/admin/matches', json={
            'team_a': 'House Vayu',
            'team_b': 'House Prithvi',
            'total_overs': 5
        })
        mid = res_create.get_json()['match']['id']
        cricket_db.start_match(mid)

        # Scorer 1 claims match
        c1 = app.test_client()
        r_log1 = c1.post('/api/auth/login', json={'email': 'scorer_one@example.com', 'password': 'pass1'})
        self.assertEqual(r_log1.status_code, 200)
        r_claim = c1.post(f'/api/scorer/matches/{mid}/claim')
        self.assertEqual(r_claim.status_code, 200)

        # Scorer 1 can record ball
        r_ball1 = c1.post(f'/api/matches/{mid}/ball', json={'runs': 1, 'client_event_uuid': str(uuid.uuid4())})
        self.assertEqual(r_ball1.status_code, 200)

        # Scorer 2 logs in and attempts to record ball on Scorer 1's match -> 403 Forbidden
        c2 = app.test_client()
        r_log2 = c2.post('/api/auth/login', json={'email': 'scorer_two@example.com', 'password': 'pass2'})
        self.assertEqual(r_log2.status_code, 200)
        r_ball2 = c2.post(f'/api/matches/{mid}/ball', json={'runs': 4, 'client_event_uuid': str(uuid.uuid4())})
        self.assertEqual(r_ball2.status_code, 403)
        self.assertIn('assigned to another scorer', r_ball2.get_json()['error'])

if __name__ == '__main__':
    unittest.main()

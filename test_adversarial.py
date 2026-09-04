"""
test_adversarial.py — Aggressive Adversarial QA & Invariant Audit Test Suite
CSDC / CSIT Cricket Tournament
"""

import os
import unittest
import uuid
import threading
import json
import time

TEST_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "test_adversarial.db")
os.environ["CRICKET_DB_PATH"] = TEST_DB_PATH

import cricket_db
from server import app
import cricket_engine
from cricket_engine import MatchConfig, replay_innings_events, evaluate_match_result


class AdversarialCricketAuditTests(unittest.TestCase):

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
        self.client.post('/api/auth/login', json={
            'email': 'gowthamkrishna18v@gmail.com',
            'password': '0724'
        })

    def _create_and_start_match(self, overs=5, ppt=11):
        res = self.client.post('/api/admin/matches', json={
            'team_a': 'House Vayu',
            'team_b': 'House Agni',
            'total_overs': overs,
            'players_per_team': ppt
        })
        mid = res.get_json()['match']['id']
        self.client.post(f'/api/admin/matches/{mid}/start')
        m = self.client.get(f'/api/matches/{mid}').get_json()['match']
        return mid, m

    # -----------------------------------------------------------------------
    # 1. PLAYING XI & GHOST/PLACEHOLDER ATTACKS
    # -----------------------------------------------------------------------

    def test_non_playing_xi_batsman_rejected(self):
        """Reject deliveries where the striker is not in the batting Playing XI."""
        mid, m = self._create_and_start_match()
        res = self.client.post(f'/api/admin/matches/{mid}/ball', json={
            'runs': 1,
            'batsman_name': 'Hacker Not In XI',
            'client_event_uuid': str(uuid.uuid4())
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn('not in the Playing XI', res.get_json()['error'])

    def test_non_playing_xi_bowler_rejected(self):
        """Reject deliveries where the bowler is not in the bowling Playing XI."""
        mid, m = self._create_and_start_match()
        res = self.client.post(f'/api/admin/matches/{mid}/ball', json={
            'runs': 1,
            'bowler_name': 'Fake Bowler',
            'client_event_uuid': str(uuid.uuid4())
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn('not in the Playing XI', res.get_json()['error'])

    def test_non_playing_xi_fielder_rejected(self):
        """Reject dismissals where the fielder is not in the bowling Playing XI."""
        mid, m = self._create_and_start_match()
        res = self.client.post(f'/api/admin/matches/{mid}/wicket', json={
            'wicket_type': 'CAUGHT',
            'fielder_name': 'Ghost Fielder',
            'client_event_uuid': str(uuid.uuid4())
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn('not in the Playing XI', res.get_json()['error'])

    def test_non_playing_xi_incoming_batter_rejected(self):
        """Reject wickets where incoming batter is not in the batting Playing XI."""
        mid, m = self._create_and_start_match()
        res = self.client.post(f'/api/admin/matches/{mid}/wicket', json={
            'wicket_type': 'BOWLED',
            'new_batter': 'Unknown Free Text Player',
            'client_event_uuid': str(uuid.uuid4())
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn('not in the Playing XI', res.get_json()['error'])

    # -----------------------------------------------------------------------
    # 2. STALE BATTER & CREASE INTEGRITY ATTACKS
    # -----------------------------------------------------------------------

    def test_dismiss_player_not_at_crease_rejected(self):
        """Reject dismissals targeting a player who is not currently at the crease."""
        mid, m = self._create_and_start_match()
        xi_a = m['playing_xi_a']
        benches = xi_a[2:] if len(xi_a) > 2 else []
        if benches:
            bench_player = benches[0]
            res = self.client.post(f'/api/admin/matches/{mid}/wicket', json={
                'wicket_type': 'BOWLED',
                'out_batter': bench_player,
                'client_event_uuid': str(uuid.uuid4())
            })
            self.assertEqual(res.status_code, 400)
            self.assertIn('not currently at the crease', res.get_json()['error'])

    def test_already_dismissed_player_cannot_bat_again(self):
        """Reject incoming batter who was already dismissed in the same innings."""
        mid, m = self._create_and_start_match()
        xi_a = m['playing_xi_a']
        p1 = xi_a[0]
        p2 = xi_a[1]
        p3 = xi_a[2]

        # Dismiss p1 -> p3 enters
        r1 = self.client.post(f'/api/admin/matches/{mid}/wicket', json={
            'wicket_type': 'BOWLED',
            'out_batter': p1,
            'new_batter': p3,
            'client_event_uuid': str(uuid.uuid4())
        })
        self.assertEqual(r1.status_code, 200)

        # Now dismiss p2, attempt to bring p1 back -> must be REJECTED!
        r2 = self.client.post(f'/api/admin/matches/{mid}/wicket', json={
            'wicket_type': 'CAUGHT',
            'out_batter': p2,
            'new_batter': p1,
            'client_event_uuid': str(uuid.uuid4())
        })
        self.assertEqual(r2.status_code, 400)
        self.assertIn('already out', r2.get_json()['error'])

    def test_non_striker_cannot_be_incoming_batter(self):
        """Reject incoming batter who is already at the crease as non-striker."""
        mid, m = self._create_and_start_match()
        xi_a = m['playing_xi_a']
        p1 = xi_a[0]
        p2 = xi_a[1]

        # Dismiss striker p1, attempt to set new_batter = p2 (who is already non-striker)
        r = self.client.post(f'/api/admin/matches/{mid}/wicket', json={
            'wicket_type': 'BOWLED',
            'out_batter': p1,
            'new_batter': p2,
            'client_event_uuid': str(uuid.uuid4())
        })
        self.assertEqual(r.status_code, 400)
        self.assertIn('already at the crease', r.get_json()['error'])

    # -----------------------------------------------------------------------
    # 3. MATCH COMPLETION MUTATION LOCKDOWN ATTACKS
    # -----------------------------------------------------------------------

    def test_scoring_on_completed_match_rejected(self):
        """Reject ordinary ball/wicket mutations once a match is COMPLETED."""
        mid, m = self._create_and_start_match(overs=1)
        # Complete match
        self.client.post(f'/api/admin/matches/{mid}/complete', json={'winner': 'House Vayu', 'margin': 'by forfeit'})
        m_comp = self.client.get(f'/api/matches/{mid}').get_json()['match']
        self.assertEqual(m_comp['status'], 'COMPLETED')

        # Attempt ball delivery on completed match -> 400
        r_ball = self.client.post(f'/api/admin/matches/{mid}/ball', json={'runs': 1, 'client_event_uuid': str(uuid.uuid4())})
        self.assertEqual(r_ball.status_code, 400)

        # Attempt wicket on completed match -> 400
        r_wkt = self.client.post(f'/api/admin/matches/{mid}/wicket', json={'wicket_type': 'BOWLED', 'client_event_uuid': str(uuid.uuid4())})
        self.assertEqual(r_wkt.status_code, 400)

    # -----------------------------------------------------------------------
    # 4. CONCURRENT RACING & DIVERGENCE (EXPECTED SEQUENCE)
    # -----------------------------------------------------------------------

    def test_divergent_sequence_conflict_rejection(self):
        """Verify delivery is rejected with 409 when client expected_sequence does not match server timeline."""
        mid, m = self._create_and_start_match()
        # Delivery 1: server at event count 0 -> advances to 1
        r1 = self.client.post(f'/api/admin/matches/{mid}/ball', json={
            'runs': 1,
            'expected_sequence': 0,
            'client_event_uuid': str(uuid.uuid4())
        })
        self.assertEqual(r1.status_code, 200)

        # Stale client sends request expecting sequence 0 (now divergent!) -> 409 Conflict
        r_stale = self.client.post(f'/api/admin/matches/{mid}/ball', json={
            'runs': 4,
            'expected_sequence': 0,
            'client_event_uuid': str(uuid.uuid4())
        })
        self.assertEqual(r_stale.status_code, 409)
        self.assertEqual(r_stale.get_json()['status'], 'REJECTED_CONFLICT')

    def test_concurrent_threads_same_uuid_no_duplicate(self):
        """Verify simultaneous threaded requests with the same UUID create exactly 1 database event."""
        mid, m = self._create_and_start_match()
        shared_uuid = str(uuid.uuid4())
        results = []

        def worker():
            c = app.test_client()
            c.post('/api/auth/login', json={'email': 'gowthamkrishna18v@gmail.com', 'password': '0724'})
            for _ in range(5):
                res = c.post(f'/api/admin/matches/{mid}/ball', json={'runs': 6, 'client_event_uuid': shared_uuid})
                if res.status_code == 200:
                    results.append(200)
                    return
                time.sleep(0.05)
            results.append(res.status_code)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()

        # All requests must succeed (200 OK), but runs must be 6, NOT 30!
        for code in results:
            self.assertEqual(code, 200)

        m_fin = self.client.get(f'/api/matches/{mid}').get_json()['match']
        self.assertEqual(m_fin['innings'][0]['runs'], 6)
        self.assertEqual(m_fin['innings'][0]['balls'], 1)

    # -----------------------------------------------------------------------
    # 5. CRICKET INVARIANT CHECK & LOSSLESS EVENT REPLAY
    # -----------------------------------------------------------------------

    def test_complete_match_accounting_invariants(self):
        """Verify: Team Total = Batters Runs + Extras across full multi-over match with wickets & extras."""
        mid, m = self._create_and_start_match(overs=2)

        # 1st innings sequence with singles, dots, boundaries, wides, no-balls, byes, wickets
        events = [
            {'runs': 4},
            {'runs': 0, 'extra': 'WIDE'},      # 1 wd
            {'runs': 2, 'extra': 'NO BALL'},   # 1 nb + 2 bat runs
            {'runs': 1},
            {'runs': 0, 'extra': 'BYE'},       # 1 bye
            {'runs': 6},
            {'runs': 0, 'extra': 'LEG BYE'},   # 1 leg-bye
        ]
        for ev in events:
            ev['client_event_uuid'] = str(uuid.uuid4())
            self.client.post(f'/api/admin/matches/{mid}/ball', json=ev)

        # Wicket
        self.client.post(f'/api/admin/matches/{mid}/wicket', json={
            'wicket_type': 'BOWLED',
            'client_event_uuid': str(uuid.uuid4())
        })

        sc_resp = self.client.get(f'/api/matches/{mid}/scorecard').get_json()['scorecard']
        sc1 = sc_resp['scorecards'][0]
        inn1_info = sc1['innings_info']
        batting_list = sc1['batting']
        extras_info = sc1['extras']

        team_total = inn1_info['runs']
        batter_runs_sum = sum(b['runs'] for b in batting_list)
        extras_total = extras_info['total']
        
        # Calculate extras directly from ball events: 1 wide + 1 no-ball + 1 bye + 1 leg-bye = 4 extras
        # Expected:
        # ball 1: 4 bat runs
        # ball 2 (wide): 0 bat runs, 1 extra
        # ball 3 (no ball): 2 bat runs, 1 extra
        # ball 4: 1 bat run
        # ball 5 (bye): 0 bat runs, 1 extra
        # ball 6: 6 bat runs
        # ball 7 (leg bye): 0 bat runs, 1 extra
        # ball 8 (wicket): 0 bat runs, 0 extras
        # Total bat runs = 4 + 2 + 1 + 6 = 13.
        # Total extras = 1 + 1 + 1 + 1 = 4.
        # Team Total = 13 + 4 = 17 runs.
        self.assertEqual(batter_runs_sum, 13)
        self.assertEqual(extras_total, 4)
        self.assertEqual(team_total, 17)
        self.assertEqual(team_total, batter_runs_sum + extras_total, "Accounting invariant: Team Total == Batter Runs + Extras")

    def test_pure_replay_lossless_state_reconstruction(self):
        """Prove ball_events alone contain 100% of the information to reconstruct match state."""
        config = MatchConfig(total_overs=2, players_per_team=11)
        raw_events = [
            {'batsman_name': 'A', 'bowler_name': 'X', 'runs': 1, 'extras': 0},
            {'batsman_name': 'B', 'bowler_name': 'X', 'runs': 4, 'extras': 0},
            {'batsman_name': 'B', 'bowler_name': 'X', 'runs': 0, 'extras': 1, 'extra_type': 'WIDE'},
            {'batsman_name': 'B', 'bowler_name': 'X', 'runs': 0, 'extras': 0, 'wicket': 1, 'wicket_type': 'BOWLED', 'out_player_name': 'B', 'new_batter_name': 'C'},
        ]
        state = replay_innings_events(config, {'innings_number': 1}, raw_events, 'A', 'B', 'X')

        self.assertEqual(state['runs'], 6)
        self.assertEqual(state['wickets'], 1)
        self.assertEqual(state['legal_balls'], 3)
        self.assertEqual(state['striker_name'], 'C')
        self.assertEqual(state['non_striker_name'], 'A')
        
        # Verify bowler stats
        bowler = next(b for b in state['bowling_performances'] if b['player_name'] == 'X')
        self.assertEqual(bowler['wickets'], 1)
        self.assertEqual(bowler['runs_conceded'], 6)
        self.assertEqual(bowler['legal_balls'], 3)


if __name__ == '__main__':
    unittest.main()

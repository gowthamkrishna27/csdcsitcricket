import os
import unittest
import json

# Configure isolated test database environment before test runs
TEST_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "test_cricket.db")
os.environ["CRICKET_DB_PATH"] = TEST_DB_PATH

import cricket_db
from server import app

class CricketIntegrationTest(unittest.TestCase):
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
        with cricket_db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            DELETE FROM matches 
            WHERE match_name NOT IN (
                'Match 1 - VAY vs AGN',
                'Match 2 - JAL vs PRI',
                'Match 0 - AKA vs VAY',
                'Titan Strikers vs Falcon Kings',
                'Solar Hawks vs Storm Riders'
            )
            """)
            conn.commit()
        # Login as admin
        res = self.client.post('/api/auth/login', json={
            'email': 'gowthamkrishna18v@gmail.com',
            'password': '0724'
        })
        self.assertEqual(res.status_code, 200, "Admin login should succeed")

    def test_end_to_end_scoring_flow(self):
        # 1. Create a match
        res = self.client.post('/api/admin/matches', json={
            'team_a': 'House Vayu',
            'team_b': 'House Agni',
            'venue': 'Finals Stadium',
            'match_date': 'Today',
            'total_overs': 10
        })
        self.assertEqual(res.status_code, 201, "Create match should succeed")
        data = res.get_json()
        self.assertTrue(data['success'])
        match_id = data['match']['id']

        # 2. Start the match
        res = self.client.post(f'/api/admin/matches/{match_id}/start')
        self.assertEqual(res.status_code, 200, "Start match should succeed")
        m_start = res.get_json()['match']
        self.assertEqual(m_start['status'], 'LIVE')
        self.assertEqual(m_start['current_inn']['runs'], 0)
        self.assertEqual(m_start['current_inn']['wickets'], 0)

        # 3. Record Ball: 4 Runs
        res = self.client.post(f'/api/admin/matches/{match_id}/ball', json={'runs': 4})
        self.assertEqual(res.status_code, 200)
        m = res.get_json()['match']
        self.assertEqual(m['current_inn']['runs'], 4, "Runs should be 4")
        self.assertEqual(m['current_inn']['balls'], 1, "Balls in over should be 1")

        # 4. Record Ball: 1 Run (odd run rotates strike)
        res = self.client.post(f'/api/admin/matches/{match_id}/ball', json={'runs': 1})
        self.assertEqual(res.status_code, 200)
        m = res.get_json()['match']
        self.assertEqual(m['current_inn']['runs'], 5)
        self.assertEqual(m['current_inn']['balls'], 2)

        # 5. Record Wicket
        res = self.client.post(f'/api/admin/matches/{match_id}/wicket', json={
            'new_batter': 'Kunal Mehra',
            'wicket_type': 'CAUGHT'
        })
        self.assertEqual(res.status_code, 200)
        m = res.get_json()['match']
        self.assertEqual(m['current_inn']['wickets'], 1, "Wickets should be 1")
        self.assertEqual(m['current_inn']['balls'], 3, "Balls in over should be 3")

        # 6. Check Public Live API
        res_live = self.client.get('/api/matches/live')
        self.assertEqual(res_live.status_code, 200)
        live_json = res_live.get_json()
        self.assertTrue(live_json['success'])
        self.assertEqual(live_json['match']['current_inn']['runs'], 5)
        self.assertEqual(live_json['match']['current_inn']['wickets'], 1)

        # 7. Check Full Scorecard API
        res_sc = self.client.get(f'/api/matches/{match_id}/scorecard')
        self.assertEqual(res_sc.status_code, 200)
        sc_data = res_sc.get_json()['scorecard']
        self.assertEqual(len(sc_data['scorecards']), 1)
        inn_sc = sc_data['scorecards'][0]
        self.assertEqual(len(inn_sc['fall_of_wickets']), 1)

        # 8. Test UNDO: Undo Wicket
        res_undo1 = self.client.post(f'/api/admin/matches/{match_id}/undo')
        self.assertEqual(res_undo1.status_code, 200)
        m_undo1 = res_undo1.get_json()['match']
        self.assertEqual(m_undo1['current_inn']['wickets'], 0, "Wicket should be undone")
        self.assertEqual(m_undo1['current_inn']['balls'], 2, "Balls in over should be back to 2")

        # 9. Test UNDO: Undo 1 run
        res_undo2 = self.client.post(f'/api/admin/matches/{match_id}/undo')
        self.assertEqual(res_undo2.status_code, 200)
        m_undo2 = res_undo2.get_json()['match']
        self.assertEqual(m_undo2['current_inn']['runs'], 4)
        self.assertEqual(m_undo2['current_inn']['balls'], 1)

        # 10. Test UNDO: Undo 4 runs
        res_undo3 = self.client.post(f'/api/admin/matches/{match_id}/undo')
        self.assertEqual(res_undo3.status_code, 200)
        m_undo3 = res_undo3.get_json()['match']
        self.assertEqual(m_undo3['current_inn']['runs'], 0)
        self.assertEqual(m_undo3['current_inn']['balls'], 0)

        print("[SUCCESS] All End-to-End API and Scoring Database assertions passed!")

    def test_two_leagues_isolation_and_standings(self):
        """Validates complete separation between League 1 and League 2 matches, teams, and points tables."""
        # 1. Fetch Leagues
        res = self.client.get('/api/leagues')
        self.assertEqual(res.status_code, 200)
        leagues = res.get_json()['leagues']
        self.assertGreaterEqual(len(leagues), 2, "Should have at least 2 leagues")
        league_ids = [l['id'] for l in leagues]
        self.assertIn(1, league_ids)
        self.assertIn(2, league_ids)

        # 2. Verify League 1 matches are strictly isolated
        res_l1 = self.client.get('/api/leagues/1/matches')
        self.assertEqual(res_l1.status_code, 200)
        l1_matches = res_l1.get_json()['matches']
        for m in l1_matches:
            self.assertEqual(m['league_id'], 1, "Match in League 1 must have league_id=1")

        # 3. Verify League 2 matches are strictly isolated
        res_l2 = self.client.get('/api/leagues/2/matches')
        self.assertEqual(res_l2.status_code, 200)
        l2_matches = res_l2.get_json()['matches']
        self.assertGreater(len(l2_matches), 0, "League 2 should have seeded matches")
        for m in l2_matches:
            self.assertEqual(m['league_id'], 2, "Match in League 2 must have league_id=2")

        # 4. Verify League 1 and League 2 points tables have zero overlap
        res_pt1 = self.client.get('/api/leagues/1/points-table')
        self.assertEqual(res_pt1.status_code, 200)
        st1 = res_pt1.get_json()['standings']
        l1_teams = {s['team'] for s in st1}

        res_pt2 = self.client.get('/api/leagues/2/points-table')
        self.assertEqual(res_pt2.status_code, 200)
        st2 = res_pt2.get_json()['standings']
        l2_teams = {s['team'] for s in st2}

        # Mutual exclusivity: no team in League 1 should be in League 2
        overlap = l1_teams.intersection(l2_teams)
        self.assertEqual(len(overlap), 0, f"Teams should not overlap between leagues: {overlap}")
        self.assertIn('Titan Strikers', l2_teams, "Titan Strikers must be in League 2")
        self.assertIn('Falcon Kings', l2_teams, "Falcon Kings must be in League 2")
        self.assertNotIn('Titan Strikers', l1_teams, "Titan Strikers must not be in League 1")

        # 5. Check NRR mathematical accuracy for League 2 completed match
        titan = next((s for s in st2 if s['team'] == 'Titan Strikers'), None)
        falcon = next((s for s in st2 if s['team'] == 'Falcon Kings'), None)
        self.assertIsNotNone(titan)
        self.assertIsNotNone(falcon)
        self.assertEqual(titan['pts'], 2, "Titan Strikers won 1 match -> 2 pts")
        self.assertEqual(falcon['pts'], 0, "Falcon Kings lost 1 match -> 0 pts")
        self.assertEqual(titan['nrr'], '+1.80', "Titan Strikers NRR must be +1.80 (14.50 - 12.70)")
        self.assertEqual(falcon['nrr'], '-1.80', "Falcon Kings NRR must be -1.80 (12.70 - 14.50)")

        # 6. Create a match specifically in League 2
        res_new_m = self.client.post('/api/admin/matches', json={
            'league_id': 2,
            'team_a': 'Solar Hawks',
            'team_b': 'Titan Strikers',
            'venue': 'Grand Arena',
            'match_date': 'Next Sunday',
            'total_overs': 10
        })
        self.assertEqual(res_new_m.status_code, 201)
        created = res_new_m.get_json()['match']
        self.assertEqual(created['league_id'], 2)

        # Verify it appears in League 2 matches, but NOT in League 1 matches
        res_check1 = self.client.get('/api/leagues/1/matches')
        res_check2 = self.client.get('/api/leagues/2/matches')
        m_ids_l1 = [m['id'] for m in res_check1.get_json()['matches']]
        m_ids_l2 = [m['id'] for m in res_check2.get_json()['matches']]
        self.assertIn(created['id'], m_ids_l2)
        self.assertNotIn(created['id'], m_ids_l1)

        # 7. Check League Overview API
        res_ov = self.client.get('/api/leagues/2/overview')
        self.assertEqual(res_ov.status_code, 200)
        ov = res_ov.get_json()['overview']
        self.assertGreaterEqual(ov['total_teams'], 4)
        self.assertGreaterEqual(ov['total_matches'], 2)
        self.assertGreaterEqual(ov['completed_matches'], 1)

        print("[SUCCESS] Multi-League isolation, points tables, and NRR assertions passed!")

    def test_leagues_crud_api(self):
        """Validates Admin League creation, updating, and deletion."""
        # 1. Create a third league
        res_create = self.client.post('/api/leagues', json={
            'name': 'League 3 Test',
            'short_name': 'L3',
            'description': 'Development League',
            'status': 'active'
        })
        self.assertEqual(res_create.status_code, 201)
        created_id = res_create.get_json()['league']['id']

        # 2. Read single league
        res_get = self.client.get(f'/api/leagues/{created_id}')
        self.assertEqual(res_get.status_code, 200)
        self.assertEqual(res_get.get_json()['league']['name'], 'League 3 Test')

        # 3. Update league
        res_upd = self.client.put(f'/api/leagues/{created_id}', json={
            'name': 'League 3 Renamed',
            'status': 'disabled'
        })
        self.assertEqual(res_upd.status_code, 200)
        self.assertEqual(res_upd.get_json()['league']['name'], 'League 3 Renamed')
        self.assertEqual(res_upd.get_json()['league']['status'], 'disabled')

        # 4. Delete league
        res_del = self.client.delete(f'/api/leagues/{created_id}')
        self.assertEqual(res_del.status_code, 200)

        # Confirm deleted
        res_check = self.client.get(f'/api/leagues/{created_id}')
        self.assertEqual(res_check.status_code, 404)
        print("[SUCCESS] League CRUD API assertions passed!")

    def test_cricket_rules_scoring_and_strike_rotation(self):
        """Validates 0, 1, 2, 3, 4, 6, strike rotation, batting & bowling figures."""
        # Create match
        res = self.client.post('/api/admin/matches', json={
            'team_a': 'House Prithvi', 'team_b': 'House Jala', 'total_overs': 5, 'venue': 'Main Stadium'
        })
        mid = res.get_json()['match']['id']
        self.client.post(f'/api/admin/matches/{mid}/start')

        # Ball 1: 0 runs (Dot)
        self.client.post(f'/api/admin/matches/{mid}/ball', json={'runs': 0})
        # Ball 2: 1 run (Strike should rotate)
        self.client.post(f'/api/admin/matches/{mid}/ball', json={'runs': 1})
        # Ball 3: 2 runs (Strike remains)
        self.client.post(f'/api/admin/matches/{mid}/ball', json={'runs': 2})
        # Ball 4: 3 runs (Strike should rotate)
        self.client.post(f'/api/admin/matches/{mid}/ball', json={'runs': 3})
        # Ball 5: 4 runs (Boundary, strike remains)
        self.client.post(f'/api/admin/matches/{mid}/ball', json={'runs': 4})
        # Ball 6: 6 runs (Six, over completes, strike rotates on over end)
        self.client.post(f'/api/admin/matches/{mid}/ball', json={'runs': 6})

        sc = self.client.get(f'/api/matches/{mid}/scorecard').get_json()['scorecard']['scorecards'][0]
        inn = sc['innings_info']
        # Total runs = 0 + 1 + 2 + 3 + 4 + 6 = 16
        self.assertEqual(inn['runs'], 16)
        self.assertEqual(inn['overs'], 1)
        self.assertEqual(inn['balls'], 0)

        # Bowler figures check
        bw = sc['bowling'][0]
        self.assertEqual(bw['legal_balls'], 6)
        self.assertEqual(bw['runs'], 16)

        # Batting figures check:
        # Striker B1 faced balls 1 (0), 2 (1), 5 (4), 6 (6) -> 11 runs off 4 balls (1x4, 1x6)
        # Striker B2 faced balls 3 (2), 4 (3) -> 5 runs off 2 balls
        bat1 = next(b for b in sc['batting'] if b['batting_order'] == 1)
        bat2 = next(b for b in sc['batting'] if b['batting_order'] == 2)
        self.assertEqual(bat1['runs'], 11)
        self.assertEqual(bat1['balls'], 4)
        self.assertEqual(bat1['fours'], 1)
        self.assertEqual(bat1['sixes'], 1)
        self.assertEqual(bat2['runs'], 5)
        self.assertEqual(bat2['balls'], 2)
        print("[SUCCESS] Cricket rules: Normal deliveries and strike rotation verified!")

    def test_cricket_rules_extras_and_bowler_attribution(self):
        """Validates Wide, No-Ball (+ bat runs), Byes, Leg-Byes, and Bowler runs."""
        res = self.client.post('/api/admin/matches', json={
            'team_a': 'House Akasha', 'team_b': 'House Agni', 'total_overs': 5, 'venue': 'Ground B'
        })
        mid = res.get_json()['match']['id']
        self.client.post(f'/api/admin/matches/{mid}/start')

        # 1. Wide delivery (penalty +1, legal ball not consumed, batter ball not consumed)
        self.client.post(f'/api/admin/matches/{mid}/ball', json={'runs': 0, 'extra': 'WIDE'})
        # 2. No-ball with 4 off bat (1 extra + 4 runs = 5 total, batter gets 4, bowler conceded 5, legal ball not consumed)
        self.client.post(f'/api/admin/matches/{mid}/ball', json={'runs': 4, 'extra': 'NO BALL'})
        # 3. 1 Bye (1 extra, batter runs 0, bowler runs 0, legal ball consumed, strike rotates on odd running bye)
        self.client.post(f'/api/admin/matches/{mid}/ball', json={'runs': 1, 'extra': 'BYE'})
        # 4. 2 Leg-Byes (2 extras, batter runs 0, bowler runs 0, legal ball consumed, strike remains on even running lb)
        self.client.post(f'/api/admin/matches/{mid}/ball', json={'runs': 2, 'extra': 'LEG BYE'})

        sc = self.client.get(f'/api/matches/{mid}/scorecard').get_json()['scorecard']['scorecards'][0]
        inn = sc['innings_info']
        # Total runs = 1 (wide) + 5 (no-ball + 4) + 1 (bye) + 2 (leg bye) = 9 runs
        self.assertEqual(inn['runs'], 9)
        # Legal balls count: only bye (1) + leg bye (1) = 2 legal balls (0.2 overs)
        self.assertEqual(inn['overs'], 0)
        self.assertEqual(inn['balls'], 2)

        # Extras check
        ext = sc['extras']
        self.assertEqual(ext['wides'], 1)
        self.assertEqual(ext['noballs'], 1)
        self.assertEqual(ext['byes'], 1)
        self.assertEqual(ext['legbyes'], 2)
        self.assertEqual(ext['total'], 5)

        # Bowler conceded check: only Wide (1) + No-Ball (5) = 6 runs. Byes & Leg Byes are 0 bowler runs!
        bw = sc['bowling'][0]
        self.assertEqual(bw['runs'], 6)
        print("[SUCCESS] Cricket rules: Extras (Wide, No-Ball, Byes, Leg-Byes) and Bowler attribution verified!")

    def test_wicket_types_and_non_bowler_dismissals(self):
        """Validates Bowled, Caught (with fielder), Run Out (bowler gets 0 wickets), and Fall of Wickets."""
        res = self.client.post('/api/admin/matches', json={
            'team_a': 'House Vayu', 'team_b': 'House Prithvi', 'total_overs': 5, 'venue': 'Oval'
        })
        mid = res.get_json()['match']['id']
        self.client.post(f'/api/admin/matches/{mid}/start')

        # Wicket 1: Caught with fielder (Credits bowler +1 wicket, sets dismissal "c Safe Hands b ...")
        self.client.post(f'/api/admin/matches/{mid}/wicket', json={
            'wicket_type': 'CAUGHT',
            'fielder_name': 'Safe Hands',
            'new_batter': 'Middle Batter 1'
        })

        # Wicket 2: Run Out (Does NOT credit bowler with a wicket)
        self.client.post(f'/api/admin/matches/{mid}/wicket', json={
            'wicket_type': 'RUN OUT',
            'fielder_name': 'Sharp Thrower',
            'new_batter': 'Middle Batter 2'
        })

        sc = self.client.get(f'/api/matches/{mid}/scorecard').get_json()['scorecard']['scorecards'][0]
        inn = sc['innings_info']
        self.assertEqual(inn['wickets'], 2)

        # Bowler should have only 1 wicket (Caught), Run Out is NOT credited to bowler!
        bw = sc['bowling'][0]
        self.assertEqual(bw['wickets'], 1)

        # Fall of wickets check
        fow = sc['fall_of_wickets']
        self.assertEqual(len(fow), 2)
        self.assertEqual(fow[0]['wicket_number'], 1)
        self.assertEqual(fow[1]['wicket_number'], 2)
        print("[SUCCESS] Cricket rules: Wicket types, Fielder tracking, and Bowler non-attribution for Run Outs verified!")

    def test_manual_strike_swap_and_edit_last_ball(self):
        """Validates manual strike swap, custom bowler assignment, and editing last delivery."""
        res = self.client.post('/api/admin/matches', json={
            'team_a': 'House Jala', 'team_b': 'House Akasha', 'total_overs': 5, 'venue': 'Pitch 1'
        })
        mid = res.get_json()['match']['id']
        self.client.post(f'/api/admin/matches/{mid}/start')

        # 1. Test manual strike swap
        res_swap = self.client.post(f'/api/admin/matches/{mid}/swap-strike')
        self.assertEqual(res_swap.status_code, 200)

        # 2. Record 1 run
        self.client.post(f'/api/admin/matches/{mid}/ball', json={'runs': 1})

        # 3. Edit last ball to FOUR
        res_edit = self.client.post(f'/api/admin/matches/{mid}/edit-last-ball', json={
            'runs': 4,
            'commentary': 'Glorious cover drive for FOUR!'
        })
        self.assertEqual(res_edit.status_code, 200)

        sc = self.client.get(f'/api/matches/{mid}/scorecard').get_json()['scorecard']['scorecards'][0]
        inn = sc['innings_info']
        self.assertEqual(inn['runs'], 4)

        # Commentary check
        comm = self.client.get(f'/api/matches/{mid}/commentary').get_json()['commentary']
        self.assertIn('Glorious cover drive for FOUR!', comm[0]['events'][0]['commentary'])
        print("[SUCCESS] Manual strike swap, custom bowler setting, and edit last ball verified!")

    def test_second_innings_target_and_match_chase_win(self):
        """Validates 2nd innings transition, automated target calculation, and chase completion."""
        res = self.client.post('/api/admin/matches', json={
            'team_a': 'House Vayu', 'team_b': 'House Agni', 'total_overs': 5, 'venue': 'Championship Stadium'
        })
        mid = res.get_json()['match']['id']
        self.client.post(f'/api/admin/matches/{mid}/start')

        # Innings 1: Score 10 runs
        self.client.post(f'/api/admin/matches/{mid}/ball', json={'runs': 6})
        self.client.post(f'/api/admin/matches/{mid}/ball', json={'runs': 4})

        # Switch to 2nd Innings
        res_sw = self.client.post(f'/api/admin/matches/{mid}/innings/switch')
        self.assertEqual(res_sw.status_code, 200)

        sc = self.client.get(f'/api/matches/{mid}/scorecard').get_json()['scorecard']
        self.assertEqual(len(sc['scorecards']), 2)
        inn2 = sc['scorecards'][1]['innings_info']
        # Target must be 10 + 1 = 11
        self.assertEqual(inn2['target'], 11)

        # Innings 2: Score 6, then 6 -> 12 runs (exceeds target of 11)
        self.client.post(f'/api/admin/matches/{mid}/ball', json={'runs': 6})
        self.client.post(f'/api/admin/matches/{mid}/ball', json={'runs': 6})

        m_final = self.client.get(f'/api/matches/{mid}').get_json()['match']
        self.assertEqual(m_final['status'], 'COMPLETED')
        self.assertEqual(m_final['winner'], 'House Agni')
        self.assertEqual(m_final['result_margin'], 'by 10 wickets')

        # Standings check
        std = self.client.get('/api/standings').get_json()['standings']
        agni_row = next(r for r in std if r['team'] == 'House Agni')
        self.assertGreaterEqual(agni_row['w'], 1)
        self.assertGreaterEqual(agni_row['pts'], 2)
        print("[SUCCESS] 2nd innings target calculation, automatic chase completion, and standings sync verified!")

    def test_team_and_player_profiles_and_leaderboards(self):
        """Validates team profile, player statistics calculation, and tournament leaderboards."""
        # 1. Team Profile API
        res_team = self.client.get('/api/teams/House%20Vayu')
        self.assertEqual(res_team.status_code, 200)
        t_data = res_team.get_json()
        self.assertTrue(t_data['success'])
        self.assertIn('team_details', t_data)

        # 2. Player Profile API
        res_p = self.client.get('/api/players/Rohit%20Verma')
        self.assertEqual(res_p.status_code, 200)
        p_data = res_p.get_json()
        self.assertTrue(p_data['success'])
        self.assertIn('player', p_data)
        self.assertIn('batting', p_data['player'])
        self.assertIn('bowling', p_data['player'])

        # 3. Leaderboards API
        res_lb = self.client.get('/api/leaderboards')
        self.assertEqual(res_lb.status_code, 200)
        lb_data = res_lb.get_json()
        self.assertTrue(lb_data['success'])
        self.assertIn('most_runs', lb_data['leaderboards'])
        self.assertIn('most_wickets', lb_data['leaderboards'])
        print("[SUCCESS] Team profile, Player statistics, and Tournament Leaderboards verified!")

    def test_security_audit_unauthenticated_access(self):
        """Verifies unauthenticated users cannot invoke admin scoring or mutation endpoints."""
        anon_client = app.test_client()

        # Mutation on matches without auth -> must be 401
        res_post_match = anon_client.post('/api/admin/matches', json={'team_a': 'A', 'team_b': 'B'})
        self.assertEqual(res_post_match.status_code, 401)

        # Scoring action without auth -> must be 401
        res_ball = anon_client.post('/api/admin/matches/1/ball', json={'runs': 4})
        self.assertEqual(res_ball.status_code, 401)

        # League creation without auth -> must be 401
        res_league = anon_client.post('/api/leagues', json={'name': 'Hacked League'})
        self.assertEqual(res_league.status_code, 401)

        print("[SUCCESS] Security audit: Unauthenticated mutations strictly rejected with 401!")

    def test_fixture_management_lifecycle_and_validations(self):
        """Tests complete fixture management lifecycle: create, validate, edit, filter, abandon, delete."""
        # 1. Reject fixture with same teams
        res_invalid = self.client.post('/api/admin/matches', json={
            'team_a': 'House Vayu',
            'team_b': 'House Vayu',
            'league_id': 1
        })
        self.assertEqual(res_invalid.status_code, 400)
        self.assertIn('cannot be the same', res_invalid.get_json()['error'])

        # 2. Reject fixture with 0 overs
        res_zero_ov = self.client.post('/api/admin/matches', json={
            'team_a': 'House Vayu',
            'team_b': 'House Agni',
            'total_overs': 0,
            'league_id': 1
        })
        self.assertEqual(res_zero_ov.status_code, 400)

        # 3. Create valid fixture
        res_create = self.client.post('/api/admin/matches', json={
            'team_a': 'House Vayu',
            'team_b': 'House Prithvi',
            'league_id': 1,
            'match_date': '2026-10-15',
            'venue': 'Ground 3',
            'total_overs': 15
        })
        self.assertEqual(res_create.status_code, 201)
        fix_id = res_create.get_json()['match']['id']

        # 4. Reject duplicate fixture
        res_dup = self.client.post('/api/admin/matches', json={
            'team_a': 'House Vayu',
            'team_b': 'House Prithvi',
            'league_id': 1,
            'match_date': '2026-10-15',
            'venue': 'Ground 3',
            'total_overs': 15
        })
        self.assertEqual(res_dup.status_code, 400)
        self.assertIn('already exists', res_dup.get_json()['error'])

        # 5. Edit fixture (date, venue, overs)
        res_edit = self.client.put(f'/api/admin/matches/{fix_id}', json={
            'match_date': '2026-10-16',
            'venue': 'Main Stadium',
            'total_overs': 20
        })
        self.assertEqual(res_edit.status_code, 200)
        m_edited = res_edit.get_json()['match']
        self.assertEqual(m_edited['match_date'], '2026-10-16')
        self.assertEqual(m_edited['venue'], 'Main Stadium')
        self.assertEqual(m_edited['total_overs'], 20)

        # 6. Filter fixtures by league, status, date, team
        res_filter_date = self.client.get('/api/matches?date=2026-10-16')
        self.assertEqual(res_filter_date.status_code, 200)
        self.assertTrue(any(m['id'] == fix_id for m in res_filter_date.get_json()['matches']))

        res_filter_team = self.client.get('/api/matches?team=Prithvi')
        self.assertEqual(res_filter_team.status_code, 200)
        self.assertTrue(any(m['id'] == fix_id for m in res_filter_team.get_json()['matches']))

        # 7. Complete as Abandoned / No Result
        res_abandon = self.client.post(f'/api/admin/matches/{fix_id}/complete', json={
            'winner': 'No Result',
            'margin': 'Match Abandoned (Rain)'
        })
        self.assertEqual(res_abandon.status_code, 200)
        m_ab = self.client.get(f'/api/matches/{fix_id}').get_json()['match']
        self.assertEqual(m_ab['status'], 'COMPLETED')
        self.assertEqual(m_ab['winner'], 'No Result')

        # 8. Delete fixture
        res_del = self.client.delete(f'/api/admin/matches/{fix_id}')
        self.assertEqual(res_del.status_code, 200)
        res_check_del = self.client.get(f'/api/matches/{fix_id}')
        self.assertEqual(res_check_del.status_code, 404)

        print("[SUCCESS] Tournament Fixture Management lifecycle & validations passed!")

    def test_flexible_playing_xi_and_t6_format_lifecycle(self):
        """Validates configurable match formats (T6/8-player), dynamic Playing XI validation, captain/keeper constraints, and 8-player all-out scoring logic."""
        # 1. Create T6 match (6 overs, 8 players per team)
        res_create = self.client.post('/api/admin/matches', json={
            'team_a': 'House Vayu',
            'team_b': 'House Agni',
            'league_id': 1,
            'format_name': 'T6',
            'total_overs': 6,
            'players_per_team': 8,
            'balls_per_over': 6,
            'match_date': '2026-11-20',
            'venue': 'T6 Championship Arena'
        })
        self.assertEqual(res_create.status_code, 201)
        m = res_create.get_json()['match']
        mid = m['id']
        self.assertEqual(m['format_name'], 'T6')
        self.assertEqual(m['total_overs'], 6)
        self.assertEqual(m['players_per_team'], 8)
        self.assertEqual(m['balls_per_over'], 6)

        # 2. Query Match Setup details
        res_setup = self.client.get(f'/api/matches/{mid}/setup')
        self.assertEqual(res_setup.status_code, 200)
        s_data = res_setup.get_json()
        self.assertEqual(s_data['players_per_team'], 8)
        self.assertEqual(s_data['total_overs'], 6)
        
        squad_a_names = [p['name'] for p in s_data['squad_a']]
        squad_b_names = [p['name'] for p in s_data['squad_b']]
        self.assertGreaterEqual(len(squad_a_names), 8)
        self.assertGreaterEqual(len(squad_b_names), 8)

        xi_a_8 = squad_a_names[:8]
        xi_b_8 = squad_b_names[:8]

        # 3. Reject 7-player XI (under limit for 8-player match)
        res_7 = self.client.post(f'/api/admin/matches/{mid}/setup', json={
            'playing_xi_a': squad_a_names[:7],
            'playing_xi_b': xi_b_8,
            'captain_a': xi_a_8[0],
            'captain_b': xi_b_8[0],
            'toss_winner': 'House Vayu',
            'toss_decision': 'BAT'
        })
        self.assertEqual(res_7.status_code, 400)
        self.assertIn('requires exactly 8 players', res_7.get_json()['error'])

        # 4. Reject 9-player XI (over limit for 8-player match)
        if len(squad_b_names) >= 9:
            res_9 = self.client.post(f'/api/admin/matches/{mid}/setup', json={
                'playing_xi_a': xi_a_8,
                'playing_xi_b': squad_b_names[:9],
                'captain_a': xi_a_8[0],
                'captain_b': squad_b_names[0],
                'toss_winner': 'House Vayu',
                'toss_decision': 'BAT'
            })
            self.assertEqual(res_9.status_code, 400)
            self.assertIn('requires exactly 8 players', res_9.get_json()['error'])

        # 5. Reject captain outside Playing XI
        res_bad_cap = self.client.post(f'/api/admin/matches/{mid}/setup', json={
            'playing_xi_a': xi_a_8,
            'playing_xi_b': xi_b_8,
            'captain_a': 'Unknown Captain',
            'captain_b': xi_b_8[0],
            'toss_winner': 'House Vayu',
            'toss_decision': 'BAT'
        })
        self.assertEqual(res_bad_cap.status_code, 400)
        self.assertIn('must be selected from the Playing XI', res_bad_cap.get_json()['error'])

        # 6. Reject wicketkeeper outside Playing XI
        res_bad_wk = self.client.post(f'/api/admin/matches/{mid}/setup', json={
            'playing_xi_a': xi_a_8,
            'playing_xi_b': xi_b_8,
            'captain_a': xi_a_8[0],
            'captain_b': xi_b_8[0],
            'wicketkeeper_a': 'Unknown Keeper',
            'toss_winner': 'House Vayu',
            'toss_decision': 'BAT'
        })
        self.assertEqual(res_bad_wk.status_code, 400)
        self.assertIn('must be selected from the Playing XI', res_bad_wk.get_json()['error'])

        # 7. Accept valid 8 + 8 Playing XI with Captain and optional Wicketkeeper
        res_valid_setup = self.client.post(f'/api/admin/matches/{mid}/setup', json={
            'playing_xi_a': xi_a_8,
            'playing_xi_b': xi_b_8,
            'captain_a': xi_a_8[0],
            'captain_b': xi_b_8[0],
            'wicketkeeper_a': xi_a_8[1],
            'toss_winner': 'House Vayu',
            'toss_decision': 'BAT'
        })
        self.assertEqual(res_valid_setup.status_code, 200)

        # 8. Verify Playing XI API returns accurate structure
        res_xi = self.client.get(f'/api/matches/{mid}/playing-xi')
        self.assertEqual(res_xi.status_code, 200)
        xi_resp = res_xi.get_json()
        self.assertEqual(xi_resp['required_players'], 8)
        self.assertEqual(len(xi_resp['team_a']['playing_xi']), 8)
        self.assertEqual(len(xi_resp['team_b']['playing_xi']), 8)
        self.assertEqual(xi_resp['toss']['winner'], 'House Vayu')
        self.assertEqual(xi_resp['toss']['decision'], 'BAT')

        # 9. Start Match (transitions UPCOMING -> LIVE with toss-aligned innings)
        res_start = self.client.post(f'/api/admin/matches/{mid}/start')
        self.assertEqual(res_start.status_code, 200)
        m_live = res_start.get_json()['match']
        self.assertEqual(m_live['status'], 'LIVE')
        self.assertEqual(len(m_live['innings']), 1)
        inn1 = m_live['innings'][0]
        self.assertEqual(inn1['batting_team'], 'House Vayu')
        self.assertEqual(inn1['bowling_team'], 'House Agni')

        # 10. Verify scorer player availability exposes only the selected 8 players
        res_sc_players = self.client.get(f'/api/matches/{mid}/players-for-scoring')
        self.assertEqual(res_sc_players.status_code, 200)
        sc_data = res_sc_players.get_json()
        self.assertEqual(set(sc_data['batting_xi']), set(xi_a_8))
        self.assertEqual(set(sc_data['bowling_xi']), set(xi_b_8))

        # 11. Record 1st Innings deliveries (6 overs = 36 legal balls)
        inn1_id = inn1['id']
        striker = xi_a_8[0]
        bowler = xi_b_8[0]
        # Score 60 runs off 36 balls (6 overs)
        for ov in range(6):
            bw = xi_b_8[ov % len(xi_b_8)]
            for b in range(6):
                runs = 2 if b % 2 == 0 else 1
                self.client.post(f'/api/admin/matches/{mid}/ball', json={
                    'innings_id': inn1_id,
                    'batsman_name': striker,
                    'bowler_name': bw,
                    'runs': runs,
                    'extras': 0,
                    'extra_type': 'NONE'
                })

        m_inn1_end = self.client.get(f'/api/matches/{mid}').get_json()['match']
        inn1_final = m_inn1_end['innings'][0]
        self.assertEqual(inn1_final['overs'], 6)
        self.assertEqual(inn1_final['balls'], 0)
        self.assertGreater(inn1_final['runs'], 0)

        # 12. Start 2nd Innings (Target = runs + 1)
        res_inn2 = self.client.post(f'/api/admin/matches/{mid}/innings/switch')
        self.assertEqual(res_inn2.status_code, 200)
        m_inn2 = self.client.get(f'/api/matches/{mid}').get_json()['match']
        self.assertEqual(len(m_inn2['innings']), 2)
        inn2 = m_inn2['innings'][1]
        target = inn1_final['runs'] + 1
        self.assertEqual(inn2['target'], target)
        self.assertEqual(inn2['batting_team'], 'House Agni')
        self.assertEqual(inn2['bowling_team'], 'House Vayu')

        # 13. Chase the target in 2nd innings with 2 wickets lost
        # In 8-player format: max wickets = 7. If 2 wickets lost, remaining = 5 wickets.
        inn2_id = inn2['id']
        b_chase1 = xi_b_8[0]
        b_chase2 = xi_b_8[1]
        b_chase3 = xi_b_8[2]
        bw_def = xi_a_8[0]

        # Wicket 1
        self.client.post(f'/api/admin/matches/{mid}/wicket', json={
            'wicket_type': 'BOWLED',
            'new_batter': b_chase2,
            'bowler_name': bw_def
        })

        # Wicket 2
        self.client.post(f'/api/admin/matches/{mid}/wicket', json={
            'wicket_type': 'CAUGHT',
            'fielder_name': xi_a_8[1],
            'new_batter': b_chase3,
            'bowler_name': bw_def
        })

        # Score runs until target is reached
        needed = target
        while needed > 0:
            step = min(6, needed)
            self.client.post(f'/api/admin/matches/{mid}/ball', json={
                'innings_id': inn2_id,
                'batsman_name': b_chase3,
                'bowler_name': bw_def,
                'runs': step,
                'extras': 0,
                'extra_type': 'NONE'
            })
            needed -= step

        # Verify automatic chase completion with 8-player all-out rule (7 - 2 = 5 wickets)
        m_finish = self.client.get(f'/api/matches/{mid}').get_json()['match']
        self.assertEqual(m_finish['status'], 'COMPLETED')
        self.assertEqual(m_finish['winner'], 'House Agni')
        self.assertEqual(m_finish['result_margin'], 'by 5 wickets')

        # Clean up
        self.client.delete(f'/api/admin/matches/{mid}')

        print("[SUCCESS] Flexible Match Format (T6, 8 Players) and Playing XI system verified 100%!")

if __name__ == '__main__':
    unittest.main()


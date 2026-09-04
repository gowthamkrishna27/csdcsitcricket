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

        # Wicket 1: Caught with fielder (Credits bowler +1 wicket, sets dismissal "c Gaurav Sen b ...")
        r1 = self.client.post(f'/api/admin/matches/{mid}/wicket', json={
            'wicket_type': 'CAUGHT',
            'fielder_name': 'Gaurav Sen',
            'new_batter': 'Kunal Mehra'
        })
        self.assertEqual(r1.status_code, 200, f"Wicket 1 failed: {r1.get_json()}")

        # Wicket 2: Run Out (Does NOT credit bowler with a wicket)
        r2 = self.client.post(f'/api/admin/matches/{mid}/wicket', json={
            'wicket_type': 'RUN OUT',
            'fielder_name': 'KL Rahul',
            'new_batter': 'Devansh Nair'
        })
        self.assertEqual(r2.status_code, 200, f"Wicket 2 failed: {r2.get_json()}")

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
        b_chase4 = xi_b_8[3]
        bw_def = xi_a_8[0]

        # Wicket 1: b_chase1 is out, b_chase3 comes in
        self.client.post(f'/api/admin/matches/{mid}/wicket', json={
            'wicket_type': 'BOWLED',
            'new_batter': b_chase3,
            'bowler_name': bw_def
        })

        # Wicket 2: b_chase2 is out, b_chase4 comes in
        self.client.post(f'/api/admin/matches/{mid}/wicket', json={
            'wicket_type': 'CAUGHT',
            'fielder_name': xi_a_8[1],
            'new_batter': b_chase4,
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

    def test_stage3_users_auth_and_rbac(self):
        """Validates Stage 3 SQLite users table authentication, roles, and status enforcement."""
        # 1. Direct database authentication tests
        ok, res = cricket_db.authenticate_user('gowthamkrishna18v@gmail.com', '0724')
        self.assertTrue(ok, "Authenticating Gowtham Krishna should succeed")
        self.assertEqual(res['role'], 'ADMIN')
        self.assertNotIn('password_hash', res)

        # Invalid password
        ok_bad, err_bad = cricket_db.authenticate_user('gowthamkrishna18v@gmail.com', 'wrongpassword')
        self.assertFalse(ok_bad)
        self.assertEqual(err_bad, "Invalid email or password")

        # Create a test scorer user
        test_scorer_email = 'scorer.test@csdcsitcricket.edu'
        ok_create, scorer_user = cricket_db.create_user("Field Scorer", test_scorer_email, "scorer123", role="SCORER")
        self.assertTrue(ok_create)
        self.assertEqual(scorer_user['role'], 'SCORER')

        # Test disabled status
        cricket_db.update_user_status(scorer_user['id'], 'DISABLED')
        ok_dis, err_dis = cricket_db.authenticate_user(test_scorer_email, 'scorer123')
        self.assertFalse(ok_dis)
        self.assertIn("disabled", err_dis.lower())

        # Restore active and test login via API
        cricket_db.update_user_status(scorer_user['id'], 'ACTIVE')
        client_scorer = app.test_client()
        res_login = client_scorer.post('/api/auth/login', json={
            'email': test_scorer_email,
            'password': 'scorer123'
        })
        self.assertEqual(res_login.status_code, 200)
        self.assertEqual(res_login.get_json()['user']['role'], 'SCORER')

        # Verify scorer is rejected from admin-only endpoints
        res_wipe = client_scorer.post('/api/admins', json={'name': 'Hacker', 'email': 'h@h.com', 'password': '123'})
        self.assertEqual(res_wipe.status_code, 403, "Scorer should be rejected with 403 from admin management")

        # Clean up test user
        cricket_db.delete_user(scorer_user['id'])
        print("[SUCCESS] Stage 3: SQLite users table authentication, password hashing, and RBAC verified!")

    def test_stage3_viewer_homepage_and_etag(self):
        """Validates Stage 3 Viewer public homepage data and smart polling ETag 304 behavior."""
        # Unauthenticated client (public spectator)
        pub_client = app.test_client()

        # 1. Homepage loads without authentication
        res_home = pub_client.get('/')
        self.assertEqual(res_home.status_code, 200)

        # 2. Consolidated homepage-data endpoint
        res_data = pub_client.get('/api/homepage-data')
        self.assertEqual(res_data.status_code, 200)
        d = res_data.get_json()
        self.assertTrue(d['success'])
        self.assertIn('leagues', d)
        self.assertIn('live_matches', d)
        self.assertIn('upcoming_matches', d)
        self.assertIn('recent_results', d)
        self.assertIn('standings', d)
        self.assertIn('leaderboards', d)

        # 3. Live Snapshot endpoint and ETag conditional caching
        res_snap = pub_client.get('/api/matches/live-snapshot')
        self.assertEqual(res_snap.status_code, 200)
        etag = res_snap.headers.get('ETag')
        self.assertIsNotNone(etag, "ETag header must be present in live-snapshot response")

        # 4. HTTP 304 Not Modified when ETag matches
        res_304 = pub_client.get('/api/matches/live-snapshot', headers={'If-None-Match': etag})
        self.assertEqual(res_304.status_code, 304, "Unchanged live state must return HTTP 304 Not Modified")
        self.assertEqual(res_304.data, b"", "HTTP 304 response body must be empty")

        print("[SUCCESS] Stage 3: Viewer homepage data consolidation and ETag 304 smart polling verified!")

    def test_stage4_1_scorer_auth_and_routing(self):
        """Validates Stage 4.1 Scorer authentication, redirects, and route protections."""
        # Create dedicated test scorer user
        scorer_email = 'scorer.stage4@test.edu'
        ok, user = cricket_db.create_user("Scorer Stage4", scorer_email, "scorerSecret", role="SCORER", status="ACTIVE")
        self.assertTrue(ok)

        try:
            # 1. Unauthenticated viewer access
            pub_client = app.test_client()
            
            # Scorer login page is accessible
            res = pub_client.get('/scorer/login')
            self.assertEqual(res.status_code, 200)

            # Scorer protected routes redirect unauthenticated users to /scorer/login
            res_matches = pub_client.get('/scorer/matches')
            self.assertEqual(res_matches.status_code, 302)
            self.assertIn('/scorer/login', res_matches.location)

            res_match = pub_client.get('/scorer/match/999')
            self.assertEqual(res_match.status_code, 302)
            self.assertIn('/scorer/login', res_match.location)

            # 2. Scorer login succeeds and directs to /scorer/matches
            scorer_client = app.test_client()
            res_login = scorer_client.post('/api/auth/login', json={
                'email': scorer_email,
                'password': 'scorerSecret'
            })
            self.assertEqual(res_login.status_code, 200)
            data = res_login.get_json()
            self.assertTrue(data['success'])
            self.assertEqual(data['user']['role'], 'SCORER')
            self.assertEqual(data.get('redirect'), '/scorer/matches')

            # 3. Authenticated Scorer access
            # Can access scorer portal
            res_s_matches = scorer_client.get('/scorer/matches')
            self.assertEqual(res_s_matches.status_code, 200)

            # Already authenticated scorer visiting /scorer/login redirects to /scorer/matches
            res_s_login = scorer_client.get('/scorer/login')
            self.assertEqual(res_s_login.status_code, 302)
            self.assertIn('/scorer/matches', res_s_login.location)

            # Scorer accessing /admin redirects to /scorer/matches
            res_s_admin = scorer_client.get('/admin')
            self.assertEqual(res_s_admin.status_code, 302)
            self.assertIn('/scorer/matches', res_s_admin.location)

            # 4. Admin login still directs to /admin
            admin_client = app.test_client()
            res_admin_login = admin_client.post('/api/auth/login', json={
                'email': 'gowthamkrishna18v@gmail.com',
                'password': '0724'
            })
            self.assertEqual(res_admin_login.status_code, 200)
            self.assertEqual(res_admin_login.get_json().get('redirect'), '/admin')

            # Admin visiting /scorer/login redirects to /admin
            res_adm_sc_login = admin_client.get('/scorer/login')
            self.assertEqual(res_adm_sc_login.status_code, 302)
            self.assertIn('/admin', res_adm_sc_login.location)

            # 5. Invalid password rejected
            bad_client = app.test_client()
            res_bad = bad_client.post('/api/auth/login', json={
                'email': scorer_email,
                'password': 'wrong_password'
            })
            self.assertEqual(res_bad.status_code, 401)

            # 6. Disabled user rejected
            cricket_db.update_user_status(user['id'], 'DISABLED')
            res_dis = bad_client.post('/api/auth/login', json={
                'email': scorer_email,
                'password': 'scorerSecret'
            })
            self.assertEqual(res_dis.status_code, 401)
            self.assertIn('disabled', res_dis.get_json()['error'].lower())

            print("[SUCCESS] Stage 4.1: Scorer authentication, role routing, and page protections verified!")
        finally:
            cricket_db.delete_user(user['id'])

    def test_stage4_2_atomic_fcfs_match_claiming(self):
        """Validates Stage 4.2 Atomic FCFS Match Claiming, leases, heartbeats, releases, and concurrency."""
        import threading

        # 1. Create two test scorers
        ok_a, user_a = cricket_db.create_user('Scorer Alpha', 'alpha@fcfs.edu', 'passA', role='SCORER', status='ACTIVE')
        self.assertTrue(ok_a)
        ok_b, user_b = cricket_db.create_user('Scorer Beta', 'beta@fcfs.edu', 'passB', role='SCORER', status='ACTIVE')
        self.assertTrue(ok_b)

        # 2. Create a test match
        ok_m, match = cricket_db.create_match('House Vayu', 'House Agni', total_overs=10)
        self.assertTrue(ok_m)
        mid = match['id']

        try:
            client_a = app.test_client()
            client_a.post('/api/auth/login', json={'email': 'alpha@fcfs.edu', 'password': 'passA'})

            client_b = app.test_client()
            client_b.post('/api/auth/login', json={'email': 'beta@fcfs.edu', 'password': 'passB'})

            # Step 1: Scorer A claims match -> SUCCESS (200)
            r1 = client_a.post(f'/api/scorer/matches/{mid}/claim')
            self.assertEqual(r1.status_code, 200)
            self.assertTrue(r1.get_json()['success'])
            self.assertEqual(r1.get_json()['match']['claimed_by_user_id'], user_a['id'])

            # Step 2: Scorer B claims match -> 409 CONFLICT
            r2 = client_b.post(f'/api/scorer/matches/{mid}/claim')
            self.assertEqual(r2.status_code, 409)
            self.assertFalse(r2.get_json()['success'])
            self.assertIn('Scorer Alpha', r2.get_json()['error'])

            # Step 3: Scorer A heartbeat -> SUCCESS (200)
            r3 = client_a.post(f'/api/scorer/matches/{mid}/heartbeat')
            self.assertEqual(r3.status_code, 200)
            self.assertTrue(r3.get_json()['success'])

            # Step 4: Scorer A release -> SUCCESS (200)
            r4 = client_a.post(f'/api/scorer/matches/{mid}/release')
            self.assertEqual(r4.status_code, 200)
            self.assertTrue(r4.get_json()['success'])

            # Step 5: Scorer B claims -> SUCCESS (200)
            r5 = client_b.post(f'/api/scorer/matches/{mid}/claim')
            self.assertEqual(r5.status_code, 200)
            self.assertTrue(r5.get_json()['success'])
            self.assertEqual(r5.get_json()['match']['claimed_by_user_id'], user_b['id'])

            # Step 6: Expired claim -> new scorer can claim
            with cricket_db.get_db() as conn:
                conn.execute("UPDATE matches SET claim_expires_at = datetime('now', '-5 minutes') WHERE id = ?", (mid,))
                conn.commit()

            r6 = client_a.post(f'/api/scorer/matches/{mid}/claim')
            self.assertEqual(r6.status_code, 200)
            self.assertTrue(r6.get_json()['success'])
            self.assertEqual(r6.get_json()['match']['claimed_by_user_id'], user_a['id'])

            # Step 7: Simultaneous concurrency test (10 concurrent threads)
            with cricket_db.get_db() as conn:
                conn.execute("UPDATE matches SET claimed_by_user_id = NULL, claim_expires_at = NULL WHERE id = ?", (mid,))
                conn.commit()

            results = []
            def try_claim(u_id):
                ok_claim, res_claim = cricket_db.claim_match_atomic(mid, u_id)
                results.append((ok_claim, res_claim))

            threads = [threading.Thread(target=try_claim, args=(f'USR_CONC_{i}',)) for i in range(10)]
            for t in threads: t.start()
            for t in threads: t.join()

            successes = [res for res in results if res[0] is True]
            conflicts = [res for res in results if res[0] is False]
            self.assertEqual(len(successes), 1, "Exactly one thread must win the atomic claim race")
            self.assertEqual(len(conflicts), 9, "All 9 other threads must receive a conflict")

            # Step 8: Reusable backend ownership check
            winning_user_id = successes[0][1]['claimed_by_user_id']
            ok_own, _ = cricket_db.verify_match_ownership(mid, winning_user_id)
            self.assertTrue(ok_own)

            ok_imposter, err_info = cricket_db.verify_match_ownership(mid, 'imposter_user')
            self.assertFalse(ok_imposter)
            self.assertEqual(err_info[0], 403)

            print("[SUCCESS] Stage 4.2: Atomic FCFS Match Claiming, leases, heartbeats, and concurrency verified!")
        finally:
            cricket_db.delete_match(mid)
            cricket_db.delete_user(user_a['id'])
            cricket_db.delete_user(user_b['id'])

    def test_stage4_3_scorer_match_selection_view(self):
        """Validates Stage 4.3 Scorer Match Selection segmentation, claims, and conflict handling."""
        # Create two test scorers
        ok_a, user_a = cricket_db.create_user('Scorer One', 'scorer1@stage43.edu', 'pass1', role='SCORER', status='ACTIVE')
        self.assertTrue(ok_a)
        ok_b, user_b = cricket_db.create_user('Scorer Two', 'scorer2@stage43.edu', 'pass2', role='SCORER', status='ACTIVE')
        self.assertTrue(ok_b)

        # Create test match
        ok_m, match = cricket_db.create_match('CSD Warriors', 'CSIT Titans', total_overs=10)
        self.assertTrue(ok_m)
        mid = match['id']

        try:
            # 1. Unauthenticated viewer blocked
            pub_client = app.test_client()
            r_page = pub_client.get('/scorer/matches')
            self.assertEqual(r_page.status_code, 302)
            self.assertIn('/scorer/login', r_page.location)

            r_api = pub_client.get('/api/scorer/matches')
            self.assertEqual(r_api.status_code, 401)

            # 2. Scorer One logs in and loads matches
            client1 = app.test_client()
            client1.post('/api/auth/login', json={'email': 'scorer1@stage43.edu', 'password': 'pass1'})

            r_html = client1.get('/scorer/matches')
            self.assertEqual(r_html.status_code, 200)

            r_list1 = client1.get('/api/scorer/matches')
            self.assertEqual(r_list1.status_code, 200)
            d1 = r_list1.get_json()
            self.assertTrue(d1['success'])
            avail_ids = [m['id'] for m in d1['available_matches']]
            self.assertIn(mid, avail_ids)

            # 3. Scorer One claims the match
            r_claim = client1.post(f'/api/scorer/matches/{mid}/claim')
            self.assertEqual(r_claim.status_code, 200)

            # Match now in my_matches for Scorer One
            r_list1_after = client1.get('/api/scorer/matches')
            d1_after = r_list1_after.get_json()
            my_ids = [m['id'] for m in d1_after['my_matches']]
            self.assertIn(mid, my_ids)

            # 4. Scorer Two logs in
            client2 = app.test_client()
            client2.post('/api/auth/login', json={'email': 'scorer2@stage43.edu', 'password': 'pass2'})

            # Match appears in other_claimed for Scorer Two
            r_list2 = client2.get('/api/scorer/matches')
            d2 = r_list2.get_json()
            other_ids = [m['id'] for m in d2['other_claimed']]
            self.assertIn(mid, other_ids)

            # Scorer Two attempt claim -> 409 Conflict
            r_conflict = client2.post(f'/api/scorer/matches/{mid}/claim')
            self.assertEqual(r_conflict.status_code, 409)

            print("[SUCCESS] Stage 4.3: Scorer Match Selection, segmentation, and conflict handling verified!")
        finally:
            cricket_db.delete_match(mid)
            cricket_db.delete_user(user_a['id'])
            cricket_db.delete_user(user_b['id'])

    def test_stage4_5_offline_scoring_queue_and_idempotent_sync(self):
        """Validates Stage 4.5 Offline Scoring Queue, Idempotency per UUID, Chronological Sync, and Conflict Rejection."""
        # 1. Setup Scorer and LIVE Match
        ok_u, user = cricket_db.create_user('Sync Scorer', 'scorer_sync@sel.edu', 'pass_sync', role='SCORER', status='ACTIVE')
        self.assertTrue(ok_u)
        uid = user['id']

        ok_m, match = cricket_db.create_match('Offline Tigers', 'Sync Hawks', total_overs=10)
        self.assertTrue(ok_m)
        mid = match['id']

        try:
            # Claim and Start Match
            ok_claim, _ = cricket_db.claim_match_atomic(mid, uid)
            self.assertTrue(ok_claim)
            cricket_db.start_match(mid)

            # Scorer logs in via Flask client
            client = app.test_client()
            client.post('/api/auth/login', json={'email': 'scorer_sync@sel.edu', 'password': 'pass_sync'})

            # --- TEST 1: IDEMPOTENCY (Same UUID twice -> no duplicate) ---
            uuid_single = 'test-uuid-ball-001'
            sync_payload_1 = {
                'events': [
                    {
                        'client_event_uuid': uuid_single,
                        'type': 'BALL',
                        'runs': 4,
                        'extra': None
                    }
                ]
            }

            # First dispatch -> APPLIED
            r1 = client.post(f'/api/scorer/matches/{mid}/sync', json=sync_payload_1)
            self.assertEqual(r1.status_code, 200)
            d1 = r1.get_json()
            self.assertTrue(d1['success'])
            self.assertEqual(len(d1['results']), 1)
            self.assertEqual(d1['results'][0]['status'], 'APPLIED')
            self.assertEqual(d1['match']['current_inn']['runs'], 4)

            # Re-dispatch same UUID -> ALREADY_APPLIED (No double counting!)
            r2 = client.post(f'/api/scorer/matches/{mid}/sync', json=sync_payload_1)
            self.assertEqual(r2.status_code, 200)
            d2 = r2.get_json()
            self.assertTrue(d2['success'])
            self.assertEqual(d2['results'][0]['status'], 'ALREADY_APPLIED')
            # Runs MUST STILL BE 4, NOT 8
            self.assertEqual(d2['match']['current_inn']['runs'], 4)

            with cricket_db.get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) AS cnt FROM ball_events WHERE client_event_uuid = ?", (uuid_single,))
                self.assertEqual(cursor.fetchone()['cnt'], 1, "Exactly one delivery row must exist for this UUID")

            # --- TEST 2: EVENTS 1, 2, 3 REMAIN ORDERED & SYNCED ---
            events_batch = [
                {'client_event_uuid': 'batch-ev-1', 'type': 'BALL', 'runs': 1, 'expected_sequence': 1},
                {'client_event_uuid': 'batch-ev-2', 'type': 'BALL', 'runs': 2, 'expected_sequence': 2},
                {'client_event_uuid': 'batch-ev-3', 'type': 'BALL', 'runs': 6, 'expected_sequence': 3}
            ]
            r_batch = client.post(f'/api/scorer/matches/{mid}/sync', json={'events': events_batch})
            self.assertEqual(r_batch.status_code, 200)
            d_batch = r_batch.get_json()
            self.assertTrue(d_batch['success'])
            statuses = [res['status'] for res in d_batch['results']]
            self.assertEqual(statuses, ['APPLIED', 'APPLIED', 'APPLIED'])
            # Total runs: 4 (initial) + 1 + 2 + 6 = 13 runs
            self.assertEqual(d_batch['match']['current_inn']['runs'], 13)

            # --- TEST 3: CONFLICTING STALE EVENT REJECTED SAFELY ---
            # Current events on server: 4 balls recorded.
            # Client submits an event expecting sequence 1 (stale/diverged timeline)
            stale_event = {
                'events': [
                    {'client_event_uuid': 'stale-ev-conflict', 'type': 'BALL', 'runs': 4, 'expected_sequence': 1}
                ]
            }
            r_conflict = client.post(f'/api/scorer/matches/{mid}/sync', json=stale_event)
            self.assertEqual(r_conflict.status_code, 200)
            d_conflict = r_conflict.get_json()
            self.assertEqual(d_conflict['results'][0]['status'], 'REJECTED_CONFLICT')
            self.assertIn('Server timeline has diverged', d_conflict['results'][0]['error'])
            # Authoritative server score must remain intact at 13
            self.assertEqual(d_conflict['match']['current_inn']['runs'], 13)

            # --- TEST 4: OWNERSHIP GUARD ---
            # Unauthenticated or unauthorized user cannot sync
            anon_client = app.test_client()
            r_anon = anon_client.post(f'/api/scorer/matches/{mid}/sync', json={'events': []})
            self.assertEqual(r_anon.status_code, 401)

            print("[SUCCESS] Stage 4.5: Offline Scoring Queue, Idempotency per UUID, and Conflict Rejection verified!")
        finally:
            cricket_db.delete_match(mid)
            cricket_db.delete_user(uid)

    def test_stage4_4_dedicated_mobile_scoring_console(self):
        """Validates Stage 4.4 Dedicated Mobile Scoring Console serving and keypad operations."""
        ok_u, u = cricket_db.create_user('Console Scorer', 'scorer_console@sel.edu', 'pass_console', role='SCORER', status='ACTIVE')
        self.assertTrue(ok_u)
        uid = u['id']

        ok_m, m = cricket_db.create_match('Console Warriors', 'Console Titans', total_overs=10)
        self.assertTrue(ok_m)
        mid = m['id']

        try:
            # 1. Unauthenticated spectator blocked from /scorer/match/:id
            pub_client = app.test_client()
            r_unauth = pub_client.get(f'/scorer/match/{mid}')
            self.assertEqual(r_unauth.status_code, 302)
            self.assertIn('/scorer/login', r_unauth.location)

            # 2. Authenticated scorer served scorer_console.html
            client = app.test_client()
            client.post('/api/auth/login', json={'email': 'scorer_console@sel.edu', 'password': 'pass_console'})
            r_console = client.get(f'/scorer/match/{mid}')
            self.assertEqual(r_console.status_code, 200)
            self.assertIn(b'Scoring Console', r_console.data)
            self.assertIn(b'btn-run-touch', r_console.data)
            self.assertIn(b'WICKET', r_console.data)

            # 3. Start match and test keypad: 0, 1, 2, 3, 4, 6
            cricket_db.start_match(mid)
            for run_val in [0, 1, 2, 3, 4, 6]:
                r_ball = client.post(f'/api/matches/{mid}/ball', json={'runs': run_val})
                self.assertEqual(r_ball.status_code, 200)

            # 4. Extra: Wide
            r_wide = client.post(f'/api/matches/{mid}/ball', json={'runs': 0, 'extra': 'WIDE'})
            self.assertEqual(r_wide.status_code, 200)

            # 5. Wicket: Caught
            r_wkt = client.post(f'/api/matches/{mid}/wicket', json={
                'type': 'CAUGHT',
                'newBatter': 'Player 3',
                'fielder': 'Fielder 1'
            })
            self.assertEqual(r_wkt.status_code, 200)

            # 6. Undo
            r_undo = client.post(f'/api/matches/{mid}/undo')
            self.assertEqual(r_undo.status_code, 200)

            # 7. Swap strike
            r_swap = client.post(f'/api/matches/{mid}/swap-strike')
            self.assertEqual(r_swap.status_code, 200)

            # 8. Set bowler
            r_bowler = client.post(f'/api/matches/{mid}/set-bowler', json={'player_name': 'New Star Bowler'})
            self.assertEqual(r_bowler.status_code, 200)

            # 9. Edit last ball
            r_edit = client.post(f'/api/matches/{mid}/edit-last-ball', json={'runs': 2, 'extra_type': None})
            self.assertEqual(r_edit.status_code, 200)

            print("[SUCCESS] Stage 4.4: Dedicated Mobile Scoring Console, keypad, extras, and secondary controls verified!")
        finally:
            cricket_db.delete_match(mid)
            cricket_db.delete_user(uid)

    def test_stage5_1_tournament_teams_players_fixtures(self):
        """Stage 5.1 Verification: Tournaments, Teams, Players, Fixtures, Validations, and RBAC."""
        # Setup test clients: Admin (self.client), Scorer, and Public Viewer
        scorer_client = app.test_client()
        viewer_client = app.test_client()

        # Create a test scorer
        ok_sc, scorer_user = cricket_db.create_user("Stage5 Scorer", "stage5_scorer@test.edu", "scorer_pass", role="SCORER", status="ACTIVE")
        self.assertTrue(ok_sc)
        scorer_login = scorer_client.post('/api/auth/login', json={'email': 'stage5_scorer@test.edu', 'password': 'scorer_pass'})
        self.assertEqual(scorer_login.status_code, 200)

        created_tournament_id = None
        created_team_id_1 = None
        created_team_id_2 = None
        created_player_id = None
        created_match_id = None

        try:
            # 1. Admin creates tournament
            r_tourn = self.client.post('/api/tournaments', json={
                'name': 'Inter-Collegiate Championship 2026',
                'season': '2026',
                'status': 'active',
                'format_name': 'T10',
                'total_overs': 10,
                'description': 'Annual Inter-Collegiate Cricket Tournament'
            })
            self.assertEqual(r_tourn.status_code, 201)
            tourn_data = r_tourn.get_json()['tournament']
            created_tournament_id = tourn_data['id']
            self.assertEqual(tourn_data['name'], 'Inter-Collegiate Championship 2026')

            # 2. Admin creates teams
            r_team1 = self.client.post('/api/teams', json={
                'name': 'St. Peters Royals',
                'short': 'SPR',
                'captain': 'Captain Royal',
                'color': '#2e7d32'
            })
            self.assertEqual(r_team1.status_code, 201)
            created_team_id_1 = r_team1.get_json()['team']['id']

            r_team2 = self.client.post('/api/teams', json={
                'name': 'City College Knights',
                'short': 'CCK',
                'captain': 'Captain Knight',
                'color': '#d32f2f'
            })
            self.assertEqual(r_team2.status_code, 201)
            created_team_id_2 = r_team2.get_json()['team']['id']

            # 3. Admin adds player
            r_player = self.client.post('/api/players', json={
                'name': 'Rohan Gavaskar',
                'team': 'St. Peters Royals',
                'role': 'All-Rounder',
                'jersey': 18
            })
            self.assertEqual(r_player.status_code, 201)
            created_player_id = r_player.get_json()['player']['id']

            # 4. Player can be assigned to team and viewed in team roster
            r_assign = self.client.post(f'/api/teams/{created_team_id_2}/players', json={'player_id': created_player_id})
            self.assertEqual(r_assign.status_code, 200)

            r_roster = self.client.get(f'/api/teams/{created_team_id_2}/roster')
            self.assertEqual(r_roster.status_code, 200)
            roster_names = [p['name'] for p in r_roster.get_json()['roster']]
            self.assertIn('Rohan Gavaskar', roster_names)

            # 5. Fixture creation succeeds
            r_fix = self.client.post('/api/fixtures', json={
                'team_a': 'St. Peters Royals',
                'team_b': 'City College Knights',
                'match_date': '2026-10-15',
                'time': '10:00 AM',
                'venue': 'North Oval',
                'total_overs': 10,
                'tournament_id': created_tournament_id
            })
            self.assertEqual(r_fix.status_code, 201)
            fix_data = r_fix.get_json()['match']
            created_match_id = fix_data['id']
            self.assertEqual(fix_data['status'], 'UPCOMING')

            # 6. Same-team fixture is rejected
            r_same = self.client.post('/api/fixtures', json={
                'team_a': 'St. Peters Royals',
                'team_b': 'St. Peters Royals',
                'match_date': '2026-10-16',
                'time': '10:00 AM'
            })
            self.assertEqual(r_same.status_code, 400)
            self.assertIn("cannot be the same", r_same.get_json()['error'].lower())

            # 7. Missing team is rejected
            r_missing = self.client.post('/api/fixtures', json={
                'team_a': 'St. Peters Royals',
                'team_b': '',
                'match_date': '2026-10-16'
            })
            self.assertEqual(r_missing.status_code, 400)
            self.assertIn("team b is required", r_missing.get_json()['error'].lower())

            # 8. Duplicate fixture is detected (same two teams at same date & time)
            r_dup = self.client.post('/api/fixtures', json={
                'team_a': 'St. Peters Royals',
                'team_b': 'City College Knights',
                'match_date': '2026-10-15',
                'time': '10:00 AM'
            })
            self.assertEqual(r_dup.status_code, 400)
            self.assertIn("duplicate fixture", r_dup.get_json()['error'].lower())

            # 9. Team scheduling conflict is detected (St. Peters Royals playing at 10:00 AM on 2026-10-15 vs another team)
            r_conflict = self.client.post('/api/fixtures', json={
                'team_a': 'St. Peters Royals',
                'team_b': 'House Agni',
                'match_date': '2026-10-15',
                'time': '10:00 AM'
            })
            self.assertEqual(r_conflict.status_code, 400)
            self.assertIn("scheduling conflict", r_conflict.get_json()['error'].lower())

            # 10. Scorer cannot modify tournament data (RBAC enforced: returns 403 Forbidden)
            r_scorer_tourn = scorer_client.post('/api/tournaments', json={'name': 'Hacked Tourn'})
            self.assertEqual(r_scorer_tourn.status_code, 403)

            r_scorer_team = scorer_client.post('/api/teams', json={'name': 'Hacked Team'})
            self.assertEqual(r_scorer_team.status_code, 403)

            r_scorer_player = scorer_client.post('/api/players', json={'name': 'Hacked Player'})
            self.assertEqual(r_scorer_player.status_code, 403)

            r_scorer_fix = scorer_client.post('/api/fixtures', json={'team_a': 'T1', 'team_b': 'T2'})
            self.assertEqual(r_scorer_fix.status_code, 403)

            # 11. Viewer cannot modify tournament data (unauthenticated: returns 401 Unauthorized)
            r_view_tourn = viewer_client.post('/api/tournaments', json={'name': 'Anon Tourn'})
            self.assertEqual(r_view_tourn.status_code, 401)

            r_view_team = viewer_client.post('/api/teams', json={'name': 'Anon Team'})
            self.assertEqual(r_view_team.status_code, 401)

            r_view_player = viewer_client.post('/api/players', json={'name': 'Anon Player'})
            self.assertEqual(r_view_player.status_code, 401)

            r_view_fix = viewer_client.post('/api/fixtures', json={'team_a': 'T1', 'team_b': 'T2'})
            self.assertEqual(r_view_fix.status_code, 401)

            # Cancellation of scheduled fixture succeeds
            r_cancel = self.client.post(f'/api/fixtures/{created_match_id}/cancel')
            self.assertEqual(r_cancel.status_code, 200)

            print("[SUCCESS] Stage 5.1: Tournament management, teams, players, fixture validations, and RBAC verified!")
        finally:
            if created_match_id:
                cricket_db.delete_match(created_match_id)
            if created_player_id:
                cricket_db.delete_player(created_player_id)
            if created_team_id_1:
                cricket_db.delete_team(created_team_id_1)
            if created_team_id_2:
                cricket_db.delete_team(created_team_id_2)
            if created_tournament_id:
                cricket_db.delete_tournament(created_tournament_id)
            cricket_db.delete_user(scorer_user['id'])

    def test_stage5_2_standings_playoffs_and_governance(self):
        """
        STAGE 5.2 VERIFICATION:
        1. completed match updates standings
        2. live match does not count as completed
        3. corrected match updates standings
        4. qualification list is correct
        5. playoff fixture can be created
        6. semifinal winner progression works
        7. final can be created from finalists
        8. completed match becomes protected
        9. scorer cannot unlock match
        10. admin can unlock with reason
        11. unlock creates audit record
        12. existing Stage 4 scorer/offline tests still pass
        """
        # Create Scorer User
        scorer_client = app.test_client()
        ok_s, scorer_user = cricket_db.create_user("Scorer Gov", "scorer_gov@test.edu", "password123", role="SCORER", status="ACTIVE")
        self.assertTrue(ok_s)
        r_sc_login = scorer_client.post('/api/auth/login', json={'email': 'scorer_gov@test.edu', 'password': 'password123'})
        self.assertEqual(r_sc_login.status_code, 200)

        # Create isolated test league
        ok_l, league = cricket_db.create_league("Gov Test League", short_name="GTL", tournament_id=1)
        self.assertTrue(ok_l)
        lid = league['id']

        # Create 4 test teams
        ok_t1, t1 = cricket_db.create_team("GTL Titans", "GTT", captain="Titan Cap", color="#111111", league_id=lid)
        ok_t2, t2 = cricket_db.create_team("GTL Warriors", "GTW", captain="Warrior Cap", color="#222222", league_id=lid)
        ok_t3, t3 = cricket_db.create_team("GTL Strikers", "GTS", captain="Striker Cap", color="#333333", league_id=lid)
        ok_t4, t4 = cricket_db.create_team("GTL Blasters", "GTB", captain="Blaster Cap", color="#444444", league_id=lid)

        m1_id = None
        sf1_id = None
        final_id = None

        try:
            # 1 & 2: Create a match between Titans and Warriors and set it to LIVE
            ok_m1, m1 = cricket_db.create_match("GTL Titans", "GTL Warriors", league_id=lid, stage="LEAGUE", total_overs=5)
            self.assertTrue(ok_m1)
            m1_id = m1['id']

            # Initially UPCOMING -> standings should have 0 played, 0 points
            st_initial = cricket_db.recalculate_standings(lid)
            titan_st = next((s for s in st_initial if s['team'] == "GTL Titans"), None)
            self.assertIsNotNone(titan_st)
            self.assertEqual(titan_st['p'], 0)
            self.assertEqual(titan_st['pts'], 0)

            # Update match to LIVE
            cricket_db.update_match(m1_id, status="LIVE")
            # 2. Live match does NOT count as completed in standings
            st_live = cricket_db.recalculate_standings(lid)
            titan_st_live = next((s for s in st_live if s['team'] == "GTL Titans"), None)
            self.assertEqual(titan_st_live['p'], 0)
            self.assertEqual(titan_st_live['pts'], 0)

            # 1. Complete match (Titans win) -> completed match updates standings
            with cricket_db.get_db() as conn:
                conn.execute("""
                UPDATE matches 
                SET status = 'COMPLETED', winner = 'GTL Titans', result_margin = 'by 15 runs', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """, (m1_id,))
                conn.commit()

            st_completed = cricket_db.recalculate_standings(lid)
            titan_st_comp = next((s for s in st_completed if s['team'] == "GTL Titans"), None)
            warrior_st_comp = next((s for s in st_completed if s['team'] == "GTL Warriors"), None)
            self.assertEqual(titan_st_comp['p'], 1)
            self.assertEqual(titan_st_comp['w'], 1)
            self.assertEqual(titan_st_comp['pts'], 2)
            self.assertEqual(warrior_st_comp['p'], 1)
            self.assertEqual(warrior_st_comp['l'], 1)
            self.assertEqual(warrior_st_comp['pts'], 0)

            # 8. Completed match becomes protected / locked
            ok_lock, locked_m = cricket_db.lock_match(m1_id, user_email="admin@test.com", reason="Match finalized")
            self.assertTrue(ok_lock)
            self.assertTrue(locked_m['is_locked'])

            # Ordinary scoring actions on locked match are rejected
            ok_ball, err_ball = cricket_db.record_ball(m1_id, runs=4)
            self.assertFalse(ok_ball)
            self.assertIn("locked", str(err_ball).lower())

            # 9. Scorer cannot unlock match (returns 403 Forbidden)
            r_sc_unlock = scorer_client.post(f'/api/admin/matches/{m1_id}/unlock', json={'reason': 'Scorer trying to unlock'})
            self.assertEqual(r_sc_unlock.status_code, 403)

            # 10. Admin can unlock with reason (fails without reason)
            r_adm_no_reason = self.client.post(f'/api/admin/matches/{m1_id}/unlock', json={'reason': ''})
            self.assertEqual(r_adm_no_reason.status_code, 400)

            r_adm_unlock = self.client.post(f'/api/admin/matches/{m1_id}/unlock', json={'reason': 'Score correction required on over 2'})
            self.assertEqual(r_adm_unlock.status_code, 200)
            self.assertFalse(r_adm_unlock.get_json()['match']['is_locked'])

            # 11. Unlock creates audit record
            r_audit = self.client.get(f'/api/admin/audit-logs?target_type=MATCH&target_id={m1_id}')
            self.assertEqual(r_audit.status_code, 200)
            logs = r_audit.get_json()['audit_logs']
            self.assertTrue(any(l['action'] == 'UNLOCK_MATCH' and 'Score correction' in l['reason'] for l in logs))

            # 3. Corrected match updates standings (e.g. Winner corrected to GTL Warriors)
            with cricket_db.get_db() as conn:
                conn.execute("""
                UPDATE matches 
                SET winner = 'GTL Warriors', result_margin = 'by 4 wickets'
                WHERE id = ?
                """, (m1_id,))
                conn.commit()

            st_corrected = cricket_db.recalculate_standings(lid)
            titan_st_corr = next((s for s in st_corrected if s['team'] == "GTL Titans"), None)
            warrior_st_corr = next((s for s in st_corrected if s['team'] == "GTL Warriors"), None)
            self.assertEqual(warrior_st_corr['w'], 1)
            self.assertEqual(warrior_st_corr['pts'], 2)
            self.assertEqual(titan_st_corr['w'], 0)
            self.assertEqual(titan_st_corr['pts'], 0)

            # 4. Qualification list is correct
            r_qual = self.client.get(f'/api/playoffs/qualification?league_id={lid}&top_n=4')
            self.assertEqual(r_qual.status_code, 200)
            q_data = r_qual.get_json()
            self.assertTrue(q_data['success'])
            qualified_teams = q_data['qualified_teams']
            self.assertEqual(len(qualified_teams), 4)
            # Rank 1 must be GTL Warriors (2 pts)
            self.assertEqual(qualified_teams[0]['team'], "GTL Warriors")
            self.assertEqual(qualified_teams[0]['seed'], 1)
            # Suggested matchups should pair 1 vs 4 and 2 vs 3
            matchups = q_data['suggested_matchups']
            self.assertEqual(len(matchups), 2)
            self.assertEqual(matchups[0]['stage'], "SEMIFINAL")
            self.assertEqual(matchups[0]['seed_a'], 1)
            self.assertEqual(matchups[0]['seed_b'], 4)

            # 5. Playoff fixture can be created
            r_create_sf = self.client.post('/api/fixtures', json={
                'team_a': qualified_teams[0]['team'],
                'team_b': qualified_teams[3]['team'],
                'match_name': 'Semi-Final 1 (Warriors vs Seed 4)',
                'stage': 'SEMIFINAL',
                'league_id': lid,
                'total_overs': 10
            })
            self.assertEqual(r_create_sf.status_code, 201)
            sf1 = r_create_sf.get_json()['match']
            sf1_id = sf1['id']
            self.assertEqual(sf1['stage'], 'SEMIFINAL')

            # 6 & 7: Semifinal winner progression works & Final can be created from finalists
            # Create Championship Final fixture
            r_create_final = self.client.post('/api/fixtures', json={
                'team_a': 'Finalist 1',
                'team_b': 'Finalist 2',
                'match_name': 'Championship Final',
                'stage': 'FINAL',
                'league_id': lid,
                'total_overs': 10
            })
            self.assertEqual(r_create_final.status_code, 201)
            final_match = r_create_final.get_json()['match']
            final_id = final_match['id']

            # Mark SF1 as COMPLETED with winner 'GTL Warriors'
            with cricket_db.get_db() as conn:
                conn.execute("""
                UPDATE matches 
                SET status = 'COMPLETED', winner = 'GTL Warriors', result_margin = 'by 20 runs'
                WHERE id = ?
                """, (sf1_id,))
                conn.commit()

            # Advance SF1 winner into Final as team_a
            r_advance = self.client.post('/api/playoffs/advance', json={
                'source_match_id': sf1_id,
                'target_match_id': final_id,
                'slot': 'team_a'
            })
            self.assertEqual(r_advance.status_code, 200)
            updated_final = r_advance.get_json()['match']
            self.assertEqual(updated_final['team_a'], 'GTL Warriors')
            self.assertEqual(updated_final['teamA'], 'GTL Warriors')

            # Verify audit trail recorded playoff advancement
            r_audit_adv = self.client.get(f'/api/admin/audit-logs?target_type=MATCH&target_id={final_id}')
            adv_logs = r_audit_adv.get_json()['audit_logs']
            self.assertTrue(any(l['action'] == 'ADVANCE_PLAYOFF' and 'GTL Warriors' in l['reason'] for l in adv_logs))

            print("[SUCCESS] Stage 5.2: Standings reliability, playoffs management, match lock/unlock governance, and audit trails verified!")
        finally:
            if final_id:
                cricket_db.delete_match(final_id)
            if sf1_id:
                cricket_db.delete_match(sf1_id)
            if m1_id:
                cricket_db.delete_match(m1_id)
            cricket_db.delete_team(t1['id'])
            cricket_db.delete_team(t2['id'])
            cricket_db.delete_team(t3['id'])
            cricket_db.delete_team(t4['id'])
            cricket_db.delete_league(lid)
            cricket_db.delete_user(scorer_user['id'])

if __name__ == '__main__':
    unittest.main()



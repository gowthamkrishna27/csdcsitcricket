import unittest
import json
import cricket_db
from server import app

class CricketIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        # Login as admin
        res = self.client.post('/api/auth/login', json={
            'email': 'admin@hpl.cricket',
            'password': 'admin123'
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

if __name__ == '__main__':
    unittest.main()

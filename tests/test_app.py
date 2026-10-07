import json
import os
import sqlite3
import tempfile
import unittest
from urllib.parse import urlparse

from app import create_app


class DrawAppTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database = os.path.join(self.temp_dir.name, "draws.sqlite3")
        self.app = create_app({
            "TESTING": True,
            "DATABASE": database,
            "APP_NAME": "Test Draw",
            "CAPTAIN_LABEL": "Captains",
            "PARTICIPANT_LABEL": "Players",
            "TEAM_LABEL": "Side",
        })
        self.client = self.app.test_client()
        self.database = database
        self.addCleanup(self.temp_dir.cleanup)

    def create_draw(self, captains, participants, max_team_size):
        return self.client.post("/draw", data={
            "title": "Saturday match",
            "captains": "\n".join(captains),
            "participants": "\n".join(participants),
            "max_team_size": str(max_team_size),
        })

    def saved_payload(self, location):
        token = urlparse(location).path.rsplit("/", 1)[-1]
        connection = sqlite3.connect(self.database)
        try:
            row = connection.execute("SELECT payload FROM saved_draw WHERE token = ?", (token,)).fetchone()
        finally:
            connection.close()
        return token, json.loads(row[0])

    def test_draw_balances_teams_and_keeps_overflow(self):
        participants = ["Player \u00c5ke"] + [f"Player {n}" for n in range(2, 8)]
        response = self.create_draw(["Alex", "Morgan"], participants, 3)

        self.assertEqual(response.status_code, 303)
        token, draw = self.saved_payload(response.location)
        counts = [len(team["participants"]) for team in draw["teams"]]
        self.assertEqual(counts, [2, 2])
        self.assertEqual(len(draw["overflow"]), 3)
        self.assertTrue(all(len(team["participants"]) + 1 <= draw["max_team_size"] for team in draw["teams"]))
        all_assigned = [name for team in draw["teams"] for name in team["participants"]]
        self.assertEqual(len(all_assigned) + len(draw["overflow"]), 7)

        page = self.client.get(f"/draw/{token}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Overflow", page.data)
        self.assertIn(b"Saturday match", page.data)

        proxied_page = self.client.get(
            f"/draw/{token}",
            headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "draw.example"},
        )
        self.assertIn(b"https://draw.example/draw/", proxied_page.data)

        pdf = self.client.get(f"/draw/{token}/pdf")
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf.mimetype, "application/pdf")
        self.assertTrue(pdf.data.startswith(b"%PDF"))

    def test_uneven_roster_is_distributed_as_evenly_as_possible(self):
        response = self.create_draw(["Alex", "Morgan"], [f"Player {n}" for n in range(1, 6)], 4)
        _, draw = self.saved_payload(response.location)

        counts = [len(team["participants"]) for team in draw["teams"]]
        self.assertEqual(sorted(counts), [2, 3])
        self.assertEqual(draw["overflow"], [])

    def test_accepts_a_comma_separated_list(self):
        response = self.create_draw(["Alex, Morgan"], ["Jamie, Taylor, Jordan"], 4)
        _, draw = self.saved_payload(response.location)

        self.assertEqual([team["captain"] for team in draw["teams"]], ["Alex", "Morgan"])
        assigned = [name for team in draw["teams"] for name in team["participants"]]
        self.assertCountEqual(assigned, ["Jamie", "Taylor", "Jordan"])

    def test_rejects_invalid_team_size(self):
        response = self.client.post("/draw", data={
            "title": "Bad draw",
            "captains": "Alex",
            "participants": "Jamie",
            "max_team_size": "1",
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"including the captain", response.data)

    def test_unknown_share_link_is_not_found(self):
        self.assertEqual(self.client.get("/draw/not-a-real-token").status_code, 404)


if __name__ == "__main__":
    unittest.main()
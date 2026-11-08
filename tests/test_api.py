"""Web API 集成测试。"""

from __future__ import annotations

import os
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from fastapi.testclient import TestClient  # noqa: E402

from backend.api import create_app  # noqa: E402

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "audio"


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp.name) / "data"
        self.app = create_app(self.data_dir)
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def test_empty_initial_state_and_index(self) -> None:
        state = self.client.get("/api/state").json()
        self.assertEqual(state["schedules"], [])
        self.assertEqual(len(state["audios"]), 2)
        self.assertEqual(state["today"]["count"], 0)
        self.assertNotIn("notifications", state["settings"])
        self.assertTrue((self.data_dir / "config.json").is_file())
        index = self.client.get("/")
        self.assertEqual(index.status_code, 200)
        self.assertIn("自动铃声系统", index.text)

    def test_schedule_crud_and_validation(self) -> None:
        payload = {
            "time": "08:00",
            "name": "第一节课",
            "audio_id": "builtin-up",
            "weekdays": [1, 2, 3, 4, 5],
            "enabled": True,
        }
        created = self.client.post("/api/schedules", json=payload)
        self.assertEqual(created.status_code, 200)
        schedule_id = created.json()["schedule"]["id"]
        state = self.client.get("/api/state").json()
        self.assertEqual(len(state["schedules"]), 1)
        duplicate = self.client.post("/api/schedules", json=payload)
        self.assertEqual(duplicate.status_code, 400)
        patched = self.client.patch(
            f"/api/schedules/{schedule_id}", json={"enabled": False}
        )
        self.assertEqual(patched.status_code, 200)
        self.assertFalse(patched.json()["schedule"]["enabled"])
        deleted = self.client.delete(f"/api/schedules/{schedule_id}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get("/api/state").json()["schedules"], [])

    def test_settings_config_and_reload(self) -> None:
        response = self.client.patch("/api/settings", json={"volume": 0, "paused": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["settings"]["volume"], 0)
        self.assertTrue(response.json()["settings"]["paused"])
        config = self.client.get("/api/config").json()
        self.assertIn('"volume": 0', config["content"])
        self.assertIn('"paused": true', config["content"])

        path = self.data_dir / "config.json"
        text = path.read_text(encoding="utf-8").replace('"volume": 0', '"volume": 41')
        path.write_text(text, encoding="utf-8")
        reloaded = self.client.post("/api/config/reload")
        self.assertEqual(reloaded.status_code, 200)
        state = self.client.get("/api/state").json()
        self.assertEqual(state["settings"]["volume"], 41)

    def test_audio_upload_and_delete(self) -> None:
        wav = (ASSETS / "builtin_up.wav").read_bytes()
        response = self.client.post(
            "/api/audios",
            files=[("files", ("我的上课铃.wav", wav, "audio/wav"))],
        )
        self.assertEqual(response.status_code, 200, response.text)
        added = response.json()["added"]
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]["name"], "我的上课铃")
        deleted = self.client.delete(f"/api/audios/{added[0]['id']}")
        self.assertEqual(deleted.status_code, 200)

    def test_preview_starts_and_stops_audio(self) -> None:
        self.client.patch("/api/settings", json={"volume": 0})
        response = self.client.post("/api/audios/builtin-up/preview")
        self.assertEqual(response.status_code, 200, response.text)
        state = self.client.get("/api/state").json()
        self.assertIsNotNone(state["playing"])
        self.assertEqual(state["playing"]["audio_id"], "builtin-up")
        self.client.post("/api/stop")
        self.assertIsNone(self.client.get("/api/state").json()["playing"])

    def test_template_and_export_import(self) -> None:
        response = self.client.post("/api/schedules/template")
        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.json()["count"], 0)
        exported = self.client.get("/api/export")
        self.assertEqual(exported.status_code, 200)
        bundle = Path(self.temp.name) / "bundle.zip"
        bundle.write_bytes(exported.content)
        with zipfile.ZipFile(bundle) as archive:
            self.assertIn("config.json", archive.namelist())

        self.client.delete("/api/schedules")
        imported = self.client.post(
            "/api/import",
            files={"file": ("bundle.zip", bundle.read_bytes(), "application/zip")},
        )
        self.assertEqual(imported.status_code, 200, imported.text)
        state = self.client.get("/api/state").json()
        self.assertGreater(len(state["schedules"]), 0)
        self.assertTrue(list((self.data_dir / "backups").glob("before-import-*.zip")))

    def test_invalid_config_is_rejected_without_replacing_data(self) -> None:
        before = self.client.get("/api/config").json()["content"]
        response = self.client.put("/api/config", json={"content": "{bad"})
        self.assertEqual(response.status_code, 400)
        after = self.client.get("/api/config").json()["content"]
        self.assertEqual(before, after)

    def test_scheduler_plays_due_schedule(self) -> None:
        self.client.patch("/api/settings", json={"volume": 0})
        now = datetime.now().replace(second=0, microsecond=0)
        schedule = {
            "time": now.strftime("%H:%M"),
            "name": "调度测试",
            "audio_id": "builtin-down",
            "weekdays": [now.isoweekday()],
            "enabled": True,
        }
        self.assertEqual(self.client.post("/api/schedules", json=schedule).status_code, 200)
        service = self.app.state.service
        service.tick(now)
        playing = service.state()["playing"]
        self.assertIsNotNone(playing)
        self.assertEqual(playing["schedule_id"], service.data.schedules[0].id)
        service.stop_playback()


if __name__ == "__main__":
    unittest.main()

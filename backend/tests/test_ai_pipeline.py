import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402


class AIPipelineTests(unittest.TestCase):
    def setUp(self):
        server.runtime_active = True
        server.decision_profile_cache.clear()

    def test_rule_classifier_handles_calm_and_alarm_signals(self):
        state, metadata = server.classify_sensor_state(
            "test-calm",
            {"hr": 82, "br": 18, "motion": 12, "mic": 0.1},
        )
        self.assertEqual(state, "sleeping")
        self.assertEqual(metadata["source"], "rules")

        state, _ = server.classify_sensor_state(
            "test-alarm",
            {"hr": 125, "br": 36, "motion": 410, "mic": 0.9},
        )
        self.assertEqual(state, "alarm")

    def test_llm_threshold_adjustments_are_bounded(self):
        child_id = "test-llm"
        server.sensor_history[child_id].extend(
            [
                {"hr": 85, "br": 19, "motion": 25, "mic": 0.15},
                {"hr": 87, "br": 20, "motion": 31, "mic": 0.18},
            ]
        )
        fake_result = {
            "multipliers": {"alarm_heart_rate_min": 9, "sleep_motion_max": 0.1},
            "reason": "test adjustment",
        }
        with patch.object(server, "DASHSCOPE_API_KEY", "test-key"), patch.object(
            server, "call_llm_json", return_value=fake_result
        ):
            _, metadata = server.classify_sensor_state(
                child_id,
                {"hr": 86, "br": 20, "motion": 28, "mic": 0.17},
            )

        self.assertEqual(metadata["source"], "llm")
        self.assertEqual(
            metadata["thresholds"]["alarm_heart_rate_min"],
            round(server.BASE_DECISION_THRESHOLDS["alarm_heart_rate_min"] * 1.15, 3),
        )
        self.assertEqual(
            metadata["thresholds"]["sleep_motion_max"],
            round(server.BASE_DECISION_THRESHOLDS["sleep_motion_max"] * 0.85, 3),
        )

    def test_camera_features_join_the_shared_trend(self):
        client = server.app.test_client()
        with patch.object(server, "maybe_create_ai_intervention"):
            response = client.post(
                "/api/device/camera-observation",
                json={
                    "child_id": "test-camera",
                    "motion_ratio": 0.08,
                    "gesture": "one",
                    "hands_detected": 1,
                },
            )
        self.assertEqual(response.status_code, 200)
        trend = response.get_json()["trend"]
        self.assertEqual(trend["camera_motion_avg"], 0.08)
        self.assertIn("one", trend["recent_gestures"])
        self.assertEqual(response.get_json()["classified_state"], "need_help")

    def test_continuous_camera_monitor_page_is_available(self):
        response = server.app.test_client().get("/monitor/camera?child_id=test-camera")
        self.assertEqual(response.status_code, 200)
        self.assertIn("不上传照片或视频", response.get_data(as_text=True))
        response.close()

    def test_parent_suggestion_uses_llm_when_configured(self):
        child_id = "test-parent"
        server.sleep_records[child_id].append(
            {"duration_seconds": 3600, "quality": "平稳", "sleep_start": None, "wake_time": None}
        )
        fake_result = {"title": "保持稳定作息", "body": "今晚继续保持固定的睡前流程。", "level": "good"}
        with patch.object(server, "DASHSCOPE_API_KEY", "test-key"), patch.object(
            server, "call_llm_json", return_value=fake_result
        ):
            suggestion = server.ai_parent_suggestion_for(child_id)
        self.assertEqual(suggestion["source"], "llm")
        self.assertEqual(suggestion["title"], fake_result["title"])


if __name__ == "__main__":
    unittest.main()

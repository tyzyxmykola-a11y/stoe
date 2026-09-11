import json
import tempfile
import unittest
from pathlib import Path

from flask import Flask

from model_io import install_model_io_capture, install_model_io_ui, model_io_snapshot


class DummyOllama:
    def __init__(self):
        self.seen_payload = None

    def _json(self, path, payload=None, timeout=30):
        self.seen_payload = payload
        return {"done": True, "response": "{}"}

    def generate(self, *, action_id, role, prompt, schema, output_tokens, seed, resolved_model=None):
        payload = {
            "model": (resolved_model or ("dummy", "digest"))[0],
            "system": "system text",
            "prompt": json.dumps(prompt, sort_keys=True),
            "format": schema,
            "options": {"seed": seed, "num_predict": output_tokens},
        }
        raw = self._json("/api/generate", payload, timeout=900)
        return {}, {"action_id": action_id, "model": payload["model"], "raw": raw}


class DummyCoder:
    def __init__(self, root):
        self.artifact_root = Path(root)
        self.ollama = DummyOllama()


class ModelIoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.coder = DummyCoder(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def artifact_dir(self, action_id):
        return self.coder.artifact_root / action_id.replace(":", "_")

    def test_capture_persists_exact_generate_payload_without_touching_action_dir(self):
        install_model_io_capture(self.coder)
        action_id = "TASK_x:coder:1"
        prompt = {"objective": "change README", "recent_tool_feedback": []}
        schema = {"type": "object"}
        self.coder.ollama.generate(
            action_id=action_id,
            role="coder",
            prompt=prompt,
            schema=schema,
            output_tokens=4000,
            seed=7,
            resolved_model=("qwen3-coder:latest", "digest"),
        )
        sidecar = self.coder.artifact_root / "_model_io" / "TASK_x_coder_1" / "request.json"
        saved = json.loads(sidecar.read_text(encoding="utf-8"))
        self.assertEqual(saved["payload"], self.coder.ollama.seen_payload)
        self.assertEqual(saved["payload"]["model"], "qwen3-coder:latest")
        self.assertEqual(json.loads(saved["payload"]["prompt"]), prompt)
        self.assertFalse(self.artifact_dir(action_id).exists())

    def test_snapshot_combines_sidecar_and_normal_action_artifacts(self):
        action_id = "TASK_x:coder:2"
        sidecar = self.coder.artifact_root / "_model_io" / "TASK_x_coder_2"
        action = self.artifact_dir(action_id)
        sidecar.mkdir(parents=True)
        action.mkdir(parents=True)
        (sidecar / "request.json").write_text(json.dumps({"payload": {"prompt": "{}"}}), encoding="utf-8")
        (action / "raw_response.json").write_text(json.dumps({"done": True, "response": "{}"}), encoding="utf-8")
        (action / "result.json").write_text(json.dumps({"kind": "finish"}), encoding="utf-8")
        (action / "metrics.json").write_text(json.dumps({"output_tokens": 4}), encoding="utf-8")
        value = model_io_snapshot(self.coder, action_id)
        self.assertEqual(value["parsed_response"]["kind"], "finish")
        self.assertTrue(value["raw_response"]["done"])
        self.assertEqual(value["metrics"]["output_tokens"], 4)

    def test_invalid_action_id_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid model action id"):
            model_io_snapshot(self.coder, "../../secret")

    def test_ui_injection_and_local_model_io_endpoint(self):
        action_id = "TASK_x:coder:3"
        sidecar = self.coder.artifact_root / "_model_io" / "TASK_x_coder_3"
        sidecar.mkdir(parents=True)
        (sidecar / "request.json").write_text(json.dumps({"payload": {"prompt": "{}"}}), encoding="utf-8")

        app = Flask(__name__)

        @app.route("/")
        def index():
            return "<html><body>hello</body></html>"

        install_model_io_ui(app, self.coder, lambda: True)
        client = app.test_client()
        page = client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn('/static/model_io.js', page.get_data(as_text=True))

        response = client.get("/api/coder/model-io/" + action_id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["action_id"], action_id)


if __name__ == "__main__":
    unittest.main()

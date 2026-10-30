"""Local HTTP integration; no browser clicks or external/provider connections."""

from copy import deepcopy
import http.client
import json
from pathlib import Path
import threading

from stylemate_memory.consumer import make_server
from tests.test_consumer_service import ServiceFixture, PNG


class ConsumerHttpTests(ServiceFixture):
    def setUp(self):
        super().setUp()
        self.server = make_server(self.service, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def post(self, command):
        code, data, _ = self.request("POST", "/api/command", json.dumps(command), {"Content-Type": "application/json"})
        return code, json.loads(data)

    def test_packaged_entry_http_transport_and_no_arbitrary_file_routes(self):
        code, html, headers = self.request("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn(b'data-adapter="http"', html)
        self.assertIn(b"consumer-http.js", html)
        self.assertNotIn(b'data-adapter="fixture"', html)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        for path in ("/consumer-http.js", "/consumer.js", "/consumer.css"):
            self.assertEqual(self.request("GET", path)[0], 200)
        for path in ("/../pyproject.toml", "/api/inspect", "/api/state?user_id=alice", "/api/state?path=/etc/passwd",
                     "/api/state?request_id=a&request_id=b", "/consumer-fixture.js"):
            self.assertIn(self.request("GET", path)[0], (400, 404))

    def test_host_origin_json_size_duplicate_fields_and_nonfinite_values(self):
        self.assertEqual(self.request("GET", "/api/state", headers={"Host": "outside.invalid"})[0], 403)
        self.assertEqual(self.request("GET", "/api/state", headers={"Origin": "https://outside.invalid"})[0], 403)
        self.assertEqual(self.request("POST", "/api/command", "{}", {"Content-Type": "text/plain"})[0], 415)
        for body in ('{"a":1,"a":2}', '{"number":NaN}', '{"number":Infinity}', '[]', '{"action":{"op":[]}}', ' ' * 24001):
            with self.subTest(body=body[:50]):
                self.assertEqual(self.request("POST", "/api/command", body, {"Content-Type": "application/json"})[0], 400)

    def test_actual_commands_state_image_version_and_trusted_owner(self):
        command = {"contract_version": "lumi-memory-v1", "command_id": "http-start", "request_id": None, "expected": None,
                   "action": {"op": "start_request", "mode": "shopping", "timezone": "UTC",
                              "targets": [{"target_id": "pants", "garment_type": "Pants"}], "text": "네이비가 좋아요"}}
        code, result = self.post(command)
        self.assertEqual(code, 202, result)
        self.service.wait_idle()
        self.review("confirm_content")
        self.send({"op": "explore"})
        self.service.wait_idle()
        code, data, _ = self.request("GET", "/api/state")
        state = json.loads(data)
        self.assertEqual(code, 200)
        self.assertTrue(state["cards"], state)
        card = state["cards"][0]
        code, data, headers = self.request("GET", card["image_url"])
        self.assertEqual((code, data, headers["Content-Type"]), (200, PNG, "image/png"))
        self.assertEqual(self.request("GET", f"/api/images/{card['image_id']}?version=999")[0], 409)
        for path in ("/api/images/../memory.sqlite3?version=1", "/api/images/%2e%2e%2fmemory.sqlite3?version=1"):
            self.assertEqual(self.request("GET", path)[0], 400)
        forged = deepcopy(command)
        forged["user_id"] = "another-user"
        self.assertEqual(self.post(forged)[0], 400)
        self.assertNotIn("synthetic-user", json.dumps(state))
        # A symlink cannot turn the permitted ID route into an arbitrary file read.
        image = self.images / f"{card['product_id']}.png"
        image.unlink()
        image.symlink_to(Path(__file__).resolve())
        code, data, _ = self.request("GET", card["image_url"])
        self.assertIn(code, (400, 404))
        self.assertNotIn(b"ServiceFixture", data)

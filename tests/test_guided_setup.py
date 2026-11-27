import json
import unittest
from unittest.mock import patch

from test_relay import relay

p = relay.p


class GuidedSetupTest(unittest.TestCase):
    def setUp(self):
        self.manager = p.Manager(True)
        self.server = {"guided": True, "role": "server", "key": "local-test-key"}
        self.client = {"guided": True, "role": "client", "remote": "203.0.113.22", "port": 6589,
                       "service_port": 14105, "key": "local-test-key"}

    def test_automatic_port_and_stale_confirmation(self):
        preview = self.manager.create(self.server, preview=True)
        self.assertEqual(preview["endpoint"], ":6589")
        self.assertNotIn(self.server["key"], json.dumps(preview))
        self.assertNotIn(preview["name"], self.manager.samples)

        with patch.object(self.manager.operations, "listeners", return_value={"tcp": {6589: {"127.0.0.1"}}, "udp": {}}):
            with self.assertRaisesRegex(p.Problem, "پیش‌نمایش تغییر کرده"):
                self.manager.create({**self.server, "confirmed": preview})
            preview = self.manager.create(self.server, preview=True)
            self.assertEqual(preview["endpoint"], ":6590")
            result = self.manager.create({**self.server, "confirmed": preview})
        self.assertEqual(result["name"], preview["name"])

    def test_service_port_and_pairing_file(self):
        report = self.manager.create(self.client, preview=True)
        self.assertEqual(report["forward"], [{"listen": "0.0.0.0:14105", "target": "127.0.0.1:14105", "protocol": "tcp"}])
        with patch.object(self.manager.operations, "listeners", return_value={"tcp": {14105: {"127.0.0.1"}}, "udp": {}}):
            with self.assertRaisesRegex(p.Problem, "در حال استفاده"):
                self.manager.create(self.client, preview=True)

        report = self.manager.create(self.server, preview=True)
        name = self.manager.create({**self.server, "confirmed": report})["name"]
        operations = self.manager.operations
        profile = operations.peer_profile(name, "127.0.0.1:8765")
        self.assertNotIn("address", profile)
        self.assertEqual(profile["transport"]["kcp"]["key"], self.server["key"])
        self.assertEqual(operations.peer_profile(name, "8.8.8.8:8765")["address"], "8.8.8.8")

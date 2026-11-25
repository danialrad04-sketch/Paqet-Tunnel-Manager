"""Exercise migration between two panel managers with different local network settings."""
import json
from pathlib import Path
import socket
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web"))
import panel
import recovery


class RecoveryTest(unittest.TestCase):
    def test_migrates_network_and_preserves_peer(self):
        source = panel.Manager(True)
        destination = panel.Manager(True)
        name = "tehran-edge"
        config = source.samples[name][0]
        config["network"] = {"interface": "ens5", "ipv4": {"addr": "192.0.2.20:0", "router_mac": "02:00:00:00:00:02"},
                             "tcp": {"local_flag": ["PA", "A"]}}
        config["forward"][0]["listen"] = "192.0.2.20:8443"
        config["transport"]["kcp"]["mtu"] = 1250
        password = "unique five words in test"
        bundle = recovery.recover(source, {"action": "export", "name": name, "password": password})
        self.assertNotIn("example-demo-key", json.dumps(bundle))
        self.assertNotIn("203.0.113.14", json.dumps(bundle))
        request = {"name": "tehran-new", "bundle": bundle, "password": password}
        with self.assertRaises(panel.Problem):
            recovery.recover(destination, {**request, "password": "invalid password value", "action": "preview"})
        damaged = {**bundle, "data": ("A" if bundle["data"][0] != "A" else "B") + bundle["data"][1:]}
        with self.assertRaises(panel.Problem):
            recovery.recover(destination, {**request, "bundle": damaged, "action": "preview"})
        with self.assertRaises(panel.Problem):
            recovery.recover(destination, {**request, "name": name, "action": "preview"})
        preview = recovery.recover(destination, {**request, "action": "preview"})
        self.assertEqual(preview["remote"], "203.0.113.14:443")
        self.assertEqual(preview["listeners"][0]["listen"], "192.0.2.10:8443")
        self.assertNotIn(request["name"], destination.samples)
        with self.assertRaises(panel.Problem):
            recovery.recover(destination, {**request, "action": "restore", "preview": "stale"})
        recovery.recover(destination, {**request, "action": "restore", "preview": preview["preview"]})
        restored = destination.samples[request["name"]][0]
        self.assertEqual(restored["network"]["interface"], "eth0")
        self.assertEqual(restored["network"]["tcp"], config["network"]["tcp"])
        self.assertEqual(restored["network"]["ipv4"]["addr"], "192.0.2.10:0")
        self.assertEqual(restored["network"]["ipv4"]["router_mac"], "02:00:00:00:00:01")
        self.assertEqual(restored["transport"], config["transport"])
        self.assertEqual(restored["socks5"], config["socks5"])
        self.assertEqual(restored["forward"][0]["target"], config["forward"][0]["target"])

    def test_occupied_port_is_rejected(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            with self.assertRaises(panel.Problem):
                recovery.check_listeners([{"host": "127.0.0.1", "port": port, "protocol": "tcp",
                                           "listen": f"127.0.0.1:{port}"}])

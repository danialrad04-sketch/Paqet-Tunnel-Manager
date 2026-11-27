"""Verify switching thresholds and the policy hold without network timing."""
from collections import defaultdict
import unittest
from unittest.mock import patch

from test_relay import relay


class AdaptiveRouteTest(unittest.IsolatedAsyncioTestCase):
    async def test_sustained_latency_hold_and_emergency_failover(self):
        config = {"name": "entry", "role": "entry", "selected": "paqet", "policy": "adaptive",
                  "primary": ["127.0.0.1", 11111], "peer": {"domain": "relay.example.org"}}
        service = object.__new__(relay.Relay)
        service.demo = False
        service.configs = {"entry": config}
        service.history = defaultdict(list)
        service.runtime = {}
        service.last_switch = {}
        service.persist_switch = lambda: None
        samples = {"paqet": {"ok": True, "ms": 175}, "https": {"ok": True, "ms": 90}}

        async def probe(_, route):
            return samples[route].copy()

        service.probe = probe
        clock = 1000

        async def cycle(count):
            nonlocal clock
            for _ in range(count):
                with patch.object(relay.time, "time", return_value=clock):
                    await service.monitor(config)
                clock += 20

        await cycle(6)
        self.assertEqual(service.active_route(config), "paqet")
        await cycle(1)
        self.assertEqual(service.active_route(config), "https")
        self.assertEqual(service.last_switch["entry"]["reason"], "quality")
        self.assertEqual(service.runtime["entry"]["quality"]["https"]["median_ms"], 90)

        samples["paqet"]["ms"] = 25
        await cycle(3)
        self.assertEqual(service.active_route(config), "https")
        samples["https"] = {"ok": False}
        await cycle(2)
        self.assertEqual(service.active_route(config), "paqet")
        self.assertEqual(service.last_switch["entry"]["reason"], "failure")

    def test_minor_improvement_does_not_trigger_switch(self):
        tests = {"paqet": {"ok": True, "streak": 5}, "quic": {"ok": True, "streak": 5}}
        quality = {"paqet": {"samples": 5, "successes": 5, "median_ms": 95},
                   "quic": {"samples": 5, "successes": 5, "median_ms": 72}}
        self.assertIsNone(relay.adaptive_candidate(quality, tests, "paqet"))

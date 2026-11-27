"""Exercise deferred receiver creation and in-place certificate renewal."""
import asyncio
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from test_relay import free_port, relay
import acme
import panel


def generate_certificate(base, name, domain):
    cert, key = base / (name + ".pem"), base / (name + ".key")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
                    "-subj", "/CN=" + domain, "-addext", "subjectAltName=DNS:" + domain,
                    "-keyout", str(key), "-out", str(cert)],
                   check=True, capture_output=True)
    return cert, key


class AcmeCommandTest(unittest.IsolatedAsyncioTestCase):
    async def test_uses_certbot_standalone_with_exact_validated_domain(self):
        process = AsyncMock()
        process.returncode = 0
        process.communicate.return_value = (b"", b"")
        ready = {"status": "ready", "managed": True}
        with patch.object(acme, "inspect", side_effect=[{"status": "missing"}, ready]):
            with patch.object(asyncio, "create_subprocess_exec", new=AsyncMock(return_value=process)) as start:
                self.assertEqual(await acme.issue("relay.example.org"), ready)
        command = start.await_args.args
        self.assertEqual(command[:3], (acme.CERTBOT, "certonly", "--standalone"))
        self.assertEqual(command[-4:], ("--cert-name", "relay.example.org", "--domains", "relay.example.org"))
        self.assertIn("http-01", command)

    def test_classifies_bind_and_dns_failures(self):
        self.assertIn("TCP 80", acme.error_message("Could not bind TCP port 80"))
        self.assertIn("DNS", acme.error_message("DNS problem: NXDOMAIN looking up A"))


@unittest.skipUnless(shutil.which("openssl"), "openssl is required")
class AcmeRelayTest(unittest.TestCase):
    def test_activates_after_issuance_and_reloads_renewal(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            domain = "relay.example.org"
            first = generate_certificate(base, "first", domain)
            renewed = generate_certificate(base, "renewed", domain)
            with patch.object(acme, "ROOT", base):
                chain, key = acme.paths(domain)
                chain.parent.mkdir(parents=True)
                renewal = base / "renewal" / f"{domain}.conf"
                renewal.parent.mkdir()
                service = relay.Relay(base, False, 8765)

                async def scenario():
                    ready = asyncio.Event()
                    port = free_port()
                    options = {"name": "receiver", "role": "receiver", "transport": "https",
                               "domain": domain, "listen": f"127.0.0.1:{port}", "target": "127.0.0.1:14105"}

                    async def issue(requested):
                        self.assertEqual(requested, domain)
                        await ready.wait()
                        shutil.copy(first[0], chain)
                        shutil.copy(first[1], key)
                        renewal.touch()

                    async def settle():
                        while (await service.view())["certificate_job"]["status"] == "running":
                            await asyncio.sleep(.01)
                        return await service.view()

                    async def presented_certificate():
                        context = ssl.create_default_context(cafile=str(first[0]))
                        context.load_verify_locations(cafile=str(renewed[0]))
                        _, stream = await asyncio.open_connection("127.0.0.1", port, ssl=context, server_hostname=domain)
                        try:
                            return stream.get_extra_info("ssl_object").getpeercert(binary_form=True)
                        finally:
                            await relay.close(stream)

                    with patch.object(acme, "issue", side_effect=issue) as issuer:
                        with self.assertRaises(panel.Problem):
                            await service.save_with_certificate({**options, "domain": "../invalid"})
                        self.assertEqual(await service.save_with_certificate(options), {"certificate_pending": True})
                        pending = await service.view()
                        self.assertEqual(pending["rows"], [])
                        self.assertEqual(pending["certificate_job"]["status"], "running")
                        ready.set()
                        finished = await asyncio.wait_for(settle(), 3)
                        self.assertEqual(finished["certificate_job"]["status"], "done")
                        self.assertTrue(finished["rows"][0]["online"])
                        self.assertTrue(finished["rows"][0]["certificate"]["managed"])
                        self.assertEqual(await presented_certificate(), ssl.PEM_cert_to_DER_cert(first[0].read_text()))
                        old_listener = service.servers["receiver"]
                        shutil.copy(renewed[0], chain)
                        shutil.copy(renewed[1], key)
                        service.reload_certificates()
                        self.assertEqual(await presented_certificate(), ssl.PEM_cert_to_DER_cert(renewed[0].read_text()))
                        self.assertIs(service.servers["receiver"], old_listener)
                        self.assertEqual(await service.save_with_certificate(options), {})
                        self.assertEqual(issuer.await_count, 1)
                        await service.stop("receiver")

                try:
                    asyncio.run_coroutine_threadsafe(scenario(), service.loop).result(10)
                finally:
                    async def shutdown():
                        tasks = asyncio.all_tasks() - {asyncio.current_task()}
                        for task in tasks:
                            task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)

                    asyncio.run_coroutine_threadsafe(shutdown(), service.loop).result(5)
                    service.loop.call_soon_threadsafe(service.loop.stop)
                    service.thread.join(5)
                    service.loop.close()

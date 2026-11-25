"""Exercise the data plane with real sockets and authenticated, nested TLS."""
import asyncio
from pathlib import Path
import queue
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web"))
import relay


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@unittest.skipUnless(shutil.which("openssl"), "openssl is required")
class RelayTest(unittest.TestCase):
    def test_tls_transport_cutover_comparison_and_failover(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            certificate, key = directory / "cert.pem", directory / "key.pem"
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                            "-keyout", str(key), "-out", str(certificate), "-days", "1",
                            "-subj", "/CN=localhost.test",
                            "-addext", "subjectAltName=DNS:localhost.test,DNS:localhost"],
                           check=True, capture_output=True)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certificate, key)
            service = relay.Relay(directory, False, 8765)
            service.baseline = ssl.create_default_context(cafile=str(certificate))
            service.reload_context = lambda _: context

            async def scenario():
                resolve = service.loop.getaddrinfo

                async def getaddrinfo(host, *args, **kwargs):
                    if host == "localhost.test":
                        host = "127.0.0.1"
                    return await resolve(host, *args, **kwargs)

                service.loop.getaddrinfo = getaddrinfo
                entry_port, receiver_port = free_port(), free_port()
                while entry_port == receiver_port:
                    receiver_port = free_port()

                async def responder(reader, writer):
                    try:
                        request = await reader.readline()
                        while (await reader.readline()) not in (b"\r\n", b""):
                            pass
                        payload = b"x" * (131072 if request.startswith(b"GET") else 0)
                        writer.write(b"HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: " +
                                     str(len(payload)).encode() + b"\r\n\r\n" + payload)
                        await writer.drain()
                    finally:
                        await relay.close(writer)

                backend = await asyncio.start_server(responder, "127.0.0.1", 0, ssl=context)
                backend_port = backend.sockets[0].getsockname()[1]
                await service.change("save", {"name": "outside", "role": "receiver",
                                     "listen": f"127.0.0.1:{receiver_port}", "domain": "localhost.test",
                                     "target": f"127.0.0.1:{backend_port}"})
                peer = await service.peer("outside")
                await service.change("save", {"name": "entry", "role": "entry",
                                     "listen": f"127.0.0.1:{entry_port}",
                                     "primary": f"127.0.0.1:{backend_port}", "peer": peer,
                                     "selected": "paqet", "probe": "https", "probe_host": "localhost.test",
                                     "probe_path": "/", "automatic": True})
                config = service.configs["entry"]
                wrong = {**config, "peer": {**config["peer"], "key": "A" * 43}}
                self.assertFalse((await service.probe(wrong, "https"))["ok"])
                self.assertTrue((await service.probe(config, "https"))["ok"])
                await service.start_comparison("entry")
                for _ in range(100):
                    if service.comparisons["entry"]["status"] != "running":
                        break
                    await asyncio.sleep(.05)
                self.assertEqual(service.comparisons["entry"]["status"], "done")
                comparison = service.comparisons["entry"]["results"]
                self.assertEqual(comparison["https"]["ok"], 3)
                self.assertEqual(comparison["https"]["load_bytes"], 131072)

                async def connect_entry():
                    return await asyncio.open_connection("127.0.0.1", entry_port, ssl=service.baseline,
                                                         server_hostname="localhost.test")

                async def check(stream):
                    reader, writer = stream
                    writer.write(b"HEAD / HTTP/1.1\r\nHost: localhost.test\r\n\r\n")
                    await writer.drain()
                    self.assertTrue((await relay.read_header(reader)).startswith(b"HTTP/1.1 200"))
                    await relay.close(writer)

                existing = await connect_entry()
                socket_before = service.servers["entry"]
                await service.select("entry", "https")
                self.assertIs(service.servers["entry"], socket_before)
                await check(existing)
                await check(await connect_entry())
                self.assertGreater(service.totals["entry"][relay.month()], 0)
                await service.select("entry", "paqet")
                config = service.configs["entry"]
                config["primary"] = ["127.0.0.1", free_port()]
                await service.monitor(config)
                self.assertEqual(service.active_route(config), "paqet")
                await service.monitor(config)
                self.assertEqual(service.active_route(config), "https")
                self.assertEqual(service.read("switches.json", {})["entry"]["selected"], "https")
                await check(await connect_entry())
                await service.stop("entry")
                await service.stop("outside")
                backend.close()
                await backend.wait_closed()

            try:
                asyncio.run_coroutine_threadsafe(scenario(), service.loop).result(20)
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


if __name__ == "__main__":
    unittest.main()

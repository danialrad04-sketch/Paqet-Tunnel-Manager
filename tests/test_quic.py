"""Verify standard UDP/QUIC against the panel's managed TCP ingress."""
import asyncio
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest

from test_relay import free_port, relay


@unittest.skipUnless(relay.quic_transport and shutil.which("openssl"), "aioquic and openssl are required")
class QuicTest(unittest.TestCase):
    def test_verified_quic_multiplexes_tcp_flows(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            certificate, key = directory / "cert.pem", directory / "key.pem"
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                            "-keyout", str(key), "-out", str(certificate), "-days", "1",
                            "-subj", "/CN=localhost.test", "-addext", "subjectAltName=DNS:localhost.test"],
                           check=True, capture_output=True)
            service = relay.Relay(directory, False, 8765)
            service.certificates = lambda _: (str(certificate), str(key))
            service.quic.cafile = str(certificate)

            async def scenario():
                resolve = service.loop.getaddrinfo

                async def getaddrinfo(host, *args, **kwargs):
                    return await resolve("127.0.0.1" if host == "localhost.test" else host, *args, **kwargs)

                service.loop.getaddrinfo = getaddrinfo
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.bind(("127.0.0.1", 0))
                    receiver_port = sock.getsockname()[1]
                entry_port = free_port()

                async def echo(reader, writer):
                    try:
                        while chunk := await reader.read(65536):
                            writer.write(chunk)
                            await writer.drain()
                    finally:
                        await relay.close(writer)

                backend = await asyncio.start_server(echo, "127.0.0.1", 0)
                async with backend:
                    backend_port = backend.sockets[0].getsockname()[1]
                    await service.change("save", {"name": "outside", "role": "receiver", "transport": "quic",
                                         "listen": f"127.0.0.1:{receiver_port}", "domain": "localhost.test",
                                         "target": f"127.0.0.1:{backend_port}"})
                    peer = await service.peer("outside")
                    self.assertEqual(peer["format"], "paqet-quic-v1")
                    await service.change("save", {"name": "entry", "role": "entry",
                                         "listen": f"127.0.0.1:{entry_port}", "quic_peer": peer,
                                         "selected": "quic", "probe": "tcp"})
                    with self.assertRaises(ConnectionError):
                        await service.quic.open({**peer, "key": "X" * 43})
                    self.assertNotIn(peer["key"], str(await service.view()))
                    with self.assertRaises(ConnectionError):
                        await relay.quic_transport.Pool().open(peer)

                    async def exchange(value):
                        stream, writer = await asyncio.open_connection("127.0.0.1", entry_port)
                        try:
                            async def send():
                                for offset in range(0, len(value), 65536):
                                    writer.write(value[offset:offset + 65536])
                                    await writer.drain()
                                writer.write_eof()

                            _, echoed = await asyncio.wait_for(asyncio.gather(send(), stream.read()), 8)
                            self.assertEqual(echoed, value)
                        finally:
                            await relay.close(writer)

                    await asyncio.gather(exchange(b"A" * 3_000_000), exchange(b"B" * 3000),
                                         exchange(b"C" * 75000))
                    self.assertEqual(len(service.quic.sessions), 1)
                    self.assertTrue((await service.probe(service.configs["entry"], "quic"))["ok"])
                    await service.stop("entry")
                    await service.stop("outside")

            try:
                asyncio.run_coroutine_threadsafe(scenario(), service.loop).result(15)
            finally:
                async def shutdown():
                    for server in service.servers.values():
                        server.close()
                    tasks = asyncio.all_tasks() - {asyncio.current_task()}
                    for task in tasks:
                        if task.get_coro().__name__ != "retire":
                            task.cancel()
                    # The QUIC client contexts need their close timers to finish.
                    await asyncio.gather(*tasks, return_exceptions=True)

                try:
                    asyncio.run_coroutine_threadsafe(shutdown(), service.loop).result(5)
                finally:
                    service.loop.call_soon_threadsafe(service.loop.stop)
                    service.thread.join(5)
                    service.loop.close()

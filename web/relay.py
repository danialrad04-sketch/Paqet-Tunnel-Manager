"""Managed TCP forwards with fixed-destination HTTPS and QUIC transports."""
import asyncio
from collections import defaultdict
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime, timezone
import hmac
import ipaddress
import json
import logging
import math
import re
import secrets
import ssl
from statistics import median
import threading
import time

import acme
import panel as p

try:
    import quic_transport
except ImportError:
    quic_transport = None


QUALITY_WINDOW = 5
QUALITY_CONFIRMATIONS = 3
QUALITY_HOLD = 120


def route_policy(config):
    return config.get("policy") or ("failover" if config.get("automatic") is True else "manual")


def route_quality(history, routes):
    summary = {}
    for route in routes:
        samples = [point["tests"][route] for point in history[-QUALITY_WINDOW:] if route in point["tests"]]
        latencies = [point["ms"] for point in samples if point["ok"]]
        summary[route] = {"samples": len(samples), "successes": len(latencies),
                          "median_ms": round(median(latencies)) if latencies else None}
    return summary


def adaptive_candidate(quality, tests, selected):
    current = quality[selected]
    if current["samples"] < QUALITY_WINDOW or current["median_ms"] is None:
        return None
    candidates = []
    for route, result in quality.items():
        if (route == selected or result["samples"] < QUALITY_WINDOW or result["successes"] < 4
                or not tests[route]["ok"] or tests[route]["streak"] < 3):
            continue
        faster = result["median_ms"] <= min(current["median_ms"] - 40, current["median_ms"] * .75)
        more_reliable = result["successes"] - current["successes"] >= 2
        if more_reliable or faster and result["successes"] >= current["successes"]:
            candidates.append(route)
    return min(candidates, key=lambda route: (-quality[route]["successes"], quality[route]["median_ms"]), default=None)


def month():
    return datetime.now(timezone.utc).strftime("%Y-%m")


def local_peer(address):
    host, port = p.endpoint(address, True)
    if not host or not ipaddress.ip_address(host).is_loopback:
        raise p.Problem("این مقصد باید یک آدرس loopback مانند 127.0.0.1:14105 باشد.")
    return host, port


def hostname(value):
    if not isinstance(value, str) or len(value) > 253 or not re.fullmatch(
        r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", value
    ):
        raise p.Problem("نام دامنهٔ معتبر لازم است.")
    return value.lower()


def secret(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{43}", value):
        raise p.Problem("کلید اتصال معتبر نیست.")
    return value


def peer_profile(value, protocol):
    fmt = f"paqet-{protocol}-v1"
    if not isinstance(value, dict) or value.get("format") != fmt:
        raise p.Problem(f"فایل اتصال {protocol.upper()} معتبر نیست.")
    return {"format": fmt, "domain": hostname(value.get("domain")),
            "port": p.number(value.get("port"), 1, 65535, "پورت گیرنده"), "key": secret(value.get("key"))}


def listener_transport(config):
    return config.get("transport", "https") if config.get("role") == "receiver" else "tcp"


async def read_header(reader):
    try:
        return await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 4)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError) as error:
        raise OSError("Invalid HTTP response") from error


async def close(writer):
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(), 2)
    except (OSError, asyncio.TimeoutError):
        writer.transport.abort()


async def copy(source, dest, count):
    while chunk := await source.read(65536):
        dest.write(chunk)
        await dest.drain()
        count(len(chunk))
    if dest.can_write_eof():
        dest.write_eof()


async def bridge(left, right, count):
    tasks = [asyncio.create_task(copy(left[0], right[1], count)),
             asyncio.create_task(copy(right[0], left[1], count))]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        # TLS has no write-half close. Allow the other direction to drain.
        if pending:
            await asyncio.wait_for(asyncio.gather(*pending), 30)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class ProbeTLS:
    """TLS over an existing stream, including over TLS on Python 3.10."""
    def __init__(self, context, host, reader, writer):
        self.incoming, self.outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
        self.session = context.wrap_bio(self.incoming, self.outgoing, server_hostname=host)
        self.reader, self.writer = reader, writer

    async def perform(self, operation, *args):
        while True:
            try:
                return operation(*args)
            except ssl.SSLWantReadError:
                await self.flush()
                chunk = await self.reader.read(16384)
                if not chunk:
                    self.incoming.write_eof()
                else:
                    self.incoming.write(chunk)
            finally:
                await self.flush()

    async def flush(self):
        if self.outgoing.pending:
            self.writer.write(self.outgoing.read())
            await self.writer.drain()

    async def read(self, size):
        try:
            return await self.perform(self.session.read, size)
        except (ssl.SSLZeroReturnError, ssl.SSLEOFError):
            return b""

    async def write(self, data):
        await self.perform(self.session.write, data)


async def read_probe_header(read):
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = await read(4096)
        if not chunk or len(data) + len(chunk) > 16384:
            raise OSError("Invalid application response")
        data += chunk
    return data.split(b"\r\n\r\n", 1)


class Relay:
    def __init__(self, directory, demo, panel_port):
        self.directory = directory
        self.demo = demo
        self.panel_port = panel_port
        self.configs = self.read("relays.json", {})
        self.totals = self.read("traffic.json", {})
        self.last_switch = self.read("switches.json", {})
        self.dirty = False
        self.servers = {}
        self.runtime = {}
        self.contexts = {}
        self.quic_contexts = {}
        self.certificate_job = None
        self.quic = quic_transport.Pool(ssl.get_default_verify_paths().cafile) if quic_transport else None
        self.history = defaultdict(list)
        self.connections = defaultdict(int)
        self.monitored = set()
        self.comparisons = {}
        self.configuration_lock = asyncio.Lock()
        self.baseline = ssl.create_default_context()
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, name="relay", daemon=True)
        self.thread.start()
        asyncio.run_coroutine_threadsafe(self.worker(), self.loop)

    def read(self, filename, default):
        if self.demo:
            return default
        try:
            return json.loads((self.directory / filename).read_text())
        except FileNotFoundError:
            return default

    def save(self, filename, data):
        if not self.demo:
            self.directory.mkdir(mode=0o700, exist_ok=True)
            p.atomic(self.directory / filename, json.dumps(data), 0o600)

    def reload_context(self, config):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.set_alpn_protocols(["http/1.1"])
        try:
            context.load_cert_chain(*self.certificates(config))
        except (ValueError, OSError) as error:
            raise p.Problem("گواهی یا کلید TLS در مسیر Let's Encrypt معتبر و خواندنی نیست.") from error
        return context

    def parse(self, data):
        name = data.get("name")
        if not isinstance(name, str) or not re.fullmatch(p.NAME, name):
            raise p.Problem("نام مسیر معتبر نیست.")
        role = data.get("role")
        old = self.configs.get(name, {})
        if type(role) is not str or role not in ("receiver", "entry"):
            raise p.Problem("نقش مسیر معتبر نیست.")
        if old and old["role"] != role:
            raise p.Problem("برای تغییر نقش، مسیر دیگری بسازید.")
        transport = data.get("transport") or old.get("transport", "https")
        default_bind = "127.0.0.1:24105"
        if role == "receiver":
            default_bind = "0.0.0.0:24443" if transport == "quic" else "0.0.0.0:8443"
        bind, port = p.endpoint(data.get("listen") or default_bind, True)
        if port == self.panel_port or port < 1024 or not bind or ":" in bind:
            # Server role can use 443 when available.
            if not (role == "receiver" and port == 443 and port != self.panel_port and bind and ":" not in bind):
                raise p.Problem("آدرس شنود IPv4 صریح و پورت آزاد ۱۰۲۴ به بالا لازم است.")
        config = {"name": name, "role": role, "listen": f"{bind}:{port}"}
        if role == "receiver":
            transport = data.get("transport") or listener_transport(old or config)
            if transport not in ("https", "quic"):
                raise p.Problem("پروتکل گیرنده معتبر نیست.")
            if old and transport != listener_transport(old):
                raise p.Problem("برای تغییر پروتکل، گیرندهٔ جدید بسازید.")
            self.require_quic(transport == "quic")
            config["transport"] = transport
            target = data.get("target")
            if isinstance(target, str) and re.fullmatch(r"[0-9]{1,5}", target):
                target = "127.0.0.1:" + target
            target = list(local_peer(target))
            if transport == "https" and target[1] == port and bind in ("0.0.0.0", target[0]):
                raise p.Problem("شنونده و مقصد گیرنده روی یک سوکت قرار دارند.")
            if target[1] == self.panel_port:
                raise p.Problem("پورت پنل برای مقصد مسیر مجاز نیست.")
            config.update(domain=hostname(data.get("domain")), target=target,
                          key=old.get("key") or secrets.token_urlsafe(32))
        elif role == "entry":
            primary = data.get("primary") or ""
            alternate, quic = (peer_profile(data[key], protocol) if data.get(key) is not None else
                               old.get(key) if data.get(f"keep_{key}") is True else None
                               for key, protocol in (("peer", "https"), ("quic_peer", "quic")))
            self.require_quic(bool(quic))
            if primary:
                primary = list(local_peer(primary))
            backup = data.get("backup") or ""
            if backup:
                backup = list(local_peer(backup))
                if not primary or backup == primary:
                    raise p.Problem("ورودی Paqet جایگزین باید با ورودی اصلی متفاوت باشد.")
            selected = data.get("selected")
            if not isinstance(selected, str) or not {"paqet": primary, "https": alternate, "quic": quic, "standby": backup}.get(selected):
                raise p.Problem("مسیر انتخابی تنظیم نشده است.")
            probe = data.get("probe", "tls")
            if probe not in ("tcp", "tls", "http", "https"):
                raise p.Problem("روش آزمون معتبر نیست.")
            probe_host = ""
            path = "/"
            if probe in ("http", "https"):
                probe_host = hostname(data.get("probe_host"))
                path = data.get("probe_path") or "/"
                if not isinstance(path, str) or not re.fullmatch(r"/[!-~]{0,1023}", path):
                    raise p.Problem("مسیر HTTP باید با / آغاز شود و فاصله نداشته باشد.")
            policy = route_policy(data)
            if policy not in ("manual", "failover", "adaptive"):
                raise p.Problem("سیاست انتخاب مسیر معتبر نیست.")
            if policy != "manual" and probe == "tcp":
                raise p.Problem("جابه‌جایی خودکار به آزمون لایهٔ برنامه نیاز دارد.")
            if policy == "adaptive" and sum(bool(route) for route in (primary, alternate, quic, backup)) < 2:
                raise p.Problem("انتخاب هوشمند به دست‌کم دو مسیر تنظیم‌شده نیاز دارد.")
            config.update(primary=primary, peer=alternate, quic_peer=quic, backup=backup, selected=selected, probe=probe,
                          probe_host=probe_host, probe_path=path, policy=policy, automatic=policy != "manual",
                          budget=p.number(data.get("budget") or 0, 0, 999999, "سقف GiB"))
            for upstream in (primary, backup):
                if upstream and upstream[1] == self.panel_port:
                    raise p.Problem("پورت پنل برای مقصد مسیر مجاز نیست.")
                if upstream and upstream[1] == port and bind in ("0.0.0.0", upstream[0]):
                    raise p.Problem("ورودی و مقصد Paqet روی یک سوکت قرار دارند.")
        else:
            raise p.Problem("نقش مسیر معتبر نیست.")
        is_udp = listener_transport(config) == "quic"
        for other in self.configs.values():
            other_is_udp = listener_transport(other) == "quic"
            if other["name"] == name or other_is_udp != is_udp:
                continue
            other_bind, other_port = p.endpoint(other["listen"], True)
            if port == other_port and (bind == other_bind or "0.0.0.0" in (bind, other_bind)):
                raise p.Problem("پورت ورودی با مسیر دیگری تداخل دارد.")
        return config

    def require_quic(self, required=True):
        if required and not self.quic and not self.demo:
            raise p.Problem("ماژول QUIC در دسترس نیست. نصب‌کننده را با --with-quic اجرا کنید.")

    @staticmethod
    def certificates(config):
        return acme.paths(config["domain"])

    async def listen(self, config):
        name = config["name"]
        if self.demo:
            return
        host, port = p.endpoint(config["listen"], True)
        options = {}
        if listener_transport(config) == "quic":
            self.require_quic()
            try:
                server, context = await quic_transport.listen(
                    host, port, lambda reader, writer: self.accept(name, reader, writer),
                    *self.certificates(config))
            except (OSError, ValueError) as error:
                raise p.Problem("پورت UDP یا گواهی QUIC در دسترس نیست.") from error
            self.servers[name], self.quic_contexts[name] = server, context
            return
        if config["role"] == "receiver":
            # The context is updated for future handshakes when the cert renews.
            context = self.reload_context(config)
            self.contexts[name] = context
            options = {"ssl": context, "ssl_handshake_timeout": 6}
        self.servers[name] = await asyncio.start_server(
            lambda reader, writer: self.accept(name, reader, writer), host, port, limit=8192, **options)

    async def stop(self, name):
        server = self.servers.pop(name, None)
        self.contexts.pop(name, None)
        self.quic_contexts.pop(name, None)
        if server:
            # Closing a listener leaves accepted connections with their original route.
            server.close()

    async def change(self, action, data):
        async with self.configuration_lock:
            return await self.change_locked(action, data)

    def named_relay(self, data):
        if data.get("name") == "" and data.get("role") in ("entry", "receiver"):
            prefix = "relay-" + data["role"]
            for i in range(1, 1001):
                name = f"{prefix}-{i:02d}"
                if name not in self.configs:
                    return {**data, "name": name}
            raise p.Problem("برای مسیر نام دیگری وارد کنید.")
        return data

    async def save_with_certificate(self, data):
        async with self.configuration_lock:
            if data.get("role") != "receiver":
                raise p.Problem("صدور گواهی برای گیرندهٔ HTTPS یا QUIC است.")
            data = self.named_relay(data)
            config = self.parse(data)
            name, domain = config["name"], config["domain"]
            original = self.configs.get(name)
            if original is None and len(self.configs) >= 40:
                raise p.Problem("حداکثر ۴۰ مسیر قابل ثبت است.")
            if self.demo or acme.inspect(domain)["status"] == "ready":
                return await self.change_locked("save", data)
            if self.certificate_job and self.certificate_job["status"] == "running":
                raise p.Problem("صدور گواهی دیگری در حال اجراست.")
            job = {"status": "running", "name": name, "domain": domain}
            self.certificate_job = job
            asyncio.create_task(self.finish_certificate(job, data, original))
            return {"certificate_pending": True}

    async def finish_certificate(self, job, data, original):
        try:
            await acme.issue(job["domain"])
        except p.Problem as error:
            job.update(status="error", error=str(error))
            return
        except OSError:
            logging.exception("Could not issue certificate for %s", job["domain"])
            job.update(status="error", error="اجرای Certbot روی میزبان ناموفق بود.")
            return
        try:
            async with self.configuration_lock:
                if self.configs.get(job["name"]) is not original:
                    raise p.Problem("مسیر هنگام صدور تغییر کرد. فرم را با تنظیمات تازه ذخیره کنید.")
                await self.change_locked("save", data)
        except p.Problem as error:
            job.update(status="error", error="گواهی آماده شد. راه‌اندازی گیرنده نیاز به بررسی دارد. " + str(error))
        except OSError:
            logging.exception("Could not activate receiver %s", job["name"])
            job.update(status="error", error="گواهی آماده شد. راه‌اندازی گیرنده روی میزبان ناموفق بود.")
        else:
            job["status"] = "done"

    async def change_locked(self, action, data):
        if action == "save":
            data = self.named_relay(data)
        name = data.get("name")
        if not isinstance(name, str):
            raise p.Problem("نام مسیر معتبر نیست.")
        old = self.configs.get(name)
        if action == "remove":
            if not old:
                raise p.Problem("مسیر پیدا نشد.")
            updated = {key: value for key, value in self.configs.items() if key != name}
            self.save("relays.json", updated)
            self.configs = updated
            await self.stop(name)
            self.runtime.pop(name, None)
            if self.last_switch.pop(name, None):
                self.persist_switch()
            self.history.pop(name, None)
            self.comparisons.pop(name, None)
            return {}
        new = self.parse(data)
        if not old and len(self.configs) >= 40:
            raise p.Problem("حداکثر ۴۰ مسیر قابل ثبت است.")
        restart = not old or (old["listen"], old.get("domain")) != (new["listen"], new.get("domain"))
        restart = restart or (not self.demo and name not in self.servers)
        try:
            if restart:
                await self.stop(name)
                await self.listen(new)
            updated = {**self.configs, name: new}
            self.save("relays.json", updated)
        except (OSError, p.Problem) as error:
            if restart:
                await self.stop(name)
                if old:
                    try:
                        await self.listen(old)
                    except (OSError, p.Problem):
                        logging.exception("Could not reopen relay %s", name)
            raise p.Problem(str(error) if isinstance(error, p.Problem) else "سوکت مسیر یا فایل تنظیمات در دسترس نیست.") from error
        self.configs = updated
        self.runtime.pop(name, None)
        if not old or any(old.get(key) != new.get(key) for key in
                          ("peer", "quic_peer", "primary", "backup", "probe", "probe_host", "probe_path", "selected", "policy", "automatic")):
            if self.last_switch.pop(name, None):
                self.persist_switch()
            self.history.pop(name, None)
            self.comparisons.pop(name, None)
        return {}

    @staticmethod
    def routes(config):
        fields = (("paqet", "primary"), ("https", "peer"), ("quic", "quic_peer"), ("standby", "backup"))
        return [name for name, field in fields if config.get(field)]

    async def outbound(self, config, route):
        if route == "quic":
            if not self.quic:
                raise ConnectionError("QUIC unavailable")
            return await self.quic.open(config["quic_peer"])
        if route != "https":
            upstream = config["primary" if route == "paqet" else "backup"]
            return await asyncio.wait_for(asyncio.open_connection(*upstream, limit=8192), 4)
        peer = config["peer"]
        domain = peer["domain"]
        stream = await asyncio.wait_for(asyncio.open_connection(domain, peer["port"], ssl=self.baseline,
                                                                limit=8192), 5)
        try:
            authority = f'{domain}:{peer["port"]}'
            stream[1].write((f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n"
                             f'Proxy-Authorization: Bearer {peer["key"]}\r\n\r\n').encode("ascii"))
            await asyncio.wait_for(stream[1].drain(), 4)
            response = await read_header(stream[0])
            if not response.startswith(b"HTTP/1.1 200 "):
                raise OSError("HTTPS relay rejected connection")
        except (Exception, asyncio.CancelledError):
            await close(stream[1])
            raise
        return stream

    async def receive_quic(self, config, stream):
        reader, writer = stream
        if not await quic_transport.authenticate(reader, config["key"]):
            writer.write(b"\x01")
            return None
        try:
            target = await asyncio.wait_for(asyncio.open_connection(*config["target"], limit=8192), 4)
        except (OSError, asyncio.TimeoutError):
            writer.write(b"\x02")
            return None
        try:
            writer.write(b"\x00")
        except OSError:
            await close(target[1])
            raise
        return target

    async def receive(self, config, stream):
        if listener_transport(config) == "quic":
            return await self.receive_quic(config, stream)
        lines = (await read_header(stream[0])).split(b"\r\n")
        _, port = p.endpoint(config["listen"], True)
        authority = f'{config["domain"]}:{port}'
        supplied = [line.partition(b":")[2].strip() for line in lines[1:] if
                    line.partition(b":")[0].lower() == b"proxy-authorization"]
        if (lines[0] != f"CONNECT {authority} HTTP/1.1".encode("ascii") or len(supplied) != 1
                or not hmac.compare_digest(supplied[0], ("Bearer " + config["key"]).encode("ascii"))):
            stream[1].write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            await asyncio.wait_for(stream[1].drain(), 2)
            return None
        try:
            target = await asyncio.wait_for(asyncio.open_connection(*config["target"], limit=8192), 4)
        except (OSError, asyncio.TimeoutError):
            stream[1].write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            await asyncio.wait_for(stream[1].drain(), 2)
            return None
        stream[1].write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        return target

    async def accept(self, name, reader, writer):
        config = self.configs.get(name)
        if self.connections[name] >= 256 or not config:
            await close(writer)
            return
        self.connections[name] += 1
        remote = None
        try:
            if config["role"] == "receiver":
                remote = await self.receive(config, (reader, writer))
            else:
                route = self.active_route(config)
                remote = await self.outbound(config, route)
            if remote:
                await bridge((reader, writer), remote, lambda size: self.count(name, size))
        except (OSError, asyncio.TimeoutError, ValueError):
            pass
        finally:
            self.connections[name] -= 1
            await close(writer)
            if remote:
                await close(remote[1])

    def count(self, name, size):
        key = month()
        months = self.totals.setdefault(name, {})
        months[key] = months.get(key, 0) + size
        self.dirty = True

    async def probe(self, config, route, *, load=False, ready=None):
        start = time.monotonic()
        remote = None
        try:
            remote = await self.outbound(config, route)
            reader, writer = remote
            kind = config["probe"]
            read = reader.read
            tls = None
            if kind in ("tls", "https"):
                context, host = self.baseline, config["probe_host"]
                if kind == "tls":
                    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE
                    host = None
                tls = ProbeTLS(context, host, reader, writer)
                await asyncio.wait_for(tls.perform(tls.session.do_handshake), 5)
                read = tls.read
            if kind in ("http", "https"):
                method = "GET" if load else "HEAD"
                request = (f'{method} {config["probe_path"]} HTTP/1.1\r\nHost: {config["probe_host"]}'
                           "\r\nConnection: close\r\n\r\n").encode("ascii")
                if tls:
                    await asyncio.wait_for(tls.write(request), 4)
                else:
                    writer.write(request)
                    await asyncio.wait_for(writer.drain(), 4)
                header, buffered = await asyncio.wait_for(read_probe_header(read), 5)
                if not re.match(rb"HTTP/1\.[01] [23][0-9]{2} ", header):
                    raise OSError("Application returned an unexpected HTTP status")
                if load:
                    ready.set()
                    deadline = self.loop.time() + 8
                    cap = 4 * 1024 * 1024
                    remaining = cap - len(buffered)
                    while remaining > 0 and (timeout := deadline - self.loop.time()) > 0:
                        try:
                            chunk = await asyncio.wait_for(read(min(65536, remaining)), timeout)
                        except asyncio.TimeoutError:
                            break
                        if not chunk:
                            break
                        remaining -= len(chunk)
                    return {"bytes": cap - remaining}
            return {"ok": True, "ms": round((time.monotonic() - start) * 1000)}
        except (OSError, asyncio.TimeoutError, ValueError):
            return {"ok": False}
        finally:
            if ready:
                ready.set()
            if remote:
                await close(remote[1])

    def active_route(self, config):
        record = self.last_switch.get(config["name"], {})
        route = record.get("selected")
        if route_policy(config) != "manual" and record.get("preferred") == config.get("selected") and route in self.routes(config):
            return route
        return config.get("selected")

    async def monitor(self, config):
        name = config["name"]
        if self.demo:
            return
        routes = self.routes(config)
        results = await asyncio.gather(*(self.probe(config, route) for route in routes))
        if self.configs.get(name) is not config:
            return
        now = int(time.time())
        record = self.runtime.setdefault(name, {"tests": {}})
        selected = self.active_route(config)
        for route, result in zip(routes, results):
            previous = record["tests"].get(route, {})
            streak = (previous.get("streak", 0) if previous.get("ok") == result["ok"] else 0) + 1
            record["tests"][route] = {**result, "time": now, "streak": streak}
        history = self.history[name]
        tests = record["tests"].copy()
        point = {"time": now, "tests": tests, "selected": selected}
        history.append(point)
        del history[:-120]
        quality = record["quality"] = route_quality(history, routes)
        policy = route_policy(config)
        if policy == "manual":
            return
        current = tests[selected]
        if not current["ok"] and current["streak"] >= 2:
            eligible = [route for route in routes if route != selected and tests[route]["ok"] and tests[route]["streak"] >= 2]
            if eligible:
                if policy == "adaptive":
                    eligible.sort(key=lambda route: (-quality[route]["successes"], quality[route]["median_ms"]))
                point["selected"] = self.switch_route(config, eligible[0], now, "failure")
                record.pop("candidate", None)
                return
        if policy != "adaptive" or not current["ok"] or now - self.last_switch.get(name, {}).get("switched", 0) < QUALITY_HOLD:
            record.pop("candidate", None)
            return
        candidate = adaptive_candidate(quality, tests, selected)
        if candidate is None:
            record.pop("candidate", None)
            return
        previous, confirmations = record.get("candidate", (None, 0))
        confirmations = confirmations + 1 if previous == candidate else 1
        record["candidate"] = (candidate, confirmations)
        if confirmations >= QUALITY_CONFIRMATIONS:
            point["selected"] = self.switch_route(config, candidate, now, "quality")
            record.pop("candidate", None)

    def switch_route(self, config, route, now, reason):
        self.last_switch[config["name"]] = {"selected": route, "preferred": config["selected"],
                                            "switched": now, "reason": reason}
        self.persist_switch()
        return route

    def reload_certificates(self):
        for name, context in {**self.contexts, **self.quic_contexts}.items():
            try:
                context.load_cert_chain(*self.certificates(self.configs[name]))
            except (OSError, ValueError):
                logging.warning("Could not reload TLS certificate for %s", name)

    async def worker(self):
        while True:
            try:
                if self.dirty:
                    cutoff = sorted({m for months in self.totals.values() for m in months})[-12:]
                    self.totals = {name: {m: n for m, n in months.items() if m in cutoff}
                                   for name, months in self.totals.items() if name in self.configs}
                    self.save("traffic.json", self.totals)
                    self.dirty = False
                if not self.demo:
                    async with self.configuration_lock:
                        for name, config in tuple(self.configs.items()):
                            if name not in self.servers:
                                try:
                                    await self.listen(config)
                                except (OSError, p.Problem):
                                    logging.warning("Could not open relay listener %s", name)
                        self.reload_certificates()
                entries = [c for c in self.configs.values() if c["role"] == "entry"]
                await asyncio.gather(*(self.monitor(c) for c in entries))
            except Exception:
                logging.exception("Relay monitoring cycle failed")
            await asyncio.sleep(20)

    async def start_comparison(self, name):
        config = self.configs.get(name, {}) if isinstance(name, str) else {}
        if config.get("role") != "entry" or len(self.routes(config)) < 2 or self.demo:
            raise p.Problem("مقایسه به دو مسیر تنظیم‌شده در پنل واقعی نیاز دارد.")
        if name in self.monitored or len(self.monitored) >= 4:
            raise p.Problem("آزمون این مسیر از قبل در حال اجراست.")
        self.monitored.add(name)
        self.comparisons[name] = {"status": "running"}
        asyncio.create_task(self.compare(name, config))
        return {}

    async def compare(self, name, config):
        try:
            results = {}
            for route in self.routes(config):
                load_task = None
                if config["probe"] in ("http", "https"):
                    ready = asyncio.Event()
                    load_task = asyncio.create_task(self.probe(config, route, load=True, ready=ready))
                    await ready.wait()
                try:
                    samples = await asyncio.gather(*(self.probe(config, route) for _ in range(3)))
                    success = sorted(sample["ms"] for sample in samples if sample["ok"])
                    load_bytes = (await load_task).get("bytes", 0) if load_task else 0
                    results[route] = {"ok": len(success), "total": len(samples), "load_bytes": load_bytes,
                                      "p50_ms": success[math.ceil(len(success) / 2) - 1] if success else None}
                finally:
                    if load_task and not load_task.done():
                        load_task.cancel()
                        await asyncio.gather(load_task, return_exceptions=True)
            if self.configs.get(name) is config:
                self.comparisons[name] = {"status": "done", "results": results}
        except Exception:
            logging.exception("Comparison failed for %s", name)
            self.comparisons[name] = {"status": "error"}
        finally:
            if self.comparisons.get(name, {}).get("status") == "running":
                self.comparisons.pop(name, None)
            self.monitored.discard(name)

    async def select(self, name, route):
        config = self.configs.get(name, {}) if isinstance(name, str) else {}
        if config.get("role") != "entry" or route not in self.routes(config):
            raise p.Problem("مسیر انتخابی پیدا نشد.")
        updated = {**self.configs, name: {**config, "selected": route}}
        self.save("relays.json", updated)
        self.configs = updated
        self.runtime.pop(name, None)
        self.switch_route(updated[name], route, int(time.time()), "manual")

    def persist_switch(self):
        try:
            self.save("switches.json", {name: point for name, point in self.last_switch.items() if name in self.configs})
        except OSError:
            logging.exception("Could not persist current route selection")

    async def view(self):
        now = datetime.now(timezone.utc)
        period = month()
        rows = []
        for name, config in self.configs.items():
            record = self.runtime.get(name, {})
            used = self.totals.get(name, {}).get(period, 0)
            budget = config.get("budget", 0) * 1024**3
            certificate = acme.inspect(config["domain"]) if config["role"] == "receiver" and not self.demo else None
            rows.append({"certificate": certificate, **{k: v for k, v in config.items() if k not in ("key", "peer", "quic_peer")},
                         "has_peer": bool(config.get("peer")), "has_quic_peer": bool(config.get("quic_peer")),
                         "routes": self.routes(config),
                         "configured": config.get("selected"),
                         "selected": self.active_route(config),
                         "tests": record.get("tests", {}), "quality": record.get("quality", {}),
                         "policy": route_policy(config), "switched": self.last_switch.get(name, {}).get("switched"),
                         "switch_reason": self.last_switch.get(name, {}).get("reason"),
                         "online": name in self.servers, "connections": self.connections[name],
                         "month": period, "bytes": used,
                         "projected_days": round(budget / used * (now.day - 1 + now.hour / 24), 1)
                         if budget and used and now.day >= 2 else None,
                         "history": self.history.get(name, []), "comparison": self.comparisons.get(name)})
        return {"demo": self.demo, "quic": bool(self.quic) or self.demo,
                "certificate_job": self.certificate_job.copy() if self.certificate_job else None,
                "rows": json.loads(json.dumps(rows))}

    async def peer(self, name):
        config = self.configs.get(name, {}) if isinstance(name, str) else {}
        if config.get("role") != "receiver":
            raise p.Problem("گیرنده پیدا نشد.")
        _, port = p.endpoint(config["listen"], True)
        return {"format": f"paqet-{listener_transport(config)}-v1", "domain": config["domain"], "port": port, "key": config["key"]}

    def call(self, method, *args, timeout=8):
        future = asyncio.run_coroutine_threadsafe(getattr(self, method)(*args), self.loop)
        try:
            return future.result(timeout)
        except FutureTimeout as error:
            future.cancel()
            raise p.Problem("مهلت عملیات مسیر به پایان رسید.") from error

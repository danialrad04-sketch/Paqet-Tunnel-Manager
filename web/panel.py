"""Local Paqet administration and isolated UI demo."""
import argparse
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import subprocess
import tempfile
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import yaml

CONFIG = Path("/etc/paqet")
UNITS = Path("/etc/systemd/system")
CORE = Path("/usr/local/bin/paqet")
STATIC = Path(__file__).resolve().parent / "static"
NAME = r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,47}"
EXISTING_NAME = r"[a-zA-Z0-9_-]{1,241}"
MODES = ("normal", "fast", "fast2", "fast3")
ACTIONS = ("start", "stop", "restart")
CAP = 32768


class Problem(Exception):
    pass


def run(*args, required=True):
    result = subprocess.run(args, text=True, errors="replace", capture_output=True,
                            timeout=12, env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
                                             "LC_ALL": "C", "SYSTEMD_COLORS": "0"})
    if required and result.returncode:
        logging.warning("%s failed with status %s", args[0], result.returncode)
        raise Problem(f"اجرای {args[0]} ناموفق بود. گزارش سرویس را بررسی کنید.")
    return result


def systemctl(*args, required=True):
    return run("systemctl", "--no-pager", *args, required=required)


def unit(name):
    return f"paqet-{name}.service"


def number(value, lower, upper, label):
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]{1,6}", str(value)):
        raise Problem(f"مقدار «{label}» باید عدد باشد.")
    value = int(value)
    if not lower <= value <= upper:
        raise Problem(f"«{label}» باید بین {lower} و {upper} باشد.")
    return value


def ipv4(value):
    try:
        return str(ipaddress.IPv4Address(value if isinstance(value, str) else ""))
    except ValueError as error:
        raise Problem("آدرس IPv4 مقصد معتبر نیست.") from error


def network():
    routes = json.loads(run("ip", "-j", "-4", "route", "show", "default").stdout)
    route = next((item for item in routes if item.get("gateway") and item.get("dev")), None)
    if not route:
        raise Problem("مسیر پیش‌فرض IPv4 پیدا نشد.")
    device, gateway = route["dev"], route["gateway"]
    route_to_gateway = json.loads(run("ip", "-j", "-4", "route", "get", gateway).stdout)
    address = route_to_gateway[0].get("prefsrc") if route_to_gateway else None
    run("ping", "-c", "1", "-W", "1", gateway, required=False)
    neighbors = json.loads(run("ip", "-j", "neigh", "show", "to", gateway, "dev", device).stdout)
    mac = next((item["lladdr"] for item in neighbors if item.get("lladdr")), None)
    if not address or not mac:
        raise Problem("آدرس IPv4 یا MAC دروازه شبکه شناسایی نشد.")
    return device, address, mac


def atomic(path, content, mode):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, mode="w", encoding="utf-8") as out:
        temporary = Path(out.name)
        try:
            os.fchmod(out.fileno(), mode)
            out.write(content)
            out.flush()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def validate(data):
    name = data.get("name", "")
    role = data.get("role")
    mode = data.get("mode", "fast")
    if not isinstance(name, str) or not re.fullmatch(NAME, name):
        raise Problem("نام تونل باید ۱ تا ۴۸ نویسهٔ لاتین، عدد، خط تیره یا زیرخط داشته باشد.")
    if role not in ("server", "client") or mode not in MODES:
        raise Problem("نقش یا حالت KCP معتبر نیست.")
    port = number(data.get("port"), 1, 65535, "پورت تانل")
    key = data.get("key", "")
    if key == "" and role == "server":
        key = secrets.token_urlsafe(32)
    if not isinstance(key, str) or not 8 <= len(key) <= 128 or not key.isprintable() or key != key.strip():
        raise Problem("کلید مشترک باید ۸ تا ۱۲۸ نویسهٔ قابل چاپ داشته باشد.")
    kcp = {"key": key, "mode": mode, "block": "aes",
           "mtu": number(data.get("mtu", 1350), 576, 1500, "MTU")}
    config = {"role": role, "log": {"level": "error"}, "transport": {
        "protocol": "kcp", "conn": number(data.get("conn", 1), 1, 64, "اتصال KCP"), "kcp": kcp}}
    if role == "server":
        config["listen"] = {"addr": f":{port}"}
    else:
        config["server"] = {"addr": f"{ipv4(data.get('remote'))}:{port}"}
        forwards = data.get("forwards", [])
        if not isinstance(forwards, list) or len(forwards) > 24:
            raise Problem("حداکثر ۲۴ قانون انتقال پورت مجاز است.")
        config["forward"] = []
        seen = set()
        for rule in forwards:
            if not isinstance(rule, dict) or rule.get("protocol") not in ("tcp", "udp", "both"):
                raise Problem("پروتکل انتقال پورت معتبر نیست.")
            listen = number(rule.get("listen"), 1, 65535, "پورت ورودی")
            target = number(rule.get("target"), 1, 65535, "پورت مقصد")
            protocols = ("tcp", "udp") if rule["protocol"] == "both" else (rule["protocol"],)
            for protocol in protocols:
                if (listen, protocol) in seen:
                    raise Problem("قانون انتقال پورت تکراری است.")
                seen.add((listen, protocol))
                config["forward"].append({"listen": f"0.0.0.0:{listen}",
                                          "target": f"127.0.0.1:{target}", "protocol": protocol})
        socks = data.get("socks", "")
        if socks != "":
            config["socks5"] = [{"listen": f"127.0.0.1:{number(socks, 1, 65535, 'SOCKS5')}"}]
        if not config["forward"] and "socks5" not in config:
            raise Problem("برای کلاینت یک قانون انتقال پورت یا پورت SOCKS5 وارد کنید.")
    return name, port, config


def mapping(value):
    return value if isinstance(value, dict) else {}


def summary(name, config, state, enabled):
    transport = mapping(config.get("transport"))
    kcp = mapping(transport.get("kcp"))
    endpoint = mapping(config.get("listen") if config.get("role") == "server" else config.get("server"))
    return {"name": name, "role": str(config.get("role", "unknown")), "state": state,
            "enabled": enabled, "endpoint": str(endpoint.get("addr", "")),
            "mode": str(kcp.get("mode", "")),
            "mtu": str(kcp.get("mtu", "")), "conn": str(transport.get("conn", "")),
            "tunable": bool(kcp) and config.get("role") in ("server", "client")}


class Manager:
    def __init__(self, demo, panel_port=8765):
        self.demo = demo
        self.panel_port = panel_port
        self.samples = {}
        if demo:
            for name, role, state, address in [
                ("tehran-edge", "client", "active", "203.0.113.14:443"),
                ("frankfurt-core", "server", "active", ":443"),
                ("ams-backup", "server", "inactive", ":8443"),
                ("office-relay", "client", "failed", "198.51.100.27:443"),
            ]:
                config = {"role": role, "listen" if role == "server" else "server": {"addr": address},
                          "transport": {"conn": 1, "kcp": {"mode": "fast", "mtu": 1350}}}
                self.samples[name] = (config, state, state != "inactive")

    def names(self):
        if self.demo:
            return sorted(self.samples)
        output = systemctl("list-unit-files", "paqet-*.service", "--no-legend").stdout
        return sorted({match.group(1) for line in output.splitlines()
                       if (match := re.match(rf"^paqet-({EXISTING_NAME})\.service\s", line))})

    def config(self, name):
        path = CONFIG / f"{name}.yaml"
        try:
            with path.open() as source:
                return mapping(yaml.safe_load(source.read(262144)))
        except (OSError, yaml.YAMLError):
            return {}

    def inventory(self):
        names = self.names()
        if self.demo:
            return [summary(name, *self.samples[name]) for name in names]
        rows = []
        for offset in range(0, len(names), 100):
            output = systemctl("show", "-p", "Id,ActiveState,UnitFileState",
                               *(unit(name) for name in names[offset:offset + 100]),
                               required=False).stdout
            for block in output.strip().split("\n\n"):
                values = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
                match = re.fullmatch(rf"paqet-({EXISTING_NAME})\.service", values.get("Id", ""))
                if match:
                    name = match.group(1)
                    rows.append(summary(name, self.config(name), values.get("ActiveState", "unknown"),
                                        values.get("UnitFileState") in ("enabled", "enabled-runtime")))
        return sorted(rows, key=lambda row: row["name"])

    def create(self, data):
        name, port, config = validate(data)
        result = {"name": name}
        if config["role"] == "server":
            result["key"] = config["transport"]["kcp"]["key"]
        if self.demo:
            if name in self.samples:
                raise Problem("این نام قبلاً ثبت شده است.")
            self.samples[name] = (config, "active", True)
            return result
        if not os.access(CORE, os.X_OK):
            raise Problem("هسته Paqet نصب نشده است.")
        config_path = CONFIG / f"{name}.yaml"
        unit_path = UNITS / unit(name)
        names = self.names()
        if os.path.lexists(config_path) or os.path.lexists(unit_path) or name in names:
            raise Problem("این نام قبلاً در تنظیمات یا systemd ثبت شده است.")
        server = config["role"] == "server"
        if server:
            if port == self.panel_port:
                raise Problem("این پورت برای پنل رزرو شده است.")
            for existing in names:
                other = self.config(existing)
                listen = str(mapping(other.get("listen")).get("addr", ""))
                if other.get("role") == "server" and listen.rsplit(":", 1)[-1] == str(port):
                    raise Problem("این پورت قبلاً برای یک تونل سرور استفاده شده است.")
        device, address, mac = network()
        config["network"] = {"interface": device, "ipv4": {
            "addr": f"{address}:{port if server else 0}", "router_mac": mac},
            "tcp": {"local_flag": ["PA"]}}
        if not server:
            config["network"]["tcp"]["remote_flag"] = ["PA"]
        hooks = ""
        if server:
            helper = "/opt/paqet-panel/packet-rules.sh"
            hooks = (f"ExecStartPre={helper} add {name} {port}\n"
                     f"ExecStopPost={helper} remove {name} {port}\n")
        definition = f"""[Unit]
Description=Paqet Tunnel ({name})
Wants=network-online.target
After=network-online.target

[Service]
Type=exec
{hooks}ExecStart={CORE} run -c {config_path}
Restart=on-failure
RestartSec=5
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
"""
        CONFIG.mkdir(mode=0o755, exist_ok=True)
        try:
            atomic(config_path, yaml.safe_dump(config, sort_keys=False), 0o600)
            atomic(unit_path, definition, 0o644)
            systemctl("daemon-reload")
            systemctl("enable", "--now", unit(name))
            time.sleep(0.7)
            systemctl("is-active", "--quiet", unit(name))
        except (OSError, Problem, subprocess.SubprocessError):
            if unit_path.exists():
                try:
                    systemctl("disable", "--now", unit(name), required=False)
                except subprocess.SubprocessError:
                    logging.exception("Could not stop %s during rollback", unit(name))
                unit_path.unlink(missing_ok=True)
            config_path.unlink(missing_ok=True)
            systemctl("daemon-reload", required=False)
            raise Problem("راه‌اندازی تونل موفق نبود. گزارش همین سرویس را در journalctl بررسی کنید.")
        return result

    def action(self, name, action):
        if action not in (*ACTIONS, "enable", "disable"):
            raise Problem("عملیات سرویس معتبر نیست.")
        if self.demo:
            config, state, enabled = self.samples[name]
            if action in ACTIONS:
                state = "inactive" if action == "stop" else "active"
            else:
                enabled = action == "enable"
            self.samples[name] = (config, state, enabled)
        else:
            systemctl(action, unit(name))

    def tune(self, name, data):
        mode = data.get("mode")
        if mode not in MODES and mode != "":
            raise Problem("حالت KCP معتبر نیست.")
        mtu = number(data.get("mtu"), 576, 1500, "MTU")
        conn = number(data.get("conn"), 1, 64, "اتصال KCP")
        path = CONFIG / f"{name}.yaml"
        original = None
        if self.demo:
            config, _, _ = self.samples[name]
        else:
            if path.is_symlink() or not path.is_file():
                raise Problem("فایل تنظیمات این تونل قابل ویرایش نیست.")
            with path.open() as stream:
                original = stream.read(262145)
            if len(original) > 262144:
                raise Problem("فایل تنظیمات از حد مجاز بزرگ‌تر است.")
            try:
                config = mapping(yaml.safe_load(original))
            except yaml.YAMLError as error:
                raise Problem("فایل تنظیمات YAML معتبر نیست.") from error
        transport = mapping(config.get("transport"))
        kcp = mapping(transport.get("kcp"))
        if not kcp or config.get("role") not in ("server", "client"):
            raise Problem("پارامترهای KCP این سرویس پیدا نشد.")
        if kcp.get("mode") == "manual" and mode:
            raise Problem("برای تنظیمات دستی، حالت فعلی را نگه دارید.")
        if mode:
            kcp["mode"] = mode
        kcp["mtu"] = mtu
        transport["conn"] = conn
        if self.demo:
            return
        active = systemctl("is-active", unit(name), required=False).stdout.strip() == "active"
        atomic(path, yaml.safe_dump(config, sort_keys=False), 0o600)
        if active:
            try:
                systemctl("restart", unit(name))
                time.sleep(0.7)
                systemctl("is-active", "--quiet", unit(name))
            except (Problem, subprocess.SubprocessError):
                atomic(path, original, 0o600)
                systemctl("restart", unit(name), required=False)
                raise Problem("اعمال تنظیمات موفق نبود. فایل قبلی بازیابی شد.")

    def logs(self, name):
        if self.demo:
            return f"[DEMO] paqet-{name}.service\n[DEMO] Journal output is simulated.\n"
        return run("journalctl", "--no-pager", "-q", "-o", "short-iso",
                   "-n", "120", "-u", unit(name)).stdout[-CAP:]

    def health(self):
        return {"host": "paqet-demo" if self.demo else socket.gethostname(),
                "core": self.demo or os.access(CORE, os.X_OK), "demo": self.demo}


def accepted_host(host, public_http):
    if not host:
        return False
    match = re.fullmatch(r"([a-z0-9.]+):([0-9]{1,5})", host)
    if not match or not 1 <= int(match.group(2)) <= 65535:
        return False
    address = match.group(1)
    if address in ("127.0.0.1", "localhost"):
        return True
    if public_http:
        try:
            ipaddress.IPv4Address(address)
            return True
        except ValueError:
            return False
    return False


class Panel(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send_data(self, status, data, content_type, cookie=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def answer(self, status, data, cookie=None):
        self.send_data(status, json.dumps(data).encode(), "application/json; charset=utf-8", cookie)

    def session(self):
        cookies = SimpleCookie(self.headers.get("Cookie", ""))
        return cookies["paqet_session"].value if "paqet_session" in cookies else ""

    def authenticated(self):
        return self.server.manager.demo or self.server.sessions.get(self.session(), 0) > time.monotonic()

    def payload(self):
        if self.headers.get_content_type() != "application/json":
            raise Problem("درخواست JSON معتبر نیست.")
        size = number(self.headers.get("Content-Length", 0), 2, CAP, "اندازه درخواست")
        data = json.loads(self.rfile.read(size))
        if not isinstance(data, dict):
            raise Problem("ساختار درخواست معتبر نیست.")
        return data

    def do_GET(self):
        self.handle_request("GET")

    def do_POST(self):
        self.handle_request("POST")

    def handle_request(self, method):
        host = self.headers.get("Host")
        if not accepted_host(host, self.server.public_http):
            self.answer(403, {"error": "میزبان درخواست مجاز نیست."})
            return
        if method == "POST" and self.headers.get("Origin") != f"http://{host}":
            self.answer(403, {"error": "مبدأ درخواست مجاز نیست."})
            return
        path = urlsplit(self.path).path
        manager = self.server.manager
        try:
            if method == "GET" and path in ("/", "/app.js", "/styles.css"):
                filename, mime = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                                  "/styles.css": ("styles.css", "text/css")}[path]
                self.send_data(200, (STATIC / filename).read_bytes(), f"{mime}; charset=utf-8")
            elif method == "GET" and path == "/api/session":
                self.answer(200, {"authenticated": self.authenticated(), "demo": manager.demo})
            elif method == "POST" and path == "/api/login":
                self.login()
            elif path.startswith("/api/") and not self.authenticated():
                self.answer(401, {"error": "ابتدا وارد پنل شوید."})
            elif method == "POST" and path == "/api/logout":
                self.server.sessions.pop(self.session(), None)
                self.answer(200, {}, "paqet_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0")
            elif method == "GET" and path == "/api/overview":
                self.answer(200, {**manager.health(), "tunnels": manager.inventory()})
            elif method == "POST" and path == "/api/tunnels":
                created = manager.create(self.payload())
                logging.info("Provisioned %s", unit(created["name"]))
                self.answer(201, created)
            elif (match := re.fullmatch(rf"/api/tunnels/({EXISTING_NAME})/(logs|action|tune)", path)):
                name, operation = match.groups()
                if name not in manager.names():
                    self.answer(404, {"error": "تونل پیدا نشد."})
                elif method == "GET" and operation == "logs":
                    self.answer(200, {"logs": manager.logs(name)})
                elif method == "POST" and operation == "action":
                    action = self.payload().get("action")
                    manager.action(name, action)
                    logging.info("Service action: %s %s", action, unit(name))
                    self.answer(200, {})
                elif method == "POST" and operation == "tune":
                    manager.tune(name, self.payload())
                    logging.info("Updated KCP settings: %s", unit(name))
                    self.answer(200, {})
                else:
                    self.answer(405, {"error": "روش درخواست مجاز نیست."})
            else:
                self.answer(404, {"error": "این مسیر پیدا نشد."})
        except (Problem, ValueError) as error:
            self.answer(400, {"error": str(error) if isinstance(error, Problem) else "دادهٔ درخواست معتبر نیست."})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (OSError, subprocess.SubprocessError):
            logging.exception("Panel operation failed")
            self.answer(503, {"error": "ارتباط با سرویس سیستم ناموفق بود."})

    def login(self):
        if self.server.manager.demo:
            self.answer(200, {})
            return
        now = time.monotonic()
        server = self.server
        server.attempts[:] = [attempt for attempt in server.attempts if now - attempt < 60]
        if len(server.attempts) >= 8:
            self.answer(429, {"error": "تعداد تلاش زیاد است. یک دقیقه صبر کنید."})
            return
        supplied = self.payload().get("token")
        if not isinstance(supplied, str) or not hmac.compare_digest(
                hashlib.sha256(supplied.encode()).digest(), server.token_hash):
            server.attempts.append(now)
            self.answer(401, {"error": "توکن ورود معتبر نیست."})
            return
        server.sessions = {key: expiry for key, expiry in server.sessions.items() if expiry > now}
        if len(server.sessions) >= 100:
            server.sessions.pop(next(iter(server.sessions)))
        session = secrets.token_urlsafe(32)
        server.sessions[session] = now + 28800
        self.answer(200, {}, f"paqet_session={session}; Path=/; HttpOnly; SameSite=Strict; Max-Age=28800")


class LocalServer(HTTPServer):
    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--bind", type=ipaddress.IPv4Address,
                        default=os.environ.get("PAQET_HTTP_BIND", "127.0.0.1"))
    parser.add_argument("--token-file", type=Path, default=Path("/etc/paqet-panel/token"))
    options = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    token = secrets.token_urlsafe(32) if options.demo else options.token_file.read_text().strip()
    if not options.demo and len(token) < 32:
        parser.error("The admin token must have at least 32 characters.")
    if options.demo and not options.bind.is_loopback:
        parser.error("Demo mode is limited to loopback.")
    bind = str(options.bind)
    with LocalServer((bind, options.port), Panel) as server:
        server.public_http = not options.bind.is_loopback
        port = server.server_port
        server.manager = Manager(options.demo, port)
        server.token_hash = hashlib.sha256(token.encode()).digest()
        server.sessions, server.attempts = {}, []
        print(f"Listening on {bind}:{port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()

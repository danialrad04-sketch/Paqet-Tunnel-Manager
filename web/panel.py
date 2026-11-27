"""Local Paqet administration and isolated UI demo."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import yaml

CONFIG = Path("/etc/paqet")
UNITS = Path("/etc/systemd/system")
STATE = Path("/etc/paqet-panel")
CORE = Path("/usr/local/bin/paqet")
PROBE_CORE = Path("/usr/local/bin/paqet-health")
STATIC = Path(__file__).resolve().parent / "static"
FONTS = {"/fonts/vazirmatn.woff2": "vazirmatn.woff2", "/fonts/jetbrains-mono.woff2": "jetbrains-mono.woff2"}
NAME = r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,47}"
EXISTING_NAME = r"[a-zA-Z0-9_-]{1,241}"
MODES = ("normal", "fast", "fast2", "fast3")
ACTIONS = ("start", "stop", "restart")
KCP_NUMERIC = ("nodelay", "interval", "resend", "nocongestion", "rcvwnd", "sndwnd",
               "smuxbuf", "streambuf", "dshard", "pshard", "smuxkalive", "smuxktimeout")
KCP_BOOLEAN = ("wdelay", "acknodelay")
CAP = 524288


class Problem(Exception):
    pass


def run(*args, required=True):
    result = subprocess.run(args, text=True, errors="replace", capture_output=True,
                            timeout=12, env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
                                             "LC_ALL": "C", "SYSTEMD_COLORS": "0"})
    if required and result.returncode:
        logging.warning("%s failed with status %s", args[0], result.returncode)
        detail = result.stderr.strip()[-1200:] or f"exit {result.returncode}"
        raise Problem(f"{args[0]} {args[2] if args[0] == 'systemctl' else ''} — {detail}")
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


def endpoint(value, listener):
    if not isinstance(value, str):
        raise Problem("آدرس باید به صورت host:port باشد.")
    match = re.fullmatch(r"(?:\[([^\]]+)\]|([^:\s/]*)):([0-9]{1,5})", value)
    if not match:
        raise Problem("آدرس باید به صورت host:port یا [IPv6]:port باشد.")
    host = match.group(1) or match.group(2) or ""
    try:
        if host or not listener:
            host = str(ipaddress.ip_address(host))
    except ValueError:
        if listener or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", host):
            raise Problem("آدرس ورودی یا مقصد معتبر نیست.")
    return host, number(match.group(3), 1, 65535, "پورت")


def route_to(target):
    routes = json.loads(run("ip", "-j", "-4", "route", "get", ipv4(target)).stdout)
    route = routes[0] if routes else {}
    if not route.get("dev") or not route.get("prefsrc"):
        raise Problem("مسیر خروجی IPv4 پیدا نشد.")
    return {"interface": route["dev"], "local": route["prefsrc"],
            "next_hop": route.get("gateway", target)}


def network(target=None):
    if target:
        route = route_to(target)
    else:
        defaults = json.loads(run("ip", "-j", "-4", "route", "show", "default").stdout)
        gateway = next((item["gateway"] for item in defaults if item.get("gateway")), None)
        if not gateway:
            raise Problem("مسیر پیش‌فرض IPv4 پیدا نشد.")
        route = route_to(gateway)
    device, address, gateway = route["interface"], route["local"], route["next_hop"]
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
    if role not in ("server", "client") or mode not in (*MODES, "manual"):
        raise Problem("نقش یا حالت KCP معتبر نیست.")
    port = number(data.get("port"), 1, 65535, "پورت تانل")
    key = data.get("key", "")
    if key == "" and role == "server":
        key = secrets.token_urlsafe(32)
    if not isinstance(key, str) or not 8 <= len(key) <= 128 or not key.isprintable() or key != key.strip():
        raise Problem("کلید مشترک باید ۸ تا ۱۲۸ نویسهٔ قابل چاپ داشته باشد.")
    kcp = {"key": key, "mode": mode, "block": "aes",
           "mtu": number(data.get("mtu", 1350), 50, 1500, "MTU")}
    config = {"role": role, "log": {"level": "error"}, "transport": {
        "protocol": "kcp", "conn": number(data.get("conn", 1), 1, 256, "اتصال KCP"), "kcp": kcp}}
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
            bind = ipv4(rule.get("listen_ip", "0.0.0.0"))
            destination = ipv4(rule.get("target_ip", "127.0.0.1"))
            protocols = ("tcp", "udp") if rule["protocol"] == "both" else (rule["protocol"],)
            for protocol in protocols:
                if any(p == listen and proto == protocol and (addr == bind or "0.0.0.0" in (addr, bind))
                       for addr, p, proto in seen):
                    raise Problem("قانون انتقال پورت تکراری است.")
                seen.add((bind, listen, protocol))
                config["forward"].append({"listen": f"{bind}:{listen}",
                                          "target": f"{destination}:{target}", "protocol": protocol})
        socks = data.get("socks", "")
        if socks != "":
            config["socks5"] = [{"listen": f"{ipv4(data.get('socks_ip', '127.0.0.1'))}:{number(socks, 1, 65535, 'SOCKS5')}"}]
            if data.get("socks_user") or data.get("socks_password"):
                if not all(isinstance(data.get(k), str) and data[k] for k in ("socks_user", "socks_password")):
                    raise Problem("نام کاربری و رمز SOCKS5 را با هم وارد کنید.")
                config["socks5"][0].update(username=data["socks_user"], password=data["socks_password"])
        if not config["forward"] and "socks5" not in config:
            raise Problem("برای کلاینت یک قانون انتقال پورت یا پورت SOCKS5 وارد کنید.")
    if data.get("transport") is not None:
        imported = mapping(data["transport"])
        if imported.get("protocol") != "kcp" or not isinstance(imported.get("kcp"), dict):
            raise Problem("تنظیمات انتقال فایل جفت‌سازی معتبر نیست.")
        config["transport"] = deepcopy(imported)
        config["transport"]["kcp"].update(key=key, mode=mode, mtu=kcp["mtu"])
        config["transport"]["conn"] = number(data.get("conn", 1), 1, 256, "اتصال KCP")
    if data.get("block"):
        config["transport"]["kcp"]["block"] = data["block"]
    if data.get("level"):
        config["log"]["level"] = data["level"]
    for key in ("tcpbuf", "udpbuf"):
        if data.get(key):
            value = str(data[key])
            if not re.fullmatch(r"[0-9]{1,10}", value) or int(value) > 2147483647:
                raise Problem("اندازه بافر معتبر نیست.")
            config["transport"][key] = int(value)
    return name, port, config


def mapping(value):
    return value if isinstance(value, dict) else {}


def service_config_path(command):
    match = re.search(r"(?:^|\s)(?:-c|--config)(?:\s+|=)([^\s;]+)", command)
    return Path(match.group(1)) if match else None


def config_role(config):
    role = config.get("role")
    if role in ("server", "client"):
        return role, "explicit"
    if role is None:
        server = bool(mapping(config.get("listen")).get("addr"))
        client = bool(mapping(config.get("server")).get("addr"))
        if client != server:
            return ("client" if client else "server"), "inferred"
    return "unknown", "unknown"


def coordinates(rows):
    roles = {row["role"] for row in rows if row["role"] in ("client", "server")}
    return next(iter(roles)) if len(roles) == 1 else "mixed" if roles else "unknown"


def system_sample():
    sample = {}
    for filename, read in {
        "stat": lambda lines: [int(value) for value in lines[0].split()[1:9]],
        "meminfo": lambda lines: {line.split(":")[0]: int(line.split()[1]) * 1024 for line in lines
                                  if line.startswith(("MemTotal:", "MemAvailable:"))},
        "net/dev": lambda lines: {device.strip(): [int(fields.split()[idx]) for idx in (0, 8)]
                                   for line in lines[2:] if ":" in line
                                   for device, fields in [line.split(":", 1)] if device.strip() != "lo"},
    }.items():
        try:
            sample[filename] = read(Path("/proc", filename).read_text().splitlines())
        except (OSError, ValueError, IndexError):
            continue
    return {"cpu": sample.get("stat", []), "memory": sample.get("meminfo", {}),
            "interfaces": sample.get("net/dev", {}), "time": time.monotonic()}


def summary(name, config, state, enabled, properties=None, source="default"):
    values = properties or {}
    transport = mapping(config.get("transport"))
    kcp = mapping(transport.get("kcp"))
    role, evidence = config_role(config)
    endpoint = mapping(config.get("listen" if role == "server" else "server"))
    network = mapping(config.get("network"))
    forwards = config.get("forward")
    forwards = [{"listen": str(rule.get("listen", "")), "target": str(rule.get("target", "")),
                 "protocol": str(rule.get("protocol", ""))}
                for rule in forwards[:256] if isinstance(rule, dict)] if isinstance(forwards, list) else []
    return {"name": name, "role": role, "evidence": evidence, "state": state, "enabled": enabled,
            "endpoint": str(endpoint.get("addr", "")), "source": source, "forwards": forwards,
            "interface": str(network.get("interface", "")), "local": str(mapping(network.get("ipv4")).get("addr", "")),
            "buffers": {"sockbuf": mapping(network.get("pcap")).get("sockbuf"),
                        "tcpbuf": transport.get("tcpbuf"), "udpbuf": transport.get("udpbuf")},
            "level": str(mapping(config.get("log")).get("level", "")),
            "advanced": {field: kcp[field] for field in (*KCP_NUMERIC, *KCP_BOOLEAN) if field in kcp},
            "mode": str(kcp.get("mode", "")), "mtu": str(kcp.get("mtu", "")), "conn": str(transport.get("conn", "")),
            "restarts": values.get("NRestarts", ""), "pid": values.get("MainPID", ""),
            "result": values.get("Result", ""), "since": values.get("ActiveEnterTimestamp", ""),
            "tunable": bool(kcp) and evidence == "explicit" and source == "default" and state != "unregistered"}


class Manager:
    def __init__(self, demo, panel_port=8765):
        self.demo = demo
        self.panel_port = panel_port
        from operations import Operations
        self.operations = Operations(self)
        self.samples, self.demo_backups, self.demo_archive, self.demo_hosts = {}, {}, {}, []
        self.demo_region = "ir"
        if demo:
            for name, role, state, address in [
                ("tehran-edge", "client", "active", "203.0.113.14:443"),
                ("frankfurt-core", "server", "active", ":443"),
                ("ams-backup", "server", "inactive", ":8443"),
                ("office-relay", "client", "failed", "198.51.100.27:443"),
            ]:
                config = {"role": role, "listen" if role == "server" else "server": {"addr": address},
                          "transport": {"protocol": "kcp", "conn": 1, "kcp": {"key": "example-demo-key", "block": "aes", "mode": "fast", "mtu": 1350}}}
                if role == "client":
                    config["socks5"] = [{"listen": "127.0.0.1:1080"}]
                    config["forward"] = [{"listen":"0.0.0.0:8443", "target":"127.0.0.1:443", "protocol":"tcp"}]
                self.samples[name] = (config, state, state != "inactive")

    def names(self):
        if self.demo:
            return sorted(self.samples)
        # A pattern with no matching unit can return a failure on older systemd.
        output = systemctl("list-unit-files", "--type=service", "--no-legend").stdout
        return sorted({match.group(1) for line in output.splitlines()
                       if (match := re.match(rf"^paqet-({EXISTING_NAME})\.service\s", line))})

    def config(self, name, path=None):
        path = path or CONFIG / f"{name}.yaml"
        try:
            with path.open() as source:
                text = source.read(262145)
            return mapping(yaml.safe_load(text)) if len(text) <= 262144 else {}
        except (OSError, UnicodeError, yaml.YAMLError, RecursionError):
            return {}

    def inventory(self):
        names = self.names()
        if self.demo:
            return [dict(summary(name, *self.samples[name]), archivable=True) for name in names]
        rows, config_references = {}, {}
        for offset in range(0, len(names), 100):
            output = systemctl("show", "-p",
                               "Id,ActiveState,UnitFileState,ExecStart,NRestarts,MainPID,Result,ActiveEnterTimestamp,FragmentPath,DropInPaths",
                               *(unit(name) for name in names[offset:offset + 100])).stdout
            for block in output.strip().split("\n\n"):
                values = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
                match = re.fullmatch(rf"paqet-({EXISTING_NAME})\.service", values.get("Id", ""))
                if not match:
                    continue
                name = match.group(1)
                default = CONFIG / f"{name}.yaml"
                command = values.get("ExecStart", "")
                path = service_config_path(command)
                accessible = path and path.parent == CONFIG and path.suffix in (".yaml", ".yml")
                source = "default" if path == default else "alternate" if accessible else "unresolved"
                config_references[name] = (path.resolve() if accessible else None)
                rows[name] = summary(name, self.config(name, path) if accessible else {},
                                     values.get("ActiveState", "unknown"),
                                     values.get("UnitFileState") in ("enabled", "enabled-runtime"), values, source)
                fragment = UNITS / unit(name)
                rows[name]["config_file"] = path.name if accessible and path.is_file() and not path.is_symlink() else ""
                rows[name]["archivable"] = (
                    source == "default" and default.is_file() and not default.is_symlink()
                    and values.get("FragmentPath") == str(fragment) and fragment.is_file()
                    and not fragment.is_symlink() and not values.get("DropInPaths")
                    and values.get("UnitFileState") in ("enabled", "disabled")
                    and rows[name]["state"] in ("active", "inactive", "failed"))
        references = Counter(config_references.values())
        for name, row in rows.items():
            if references[config_references[name]] != 1:
                row["archivable"] = False
                row["config_file"] = ""
        for path in sorted(CONFIG.glob("*.y*ml")):
            if path.suffix in (".yaml", ".yml") and re.fullmatch(EXISTING_NAME, path.stem) and path.stem not in rows and path.resolve() not in references:
                config = self.config(path.stem, path)
                if "role" in config or config_role(config)[0] != "unknown":
                    rows[path.stem] = summary(path.stem, config, "unregistered", False, source="file")
                    rows[path.stem]["config_file"] = path.name if not path.is_symlink() else ""
        return [rows[name] for name in sorted(rows)]

    def region(self):
        if self.demo:
            return self.demo_region
        try:
            value = (STATE / "region").read_text().strip()
        except FileNotFoundError:
            return ""
        return value if value in ("ir", "foreign") else ""

    def set_region(self, region):
        if region not in ("", "ir", "foreign"):
            raise Problem("موقعیت انتخاب‌شده معتبر نیست.")
        if self.demo:
            self.demo_region = region
        else:
            atomic(STATE / "region", region + "\n", 0o600)

    def backup_path(self, name):
        return STATE / "restore-points" / f"{name}.json"

    def has_backup(self, name):
        return name in self.demo_backups if self.demo else self.backup_path(name).is_file()

    def restore(self, name):
        if not self.has_backup(name):
            raise Problem("نقطهٔ بازیابی پیدا نشد.")
        if self.demo:
            self.operations.remember(name, self.full_config(name)["yaml"], "restore")
            config, status, enabled = self.samples[name]
            config = self.demo_backups.pop(name)
            self.samples[name] = (config, status, enabled)
            return
        row = next((row for row in self.inventory() if row["name"] == name), {})
        if not row.get("config_file"):
            raise Problem("فایل کنونی سرویس برای بازیابی قابل تأیید نیست.")
        backup = self.backup_path(name)
        path = self.editor_path(name)
        if path.is_symlink():
            raise Problem("بازیابی فایل پیوندی مجاز نیست.")
        original = path.read_text()
        point = json.loads(backup.read_text())
        if hashlib.sha256(original.encode()).hexdigest() != point.get("updated"):
            raise Problem("تنظیمات پس از ساخت نقطهٔ بازیابی تغییر کرده است.")
        self.operations.remember(name, original, "restore")
        atomic(path, point["original"], 0o600)
        self.apply_change(name, path, original, row["state"] == "active")
        backup.unlink()

    @staticmethod
    def apply_change(name, path, original, active):
        if not active:
            return
        try:
            systemctl("restart", unit(name))
            time.sleep(0.7)
            systemctl("is-active", "--quiet", unit(name))
        except (Problem, subprocess.SubprocessError) as error:
            detail = Manager.failure_detail(name, error)
            atomic(path, original, 0o600)
            systemctl("restart", unit(name), required=False)
            raise Problem("فایل قبلی بازیابی شد. " + detail) from error

    def check_name_available(self, name):
        if self.demo:
            taken = name in self.samples or name in self.demo_archive
        else:
            existing = (CONFIG / f"{name}.yaml", CONFIG / f"{name}.yml", UNITS / unit(name))
            taken = name in self.archives() or any(os.path.lexists(path) for path in existing) or name in self.names()
        if taken:
            raise Problem("این نام قبلاً در تنظیمات یا systemd ثبت شده است.")

    def create(self, data):
        if "yaml" in data:
            name = data.get("name", "")
            if not isinstance(name, str) or not re.fullmatch(NAME, name):
                raise Problem("نام تونل معتبر نیست.")
            config = self.parse_configuration(data["yaml"])
            side = mapping(config.get("listen") if config.get("role") == "server" else config.get("server"))
            port = number(str(side.get("addr", "")).rsplit(":", 1)[-1], 1, 65535, "پورت")
        else:
            name, port, config = validate(data)
        self.check_configuration(name, config)
        self.check_name_available(name)
        result = {"name": name}
        if config["role"] == "server":
            result["key"] = config["transport"]["kcp"]["key"]
        if self.demo:
            self.samples[name] = (config, "active", True)
            return result
        if not os.access(CORE, os.X_OK):
            raise Problem("هسته Paqet نصب نشده است.")
        config_path = CONFIG / f"{name}.yaml"
        unit_path = UNITS / unit(name)
        server = config["role"] == "server"
        if server:
            if port == self.panel_port:
                raise Problem("این پورت برای پنل رزرو شده است.")
            for other in self.inventory():
                listen = other["endpoint"]
                if other["role"] == "server" and listen.rsplit(":", 1)[-1] == str(port):
                    raise Problem("این پورت قبلاً برای یک تونل سرور استفاده شده است.")
        if not config.get("network"):
            device, address, mac = network(None if server else config["server"]["addr"].rsplit(":", 1)[0])
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
After=network.target

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
        except (OSError, Problem, subprocess.SubprocessError) as error:
            detail = self.failure_detail(name, error)
            if unit_path.exists():
                try:
                    systemctl("disable", "--now", unit(name), required=False)
                except subprocess.SubprocessError:
                    logging.exception("Could not stop %s during rollback", unit(name))
                unit_path.unlink(missing_ok=True)
            config_path.unlink(missing_ok=True)
            systemctl("daemon-reload", required=False)
            raise Problem(detail) from error
        return result

    @staticmethod
    def failure_detail(name, error):
        try:
            lines = run("journalctl", "-q", "--no-pager", "-n", "8", "-o", "cat", "-u", unit(name),
                        required=False).stdout.strip()[-1800:]
        except (OSError, subprocess.SubprocessError):
            lines = ""
        return f"{unit(name)} — {error}\n{lines}".strip()

    def editor_path(self, name):
        row = next((r for r in self.inventory() if r["name"] == name), {})
        filename = row.get("config_file")
        if not filename or Path(filename).name != filename:
            raise Problem("مسیر فایل مستقل این تونل تأیید نشد.")
        path = CONFIG / filename
        if path.is_symlink() or not path.is_file():
            raise Problem("فایل تنظیمات در دسترس نیست.")
        return path

    def full_config(self, name):
        if self.demo:
            if name not in self.samples:
                raise Problem("تونل پیدا نشد.")
            text = yaml.safe_dump(self.samples[name][0], sort_keys=False)
        else:
            path = self.editor_path(name)
            with path.open() as source:
                text = source.read(262145)
            if len(text.encode()) > 262144:
                raise Problem("حجم تنظیمات بیشتر از ۲۵۶ کیلوبایت است.")
        return {"yaml": text, "forwards": mapping(yaml.safe_load(text)).get("forward") or [], "revision": hashlib.sha256(text.encode()).hexdigest()}

    def replace_config(self, name, data):
        current = self.full_config(name)
        if data.get("revision") != current["revision"]:
            raise Problem("فایل تغییر کرده است. تنظیمات را دوباره باز کنید.")
        text = data.get("yaml")
        new = self.parse_configuration(text)
        old = mapping(yaml.safe_load(current["yaml"]))
        if new.get("role") != old.get("role"):
            raise Problem("برای تغییر نقش، سرویس جدید ایجاد کنید.")
        self.check_configuration(name, new)
        if self.demo:
            self.operations.remember(name, current["yaml"])
            config, state, enabled = self.samples[name]
            self.demo_backups[name] = deepcopy(config)
            self.samples[name] = (new, state, enabled)
        else:
            active = systemctl("is-active", unit(name), required=False).stdout.strip() == "active"
            self.save_config(name, self.editor_path(name), current["yaml"], new, active, text)

    @staticmethod
    def parse_configuration(text):
        if not isinstance(text, str) or len(text.encode()) > 262144:
            raise Problem("حجم فایل YAML معتبر نیست.")
        try:
            if any(isinstance(token, yaml.tokens.AliasToken) for token in yaml.scan(text)):
                raise Problem("ارجاع YAML مجاز نیست.")
            return mapping(yaml.safe_load(text))
        except (yaml.YAMLError, RecursionError) as error:
            raise Problem("ساختار YAML معتبر نیست.") from error

    def check_configuration(self, name, new):
        role = new.get("role")
        if role not in ("client", "server"):
            raise Problem("نقش باید client یا server باشد.")
        transport = mapping(new.get("transport"))
        if transport.get("protocol") != "kcp" or not isinstance(mapping(transport.get("kcp")).get("key"), str) or not transport["kcp"]["key"]:
            raise Problem("پروتکل KCP و کلید مشترک لازم است.")
        if role == "server":
            _, port = endpoint(mapping(new.get("listen")).get("addr"), True)
            if port == self.panel_port:
                raise Problem("پورت پنل رزرو شده است.")
            if any(r["name"] != name and r["role"] == "server" and r["endpoint"].rsplit(":",1)[-1] == str(port)
                   for r in self.inventory()):
                raise Problem("این پورت در تنظیمات سرور دیگری استفاده شده است.")
        else:
            if not mapping(new.get("server")).get("addr") or not (new.get("forward") or new.get("socks5")):
                raise Problem("آدرس سرور و دست‌کم یک forward یا socks5 لازم است.")
            endpoint(mapping(new.get("server")).get("addr"), False)
            for key in ("forward", "socks5"):
                if key in new and not isinstance(new[key], list):
                    raise Problem(f"{key} باید فهرست باشد.")
            listeners = []
            for group in ("forward", "socks5"):
                for rule in new.get(group) or []:
                    if not isinstance(rule, dict):
                        raise Problem("قالب قانون انتقال یا SOCKS5 معتبر نیست.")
                    protocol = rule.get("protocol") if group == "forward" else "tcp"
                    if protocol not in ("tcp", "udp"):
                        raise Problem("پروتکل باید tcp یا udp باشد.")
                    bind, port = endpoint(rule.get("listen"), True)
                    if group == "forward":
                        endpoint(rule.get("target"), False)
                    if port == self.panel_port and protocol == "tcp":
                        raise Problem("پورت ورودی با پورت پنل تداخل دارد.")
                    for other, used_port, used_protocol in listeners:
                        if used_port == port and used_protocol == protocol and (
                                bind == other or bind in ("", "::", "0.0.0.0") or other in ("", "::", "0.0.0.0")):
                            raise Problem("آدرس ورودی و پروتکل تکراری است.")
                    listeners.append((bind, port, protocol))

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
        if mode not in (*MODES, "manual", ""):
            raise Problem("حالت KCP معتبر نیست.")
        mtu = number(data.get("mtu"), 50, 1500, "MTU")
        conn = number(data.get("conn"), 1, 256, "اتصال KCP")
        path, original, config, active = self.editable_config(name)
        transport = mapping(config.get("transport"))
        kcp = mapping(transport.get("kcp"))
        if not kcp or config.get("role") not in ("server", "client"):
            raise Problem("پارامترهای KCP این سرویس پیدا نشد.")
        changes = {}
        for field in KCP_NUMERIC:
            if field in data and data[field] != "":
                raw = str(data[field])
                if not re.fullmatch(r"[0-9]{1,10}", raw) or int(raw) > 2147483647:
                    raise Problem(f"مقدار {field} معتبر نیست.")
                changes[field] = int(raw)
        for field in KCP_BOOLEAN:
            if field in data and data[field] != "":
                if data[field] not in ("true", "false"):
                    raise Problem(f"مقدار {field} معتبر نیست.")
                changes[field] = data[field] == "true"
        buffers = {}
        for field in ("sockbuf", "tcpbuf", "udpbuf"):
            if field in data:
                value = str(data[field])
                if value and (not re.fullmatch(r"[0-9]{1,10}", value) or int(value) > 2147483647):
                    raise Problem(f"اندازهٔ {field} معتبر نیست.")
                if field == "sockbuf" and value and int(value) != 0 and not 1024 <= int(value) <= 104857600:
                    raise Problem("بافر PCAP باید صفر یا بین ۱۰۲۴ بایت و ۱۰۰ مگابایت باشد.")
                buffers[field] = int(value) if value else None
        level = data.get("level")
        if level is not None and level not in ("", "none", "debug", "info", "warn", "error", "fatal"):
            raise Problem("سطح گزارش معتبر نیست.")
        if self.demo:
            self.operations.remember(name, self.full_config(name)["yaml"])
            self.demo_backups[name] = deepcopy(config)
        for field in (*KCP_NUMERIC, *KCP_BOOLEAN):
            if data.get(field) == "":
                kcp.pop(field, None)
        for field, value in buffers.items():
            settings = transport
            if field == "sockbuf":
                if value is None and not mapping(mapping(config.get("network")).get("pcap")):
                    continue
                settings = config.setdefault("network", {}).setdefault("pcap", {})
            if value is None:
                settings.pop(field, None)
            else:
                settings[field] = value
        if level:
            config.setdefault("log", {})["level"] = level
        elif level == "":
            mapping(config.get("log")).pop("level", None)
        kcp.update(changes)
        if mode:
            kcp["mode"] = mode
        kcp["mtu"] = mtu
        transport["conn"] = conn
        if not self.demo:
            self.save_config(name, path, original, config, active)

    def editable_config(self, name):
        path = CONFIG / f"{name}.yaml"
        original = None
        row = {}
        if self.demo:
            config, _, _ = self.samples[name]
        else:
            row = next((row for row in self.inventory() if row["name"] == name), {})
            if not row.get("tunable") or path.is_symlink() or not path.is_file():
                raise Problem("فایل تنظیمات این تونل قابل ویرایش نیست.")
            with path.open() as stream:
                original = stream.read(262145)
            if len(original) > 262144:
                raise Problem("فایل تنظیمات از حد مجاز بزرگ‌تر است.")
            try:
                config = mapping(yaml.safe_load(original))
            except yaml.YAMLError as error:
                raise Problem("فایل تنظیمات YAML معتبر نیست.") from error
        return path, original, config, row.get("state") == "active"

    def refresh_network(self, name):
        path, original, config, active = self.editable_config(name)
        role = config.get("role")
        if role == "server":
            port = number(str(mapping(config.get("listen")).get("addr", "")).rsplit(":", 1)[-1],
                          1, 65535, "پورت شنود")
            target = None
        elif role == "client":
            port = 0
            target = ipv4(str(mapping(config.get("server")).get("addr", "")).rsplit(":", 1)[0])
        else:
            raise Problem("نقش این تونل مشخص نیست.")
        detected = ("eth0", "192.0.2.10", "02:00:00:00:00:01") if self.demo else network(target)
        interface, address, mac = detected
        if self.demo:
            self.operations.remember(name, self.full_config(name)["yaml"])
            self.demo_backups[name] = deepcopy(config)
        settings = mapping(config.get("network"))
        settings["interface"] = interface
        settings["ipv4"] = {**mapping(settings.get("ipv4")), "addr": f"{address}:{port}", "router_mac": mac}
        config["network"] = settings
        if not self.demo:
            self.save_config(name, path, original, config, active)

    def save_config(self, name, path, original, config, active, text=None):
        self.operations.remember(name, original)
        backup = self.backup_path(name)
        backup.parent.mkdir(mode=0o700, exist_ok=True)
        updated = text if text is not None else yaml.safe_dump(config, sort_keys=False)
        point = {"updated": hashlib.sha256(updated.encode()).hexdigest(), "original": original}
        old_point = backup.read_text() if backup.is_file() else None
        atomic(backup, json.dumps(point), 0o600)
        try:
            atomic(path, updated, 0o600)
            self.apply_change(name, path, original, active)
        except (OSError, Problem, subprocess.SubprocessError):
            if old_point is None:
                backup.unlink(missing_ok=True)
            else:
                atomic(backup, old_point, 0o600)
            raise

    def archive_path(self, name):
        return STATE / "archives" / f"{name}.json"

    def archives(self):
        if self.demo:
            return sorted(self.demo_archive)
        return sorted(path.stem for path in (STATE / "archives").glob("*.json")
                      if re.fullmatch(EXISTING_NAME, path.stem))

    def archive(self, name, confirmation):
        if confirmation != name:
            raise Problem("برای تأیید حذف، نام دقیق تونل را وارد کنید.")
        row = next((row for row in self.inventory() if row["name"] == name), {})
        if not row.get("archivable") or name in self.archives():
            raise Problem("این سرویس برای حذف قابل تأیید نیست یا قبلاً آرشیو شده است.")
        if self.demo:
            self.demo_archive[name] = (self.samples.pop(name), self.demo_backups.pop(name, None))
            return
        config, fragment, archive = CONFIG / f"{name}.yaml", UNITS / unit(name), self.archive_path(name)
        standalone = systemctl("show", "-p", "ExecStart", "--value", "paqet.service", required=False)
        standalone_config = service_config_path(standalone.stdout)
        if standalone_config and standalone_config.is_absolute() and standalone_config.resolve() == config.resolve():
            raise Problem("سرویس paqet.service هم از فایل تنظیمات این تونل استفاده می‌کند.")
        record = {"config": config.read_text(), "unit": fragment.read_text(),
                  "enabled": row["enabled"], "active": row["state"] == "active"}
        archive.parent.mkdir(mode=0o700, exist_ok=True)
        atomic(archive, json.dumps(record), 0o600)
        removed = []
        try:
            systemctl("disable", "--now", unit(name))
            for path, key, mode in ((fragment, "unit", 0o644), (config, "config", 0o600)):
                path.unlink()
                removed.append((path, key, mode))
            systemctl("daemon-reload")
        except (OSError, Problem, subprocess.SubprocessError):
            for path, key, mode in removed:
                atomic(path, record[key], mode)
            systemctl("daemon-reload")
            self.restore_service_state(name, record)
            archive.unlink()
            raise

    @staticmethod
    def restore_service_state(name, record):
        if record["enabled"]:
            systemctl("enable", unit(name))
        if record["active"]:
            systemctl("start", unit(name))

    def unarchive(self, name):
        if name not in self.archives():
            raise Problem("تونل در آرشیو پیدا نشد.")
        if self.demo:
            sample, backup = self.demo_archive.pop(name)
            self.samples[name] = sample
            if backup is not None:
                self.demo_backups[name] = backup
            return
        config, fragment, archive = CONFIG / f"{name}.yaml", UNITS / unit(name), self.archive_path(name)
        if any(os.path.lexists(path) for path in (config, config.with_suffix(".yml"), fragment)) or name in self.names():
            raise Problem("هم‌اکنون فایل یا سرویس دیگری با همین نام وجود دارد.")
        record = json.loads(archive.read_text())
        try:
            data = mapping(yaml.safe_load(record["config"]))
        except yaml.YAMLError:
            data = {}
        if config_role(data)[0] == "server":
            port = str(mapping(data.get("listen")).get("addr", "")).rsplit(":", 1)[-1]
            if port == str(self.panel_port) or any(row["role"] == "server" and
                    row["endpoint"].rsplit(":", 1)[-1] == port for row in self.inventory()):
                raise Problem("پورت تونل آرشیوشده اکنون در استفاده است.")
        CONFIG.mkdir(mode=0o755, exist_ok=True)
        created = []
        try:
            for path, key, mode in ((config, "config", 0o600), (fragment, "unit", 0o644)):
                atomic(path, record[key], mode)
                created.append(path)
            systemctl("daemon-reload")
            self.restore_service_state(name, record)
            if record["active"]:
                time.sleep(0.7)
                systemctl("is-active", "--quiet", unit(name))
            archive.unlink()
        except (OSError, Problem, subprocess.SubprocessError):
            if fragment in created:
                systemctl("disable", "--now", unit(name), required=False)
            for path in reversed(created):
                path.unlink(missing_ok=True)
            systemctl("daemon-reload", required=False)
            raise

    def hosts(self):
        if self.demo:
            return self.demo_hosts
        try:
            return json.loads((STATE / "hosts.json").read_text())
        except FileNotFoundError:
            return []

    def change_hosts(self, data):
        address = ipv4(data.get("address"))
        port = number(data.get("port"), 1, 65535, "پورت")
        hosts = self.hosts()
        keys = {(address, port)}
        action = data.get("action")
        if action == "save" and isinstance(data.get("previous"), dict):
            previous = data["previous"]
            keys.add((ipv4(previous.get("address")), number(previous.get("port"), 1, 65535, "پورت")))
        updated = [host for host in hosts if (host["address"], host["port"]) not in keys]
        if action == "save":
            label, region = data.get("label"), data.get("region")
            if not isinstance(label, str) or not 1 <= len(label.strip()) <= 64 or region not in ("", "ir", "foreign"):
                raise Problem("نام یا موقعیت سرور معتبر نیست.")
            if len(updated) >= 50:
                raise Problem("حداکثر ۵۰ سرور قابل ثبت است.")
            updated.append({"address": address, "port": port, "label": label.strip(), "region": region})
        elif action != "remove":
            raise Problem("عملیات دفتر سرورها معتبر نیست.")
        if self.demo:
            self.demo_hosts = updated
        else:
            atomic(STATE / "hosts.json", json.dumps(updated), 0o600)
        return updated

    def host_report(self):
        if self.demo:
            return {"kernel": "Linux · demo", "uptime": 104520, "disk": [16000000000, 5000000000],
                    "interfaces": [{"name": "eth0", "state": "UP", "mtu": 1500, "addresses": ["192.0.2.10/24"]}],
                    "routes": [{"destination": "default", "gateway": "192.0.2.1", "interface": "eth0", "metric": 100}],
                    "listeners": [["tcp", "0.0.0.0:8765"], ["udp", "192.0.2.10:5353"]], "dns": ["192.0.2.53"]}
        interfaces = json.loads(run("ip", "-j", "address", "show").stdout)
        routes = json.loads(run("ip", "-j", "route", "show", "table", "main").stdout)
        sockets = run("ss", "-H", "-lntu").stdout.splitlines()
        disk = shutil.disk_usage("/")
        dns = Path("/etc/resolv.conf").read_text().splitlines()
        return {"kernel": os.uname().release, "uptime": int(float(Path("/proc/uptime").read_text().split()[0])),
                "disk": [disk.total, disk.used],
                "interfaces": [{"name": item["ifname"], "state": item.get("operstate", ""), "mtu": item.get("mtu"),
                                "addresses": [f"{addr['local']}/{addr['prefixlen']}" for addr in item.get("addr_info", [])
                                              if "local" in addr and "prefixlen" in addr]} for item in interfaces[:128]],
                "routes": [{"destination": item.get("dst", "default"), "gateway": item.get("gateway", ""),
                            "interface": item.get("dev", ""), "metric": item.get("metric", "")} for item in routes[:256]],
                "listeners": [[cols[0], cols[4]] for cols in (line.split() for line in sockets[:256])
                              if len(cols) >= 6],
                "dns": [line.split()[1] for line in dns if line.startswith("nameserver ") and len(line.split()) >= 2]}

    def diagnose(self, name):
        row = next((row for row in self.inventory() if row["name"] == name), {})
        if row.get("role") != "client":
            raise Problem("بررسی مسیر برای تونل کلاینت است.")
        target = ipv4(row["endpoint"].rsplit(":", 1)[0])
        if self.demo:
            return {"target": target, "interface": "eth0", "local": "192.0.2.10",
                    "next_hop": "192.0.2.1", "matches": None}
        route = route_to(target)
        configured = row["local"].rsplit(":", 1)[0]
        route["matches"] = (route["interface"] == row["interface"] and route["local"] == configured
                            if row["interface"] and configured else None)
        return {"target": target, **route}

    def probe_core(self, name):
        config = self.parse_configuration(self.full_config(name)["yaml"])
        if config.get("role") != "client":
            raise Problem("آزمون پاسخ KCP برای تونل کلاینت است.")
        if self.demo:
            return {"demo": True}
        if not os.access(PROBE_CORE, os.X_OK):
            raise Problem("ابزار آزمون هسته نصب نشده است.")
        report = run(str(PROBE_CORE), "health", "-c", str(self.editor_path(name)), "--count", "3",
                     "--timeout-ms", "1500", required=False)
        if report.returncode:
            raise Problem("آزمون هسته شروع نشد. تنظیمات شبکهٔ کلاینت را بررسی کنید.")
        result = json.loads(report.stdout)
        if not isinstance(result, dict) or result.get("schema") != "paqet-health-v1":
            raise Problem("فرمت پاسخ ابزار آزمون معتبر نیست.")
        samples = result.get("samples")
        if not isinstance(samples, list) or len(samples) != 3 or not all(isinstance(item, dict) for item in samples):
            raise Problem("نمونه‌های آزمون هسته معتبر نیستند.")
        return {"samples": samples}

    def probe_forward(self, name, listen):
        row = next((row for row in self.inventory() if row["name"] == name), {})
        if row.get("role") != "client" or row.get("state") != "active" or not any(
                rule["listen"] == listen and rule["protocol"] == "tcp" for rule in row.get("forwards", [])):
            raise Problem("یک ورودی TCP ثبت‌شده روی کلاینت فعال انتخاب کنید.")
        host, port = endpoint(listen, True)
        host = {"": "127.0.0.1", "0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
        if self.demo:
            return {"status": "demo"}
        if not ipaddress.ip_address(host).is_loopback:
            interfaces = json.loads(run("ip", "-j", "address", "show").stdout)
            if not any(addr.get("local") == host for item in interfaces for addr in item.get("addr_info", [])):
                raise Problem("آدرس شنود روی رابط‌های این میزبان وجود ندارد.")
        # Only contact a configured local listener. A completed TLS handshake proves
        # an application replied through the forward; certificate identity is outside this test.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        started = time.monotonic()
        try:
            with socket.create_connection((host, port), timeout=2) as connection:
                try:
                    with context.wrap_socket(connection) as stream:
                        return {"status": "tls", "version": stream.version(),
                                "ms": round((time.monotonic() - started) * 1000)}
                except OSError:
                    return {"status": "tcp"}
        except OSError:
            return {"status": "unreachable"}

    def logs(self, name):
        if self.demo:
            return f"[DEMO] paqet-{name}.service\n[DEMO] Journal output is simulated.\n"
        return run("journalctl", "--no-pager", "-q", "-o", "short-iso",
                   "-n", "120", "-u", unit(name)).stdout[-CAP:]

    def health(self):
        rows = self.inventory()
        for row in rows:
            row["editable"] = self.demo or bool(row.get("config_file"))
            row["backup"] = row["editable"] and self.has_backup(row["name"])
        return {"host": "paqet-demo" if self.demo else socket.gethostname(),
                "core": self.demo or os.access(CORE, os.X_OK), "demo": self.demo,
                "core_probe": self.demo or os.access(PROBE_CORE, os.X_OK),
                "tunnels": rows, "region": self.region(), "topology": coordinates(rows),
                "sample": {} if self.demo else system_sample()}


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

    def send_data(self, status, data, content_type, cookie=None, cache="no-store"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
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
            elif method == "GET" and path in FONTS:
                self.send_data(200, (STATIC / "fonts" / FONTS[path]).read_bytes(), "font/woff2",
                               cache="public, max-age=2592000, immutable")
            elif method == "GET" and path == "/api/session":
                self.answer(200, {"authenticated": self.authenticated(), "demo": manager.demo,
                                  "features": {"receiver_acme": True, "self_update": True}})
            elif method == "POST" and path == "/api/login":
                self.login()
            elif path.startswith("/api/") and not self.authenticated():
                self.answer(401, {"error": "ابتدا وارد پنل شوید."})
            elif method == "POST" and path == "/api/logout":
                self.server.sessions.pop(self.session(), None)
                self.answer(200, {}, "paqet_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0")
            elif method == "GET" and path == "/api/updates":
                self.answer(200, self.server.updates.view())
            elif method == "POST" and path == "/api/updates":
                data = self.payload()
                action = data.get("action")
                if action in ("check", "check-and-install"):
                    self.server.updates.start_check(install=action == "check-and-install")
                elif action == "apply":
                    self.server.updates.apply(data.get("revision"))
                else:
                    raise Problem("عملیات به‌روزرسانی معتبر نیست.")
                self.answer(202, self.server.updates.view())
            elif method == "GET" and path == "/api/overview":
                self.answer(200, {**manager.health(), "quic": bool(self.server.relay.quic) or manager.demo})
            elif method == "GET" and path == "/api/relays":
                self.answer(200, self.server.relay.call("view"))
            elif method == "POST" and path == "/api/relays":
                data = self.payload()
                action = data.get("action")
                if action == "save" and data.get("issue_certificate") is True:
                    result = self.server.relay.call("save_with_certificate", data)
                elif action in ("save", "remove"):
                    result = self.server.relay.call("change", action, data)
                elif action == "select":
                    result = self.server.relay.call("select", data.get("name"), data.get("route"))
                elif action == "compare":
                    result = self.server.relay.call("start_comparison", data.get("name"))
                elif action == "profile":
                    result = self.server.relay.call("peer", data.get("name"))
                else:
                    raise Problem("عملیات مسیر معتبر نیست.")
                self.answer(202 if result and result.get("certificate_pending") else 200, result or {})
            elif method == "POST" and path == "/api/recovery":
                from recovery import recover
                self.answer(200, recover(manager, self.payload()))
            elif method == "GET" and path == "/api/host-report":
                self.answer(200, manager.host_report())
            elif method == "GET" and path == "/api/archives":
                self.answer(200, {"names": manager.archives()})
            elif method == "GET" and path == "/api/hosts":
                self.answer(200, {"hosts": manager.hosts()})
            elif method == "POST" and path == "/api/hosts":
                self.answer(200, {"hosts": manager.change_hosts(self.payload())})
            elif method == "POST" and (match := re.fullmatch(rf"/api/archives/({EXISTING_NAME})/restore", path)):
                manager.unarchive(match.group(1))
                logging.info("Restored archived tunnel: %s", unit(match.group(1)))
                self.answer(200, {})
            elif method == "POST" and path == "/api/region":
                manager.set_region(self.payload().get("region"))
                self.answer(200, {})
            elif method == "POST" and path == "/api/tunnels":
                created = manager.create(self.payload())
                logging.info("Provisioned %s", unit(created["name"]))
                self.answer(201, created)
            elif (match := re.fullmatch(rf"/api/tunnels/({EXISTING_NAME})/(logs|action|tune|restore|diagnose|archive|network|config|pair|forwards|probe|history|rotation|preflight|diagnostic|core-probe)", path)):
                name, operation = match.groups()
                if operation not in ("config", "forwards", "pair", "restore", "history", "diagnostic", "core-probe") and name not in manager.names():
                    self.answer(404, {"error": "تونل پیدا نشد."})
                elif operation == "config" and method == "GET":
                    self.answer(200, manager.full_config(name))
                elif operation == "history":
                    self.answer(200, manager.operations.config_view(name, self.payload() if method == "POST" else None))
                elif operation == "rotation" and method == "POST":
                    self.answer(201, manager.operations.rotation(name, self.payload()))
                elif operation == "core-probe" and method == "POST":
                    self.payload()
                    self.answer(200, manager.probe_core(name))
                elif operation == "preflight" and method == "GET":
                    self.answer(200, manager.operations.preflight(name))
                elif operation == "diagnostic" and method == "GET":
                    self.answer(200, manager.operations.diagnostic(name))
                elif operation == "forwards" and method == "POST":
                    edit = self.payload()
                    current = manager.full_config(name)
                    config = manager.parse_configuration(current["yaml"])
                    if config.get("role") != "client":
                        raise Problem("انتقال پورت روی کلاینت تعریف می‌شود.")
                    rules = edit.get("rules")
                    if not isinstance(rules, list) or len(rules) > 256:
                        raise Problem("قوانین انتقال معتبر نیستند.")
                    config["forward"] = rules
                    manager.replace_config(name, {"revision": edit.get("revision"), "yaml": yaml.safe_dump(config, sort_keys=False)})
                    self.answer(200, {})
                elif operation == "config" and method == "POST":
                    manager.replace_config(name, self.payload())
                    self.answer(200, {})
                elif operation == "pair" and method == "GET":
                    config = mapping(yaml.safe_load(manager.full_config(name)["yaml"]))
                    if config.get("role") != "server":
                        raise Problem("فایل اتصال از تونل سرور صادر می‌شود.")
                    self.answer(200, {"format": "paqet-peer-v1", "port": str(mapping(config.get("listen")).get("addr", "")).rsplit(":", 1)[-1],
                                      "transport": config.get("transport")})
                elif method == "GET" and operation == "logs":
                    self.answer(200, {"logs": manager.logs(name)})
                elif method == "POST" and operation == "probe":
                    self.answer(200, manager.probe_forward(name, self.payload().get("listen")))
                elif method == "GET" and operation == "diagnose":
                    self.answer(200, manager.diagnose(name))
                elif method == "POST" and operation == "action":
                    action = self.payload().get("action")
                    manager.action(name, action)
                    logging.info("Service action: %s %s", action, unit(name))
                    self.answer(200, {})
                elif method == "POST" and operation == "tune":
                    manager.tune(name, self.payload())
                    logging.info("Updated KCP settings: %s", unit(name))
                    self.answer(200, {})
                elif method == "POST" and operation == "network":
                    manager.refresh_network(name)
                    logging.info("Refreshed network configuration: %s", unit(name))
                    self.answer(200, {})
                elif method == "POST" and operation == "archive":
                    manager.archive(name, self.payload().get("confirmation"))
                    logging.info("Archived tunnel: %s", unit(name))
                    self.answer(200, {})
                elif method == "POST" and operation == "restore":
                    manager.restore(name)
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
    sys.modules.setdefault("panel", sys.modules[__name__])
    from relay import Relay
    from updates import Updates

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
        server.relay = Relay(STATE, options.demo, port)
        server.updates = Updates(STATE, options.demo)
        server.token_hash = hashlib.sha256(token.encode()).digest()
        server.sessions, server.attempts = {}, []
        print(f"Listening on {bind}:{port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()

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
STATE = Path("/etc/paqet-panel")
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
                for rule in forwards[:64] if isinstance(rule, dict)] if isinstance(forwards, list) else []
    return {"name": name, "role": role, "evidence": evidence, "state": state, "enabled": enabled,
            "endpoint": str(endpoint.get("addr", "")), "source": source, "forwards": forwards,
            "interface": str(network.get("interface", "")), "local": str(mapping(network.get("ipv4")).get("addr", "")),
            "mode": str(kcp.get("mode", "")), "mtu": str(kcp.get("mtu", "")), "conn": str(transport.get("conn", "")),
            "restarts": values.get("NRestarts", ""), "pid": values.get("MainPID", ""),
            "result": values.get("Result", ""), "since": values.get("ActiveEnterTimestamp", ""),
            "tunable": bool(kcp) and evidence == "explicit" and source == "default" and state != "unregistered"}


class Manager:
    def __init__(self, demo, panel_port=8765):
        self.demo = demo
        self.panel_port = panel_port
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
                          "transport": {"conn": 1, "kcp": {"mode": "fast", "mtu": 1350}}}
                self.samples[name] = (config, state, state != "inactive")

    def names(self):
        if self.demo:
            return sorted(self.samples)
        output = systemctl("list-unit-files", "paqet-*.service", "--no-legend").stdout
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
                rows[name]["archivable"] = (
                    source == "default" and default.is_file() and not default.is_symlink()
                    and values.get("FragmentPath") == str(fragment) and fragment.is_file()
                    and not fragment.is_symlink() and not values.get("DropInPaths")
                    and values.get("UnitFileState") in ("enabled", "disabled")
                    and rows[name]["state"] in ("active", "inactive", "failed"))
        references = Counter(config_references.values())
        for name, row in rows.items():
            if row["archivable"] and references[config_references[name]] != 1:
                row["archivable"] = False
        for path in sorted(CONFIG.glob("*.y*ml")):
            if path.suffix in (".yaml", ".yml") and re.fullmatch(EXISTING_NAME, path.stem) and path.stem not in rows:
                config = self.config(path.stem, path)
                if "role" in config or config_role(config)[0] != "unknown":
                    rows[path.stem] = summary(path.stem, config, "unregistered", False, source="file")
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
            config, status, enabled = self.samples[name]
            config = self.demo_backups.pop(name)
            self.samples[name] = (config, status, enabled)
            return
        row = next((row for row in self.inventory() if row["name"] == name), {})
        if not row.get("tunable"):
            raise Problem("فایل کنونی سرویس برای بازیابی قابل تأیید نیست.")
        backup = self.backup_path(name)
        path = CONFIG / f"{name}.yaml"
        if path.is_symlink():
            raise Problem("بازیابی فایل پیوندی مجاز نیست.")
        original = path.read_text()
        point = json.loads(backup.read_text())
        if hashlib.sha256(original.encode()).hexdigest() != point.get("updated"):
            raise Problem("تنظیمات پس از ساخت نقطهٔ بازیابی تغییر کرده است.")
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
        except (Problem, subprocess.SubprocessError):
            atomic(path, original, 0o600)
            systemctl("restart", unit(name), required=False)
            raise Problem("اعمال تنظیمات موفق نبود. فایل قبلی بازیابی شد.")

    def create(self, data):
        name, port, config = validate(data)
        result = {"name": name}
        if config["role"] == "server":
            result["key"] = config["transport"]["kcp"]["key"]
        if self.demo:
            if name in self.samples or name in self.demo_archive:
                raise Problem("این نام قبلاً ثبت شده است.")
            self.samples[name] = (config, "active", True)
            return result
        if not os.access(CORE, os.X_OK):
            raise Problem("هسته Paqet نصب نشده است.")
        config_path = CONFIG / f"{name}.yaml"
        unit_path = UNITS / unit(name)
        names = self.names()
        if name in self.archives() or os.path.lexists(config_path.with_suffix(".yml")) or os.path.lexists(config_path) or os.path.lexists(unit_path) or name in names:
            raise Problem("این نام قبلاً در تنظیمات یا systemd ثبت شده است.")
        server = config["role"] == "server"
        if server:
            if port == self.panel_port:
                raise Problem("این پورت برای پنل رزرو شده است.")
            for other in self.inventory():
                listen = other["endpoint"]
                if other["role"] == "server" and listen.rsplit(":", 1)[-1] == str(port):
                    raise Problem("این پورت قبلاً برای یک تونل سرور استفاده شده است.")
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
        path, original, config, active = self.editable_config(name)
        transport = mapping(config.get("transport"))
        kcp = mapping(transport.get("kcp"))
        if not kcp or config.get("role") not in ("server", "client"):
            raise Problem("پارامترهای KCP این سرویس پیدا نشد.")
        if kcp.get("mode") == "manual" and mode:
            raise Problem("برای تنظیمات دستی، حالت فعلی را نگه دارید.")
        if self.demo:
            self.demo_backups[name] = deepcopy(config)
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
            self.demo_backups[name] = deepcopy(config)
        settings = mapping(config.get("network"))
        settings["interface"] = interface
        settings["ipv4"] = {**mapping(settings.get("ipv4")), "addr": f"{address}:{port}", "router_mac": mac}
        config["network"] = settings
        if not self.demo:
            self.save_config(name, path, original, config, active)

    def save_config(self, name, path, original, config, active):
        backup = self.backup_path(name)
        backup.parent.mkdir(mode=0o700, exist_ok=True)
        updated = yaml.safe_dump(config, sort_keys=False)
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

    def logs(self, name):
        if self.demo:
            return f"[DEMO] paqet-{name}.service\n[DEMO] Journal output is simulated.\n"
        return run("journalctl", "--no-pager", "-q", "-o", "short-iso",
                   "-n", "120", "-u", unit(name)).stdout[-CAP:]

    def health(self):
        rows = self.inventory()
        for row in rows:
            row["backup"] = row["tunable"] and self.has_backup(row["name"])
        return {"host": "paqet-demo" if self.demo else socket.gethostname(),
                "core": self.demo or os.access(CORE, os.X_OK), "demo": self.demo,
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
                self.answer(200, manager.health())
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
            elif (match := re.fullmatch(rf"/api/tunnels/({EXISTING_NAME})/(logs|action|tune|restore|diagnose|archive|network)", path)):
                name, operation = match.groups()
                if name not in manager.names():
                    self.answer(404, {"error": "تونل پیدا نشد."})
                elif method == "GET" and operation == "logs":
                    self.answer(200, {"logs": manager.logs(name)})
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

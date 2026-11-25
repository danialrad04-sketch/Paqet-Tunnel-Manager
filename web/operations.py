"""Local version history and operator-mediated Paqet pairing."""
from copy import deepcopy
import difflib
import hashlib
import json
import re
import secrets
import time
from datetime import datetime, timezone

import yaml

import panel as p


HISTORY_LIMIT = 12
GROUP = r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,47}"


def revision(text):
    return hashlib.sha256(text.encode()).hexdigest()


def clean(value):
    """Redact credentials before rendering a configuration outside the editor."""
    if isinstance(value, dict):
        return {key: ("[redacted]" if re.search(
            r"key|secret|token|pass|user|credential|auth", str(key), re.I) else clean(item))
                for key, item in value.items()}
    if isinstance(value, list):
        return [clean(item) for item in value]
    return value


class Operations:
    def __init__(self, manager):
        self.manager = manager
        self.demo = manager.demo
        self.memory = {}

    def history(self, name):
        if self.demo:
            return self.memory.get(name, [])
        try:
            return json.loads(self.history_path(name).read_text())
        except FileNotFoundError:
            return []

    @staticmethod
    def history_path(name):
        return p.STATE / "history" / f"{name}.json"

    def remember(self, name, text, label="edit", group=""):
        if not isinstance(text, str) or len(text.encode()) > 262144:
            return
        previous = self.history(name)
        if previous and previous[0]["revision"] == revision(text) and previous[0]["group"] == group:
            return
        record = {"time": int(time.time()), "label": label, "group": group, "revision": revision(text), "yaml": text}
        updated = [record, *previous][:HISTORY_LIMIT]
        if self.demo:
            self.memory[name] = updated
        else:
            path = self.history_path(name)
            path.parent.mkdir(mode=0o700, exist_ok=True)
            p.atomic(path, json.dumps(updated), 0o600)

    @staticmethod
    def group(data):
        group = data.get("group")
        if not isinstance(group, str) or not re.fullmatch(GROUP, group):
            raise p.Problem("شناسهٔ مشترک عملیات معتبر نیست.")
        return group

    def config_view(self, name, data):
        current = self.manager.full_config(name)
        entries = self.history(name)
        if data is None:
            return {"revision": current["revision"], "entries": [
                {"id": index, **{k: v for k, v in entry.items() if k != "yaml"}}
                for index, entry in enumerate(entries)]}
        action = data.get("action")
        if action == "checkpoint":
            self.remember(name, current["yaml"], "checkpoint", self.group(data))
            return {}
        if action == "apply_group":
            group = self.group(data)
            if current["revision"] != data.get("revision"):
                raise p.Problem("تنظیمات فعلی تغییر کرده است.")
            self.remember(name, current["yaml"], "checkpoint", group)
            self.manager.replace_config(name, data)
            return {}
        if action == "receipt":
            group = self.group(data)
            checkpoint = next((entry for entry in reversed(entries) if entry["group"] == group), None)
            if not checkpoint:
                raise p.Problem("برای این شناسه نقطهٔ بازیابی ثبت نشده است.")
            status = "at_checkpoint" if checkpoint["revision"] == current["revision"] else "changed"
            role = self.manager.parse_configuration(current["yaml"]).get("role")
            return {"format": "paqet-checkpoint-v1", "group": group, "role": role, "status": status,
                    "revision": current["revision"], "checkpoint": checkpoint["revision"]}
        if action == "preview":
            new = self.manager.parse_configuration(data.get("yaml"))
            self.manager.check_configuration(name, new)
            old = clean(self.manager.parse_configuration(current["yaml"]))
            return {"diff": self.diff(old, clean(new))}
        index = p.number(data.get("id"), 0, HISTORY_LIMIT - 1, "نسخه")
        if index >= len(entries) or entries[index]["revision"] != data.get("point"):
            raise p.Problem("فهرست نسخه‌ها تغییر کرد. آن را دوباره باز کنید.")
        point = entries[index]
        if action == "diff":
            old = clean(self.manager.parse_configuration(current["yaml"]))
            new = clean(self.manager.parse_configuration(point["yaml"]))
            return {"diff": self.diff(old, new)}
        if action == "restore":
            self.manager.replace_config(name, {"revision": data.get("revision"), "yaml": point["yaml"]})
            return {}
        raise p.Problem("عملیات تاریخچه معتبر نیست.")

    @staticmethod
    def diff(old, new):
        previous, upcoming = (yaml.safe_dump(item, sort_keys=True).splitlines() for item in (old, new))
        return "\n".join(difflib.unified_diff(previous, upcoming, fromfile="current", tofile="selected", lineterm=""))[:40000]

    def rotation(self, original, data):
        """Create a fresh standby without restarting the existing pair."""
        group = self.group(data)
        manager = self.manager
        current = manager.full_config(original)
        if data.get("revision") != current["revision"]:
            raise p.Problem("تنظیمات اصلی تغییر کرده است. صفحه را تازه کنید.")
        config = deepcopy(manager.parse_configuration(current["yaml"]))
        name = data.get("name")
        if not isinstance(name, str) or not re.fullmatch(p.NAME, name):
            raise p.Problem("نام تونل آماده‌به‌کار معتبر نیست.")
        port = p.number(data.get("port"), 1024, 65535, "پورت تازه")
        transport = config["transport"]
        if config["role"] == "server":
            transport["kcp"]["key"] = secrets.token_urlsafe(24)
            host, old_port = p.endpoint(config["listen"]["addr"], True)
            if port == old_port:
                raise p.Problem("پورت سرور آماده‌به‌کار باید تازه باشد.")
            config["listen"]["addr"] = address(host, port)
            local = p.mapping(p.mapping(config.get("network")).get("ipv4"))
            if local.get("addr"):
                ip, _ = p.endpoint(local["addr"], True)
                local["addr"] = address(ip, port)
            v6 = p.mapping(p.mapping(config.get("network")).get("ipv6"))
            if v6.get("addr"):
                ip, _ = p.endpoint(v6["addr"], True)
                v6["addr"] = address(ip, port)
            profile = {"format": "paqet-rotation-v1", "group": group, "port": port,
                       "transport": transport}
        else:
            profile = data.get("profile")
            if not isinstance(profile, dict) or profile.get("format") != "paqet-rotation-v1" or profile.get("group") != group:
                raise p.Problem("فایل گردش کلید و شناسهٔ مشترک را بررسی کنید.")
            old_host, _ = p.endpoint(config["server"]["addr"], False)
            server_port = p.number(profile.get("port"), 1024, 65535, "پورت تازهٔ سرور")
            selected = next((rule for rule in config.get("forward") or []
                             if rule["listen"] == data.get("forward") and rule["protocol"] == "tcp"), None)
            if not selected:
                raise p.Problem("یک ورودی TCP از تونل اصلی انتخاب کنید.")
            config["server"]["addr"] = address(old_host, server_port)
            config["transport"] = profile.get("transport")
            config.pop("socks5", None)
            config["forward"] = [{**selected, "listen": f"127.0.0.1:{port}"}]
        # Record both original revisions under the same operator-supplied ID.
        self.remember(original, current["yaml"], "checkpoint", group)
        manager.create({"name": name, "yaml": yaml.safe_dump(config, sort_keys=False)})
        return {"name": name, **({"profile": profile} if config["role"] == "server" else
                                {"listen": f"127.0.0.1:{port}"})}

    def preflight(self, name):
        manager = self.manager
        row = next((row for row in manager.inventory() if row["name"] == name), {})
        if row.get("role") != "client":
            raise p.Problem("پیش‌بررسی مسیر برای سمت کلاینت است.")
        route = manager.diagnose(name)
        mtu = row["mtu"]
        report = {"route": route, "configured_mtu": mtu, "interface_mtu": None, "df_test": "unavailable"}
        if self.demo:
            return {**report, "interface_mtu": 1500, "df_test": "demo"}
        links = json.loads(p.run("ip", "-j", "link", "show", "dev", route["interface"]).stdout)
        report["interface_mtu"] = links[0].get("mtu") if links else None
        if mtu.isdecimal() and 50 <= int(mtu) <= 1500:
            # Match an IPv4 packet of this size, including the 20-byte IPv4 and 8-byte ICMP headers.
            result = p.run("ping", "-4", "-n", "-M", "do", "-W", "1", "-c", "1", "-s", str(int(mtu) - 28),
                           route["target"], required=False)
            if result.returncode == 0:
                report["df_test"] = "ok"
            elif re.search(r"message too long|frag needed|mtu[= ]", result.stdout + result.stderr, re.I):
                report["df_test"] = "too_large"
            else:
                report["df_test"] = "inconclusive"
        return report

    def diagnostic(self, name):
        manager = self.manager
        row = next((row for row in manager.inventory() if row["name"] == name), None)
        if not row:
            raise p.Problem("تونل پیدا نشد.")
        flags = {"message too large": "packet_too_large", "message too long": "packet_too_large",
                 "address already in use": "address_in_use", "connection refused": "connection_refused",
                 "permission denied": "permission_denied", "timed out": "timeout"}
        journal = manager.logs(name).lower() if name in manager.names() else ""
        core = p.run(str(p.CORE), "version", required=False).stdout if not self.demo and p.CORE.is_file() else ""
        version = re.search(r"\bv[0-9]+\.[0-9]+\.[0-9]+[a-zA-Z0-9.-]*", core)
        return {"format": "paqet-diagnostic-v1", "created": datetime.now(timezone.utc).isoformat(),
                "version": version.group() if version else None, "role": row["role"], "state": row["state"],
                "mode": row["mode"], "mtu": row["mtu"], "conn": row["conn"], "restarts": row["restarts"],
                "forwards": len(row["forwards"]), "demo": self.demo,
                "warnings": sorted({value for label, value in flags.items() if label in journal})}


def address(host, port):
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"

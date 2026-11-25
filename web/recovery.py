"""Encrypted, portable recovery of a Paqet IPv4 client."""
from base64 import b64decode, b64encode
import binascii
from datetime import datetime, timezone
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import socket

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import yaml

import panel as p


FORMAT = "paqet-client-recovery-v1"
MAX_CONFIG = 262144


def derive(password, salt):
    if not isinstance(password, str) or not 16 <= len(password) <= 128:
        raise p.Problem("عبارت بازیابی باید بین ۱۶ تا ۱۲۸ نویسه باشد.")
    return hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=1, dklen=32, maxmem=64 * 1024**2)


def encode(data):
    return b64encode(data).decode("ascii")


def pack(name, text, password):
    payload = json.dumps({"name": name, "yaml": text, "created": datetime.now(timezone.utc).isoformat()},
                         ensure_ascii=False).encode()
    if len(payload) > MAX_CONFIG:
        raise p.Problem("حجم تنظیمات برای فایل بازیابی زیاد است.")
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    blob = AESGCM(derive(password, salt)).encrypt(nonce, payload, FORMAT.encode())
    return {"format": FORMAT, "salt": encode(salt), "nonce": encode(nonce), "data": encode(blob)}


def unpack(bundle, password):
    if not isinstance(bundle, dict) or bundle.get("format") != FORMAT:
        raise p.Problem("فرمت فایل بازیابی معتبر نیست.")
    try:
        fields = ("salt", "nonce", "data")
        if any(not isinstance(bundle.get(field), str) for field in fields):
            raise ValueError
        salt, nonce, encrypted = (b64decode(bundle[field], validate=True) for field in fields)
        if len(salt) != 16 or len(nonce) != 12 or not 16 < len(encrypted) <= MAX_CONFIG + 16:
            raise ValueError
    except (binascii.Error, ValueError) as error:
        raise p.Problem("ساختار فایل بازیابی معتبر نیست.") from error
    try:
        payload = AESGCM(derive(password, salt)).decrypt(nonce, encrypted, FORMAT.encode())
        return json.loads(payload)
    except (InvalidTag, ValueError, UnicodeError) as error:
        raise p.Problem("عبارت بازیابی اشتباه است یا فایل تغییر کرده است.") from error


def remote_ipv4(config):
    if config.get("role") != "client":
        raise p.Problem("فایل بازیابی برای تونل IPv4 سمت کلاینت است.")
    if p.mapping(config.get("network")).get("ipv6"):
        raise p.Problem("بازیابی خودکار این فایل فقط برای پیکربندی شبکهٔ IPv4 در دسترس است.")
    remote = p.mapping(config.get("server")).get("addr")
    host, _ = p.endpoint(remote, False)
    return p.ipv4(host)


def listeners(config, previous, address):
    rows = []
    for group in ("forward", "socks5"):
        for rule in config.get(group) or []:
            original = rule["listen"]
            host, port = p.endpoint(original, True)
            if previous and host == previous and host != address:
                host = address
                rule["listen"] = f"{address}:{port}"
            protocol = rule.get("protocol") if group == "forward" else "tcp"
            rows.append({"listen": rule["listen"], "original": original, "host": host, "port": port,
                         "protocol": protocol, "target": rule.get("target"), "type": group})
    return rows


def check_listeners(rows):
    for row in rows:
        host, port = row["host"], row["port"]
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        kind = socket.SOCK_DGRAM if row["protocol"] == "udp" else socket.SOCK_STREAM
        try:
            with socket.socket(family, kind) as listener:
                listener.bind((host, port))
        except OSError as error:
            raise p.Problem(f"ورودی {row['listen']} ({row['protocol'].upper()}) روی میزبان جدید آزاد یا قابل شنود نیست.") from error


def recover(manager, data):
    action = data.get("action")
    password = data.get("password")
    name = data.get("name")
    if action == "export":
        if not isinstance(name, str) or not re.fullmatch(p.EXISTING_NAME, name):
            raise p.Problem("نام تونل معتبر نیست.")
        text = manager.full_config(name)["yaml"]
        config = manager.parse_configuration(text)
        remote_ipv4(config)
        manager.check_configuration(name, config)
        return pack(name, text, password)
    if action not in ("preview", "restore"):
        raise p.Problem("عملیات بازیابی معتبر نیست.")
    payload = unpack(data.get("bundle"), password)
    if not isinstance(payload, dict) or not isinstance(payload.get("name"), str):
        raise p.Problem("محتوای فایل بازیابی معتبر نیست.")
    source = payload["name"]
    fallback = source.lstrip("_-")[:48] or "recovered-client"
    name = fallback if name in (None, "") else name
    if not isinstance(name, str) or not re.fullmatch(p.NAME, name):
        raise p.Problem("نام تونل روی میزبان جدید معتبر نیست.")
    manager.check_name_available(name)
    if not manager.demo and not os.access(p.CORE, os.X_OK):
        raise p.Problem("هستهٔ Paqet روی این میزبان نصب نشده است.")
    config = manager.parse_configuration(payload.get("yaml"))
    target = remote_ipv4(config)
    manager.check_configuration(name, config)
    network = p.mapping(config.get("network"))
    previous = p.mapping(network.get("ipv4")).get("addr", "")
    previous = previous.rsplit(":", 1)[0] if isinstance(previous, str) else ""
    try:
        previous = str(ipaddress.IPv4Address(previous))
        if ipaddress.IPv4Address(previous).is_unspecified or ipaddress.IPv4Address(previous).is_loopback:
            previous = ""
    except ValueError:
        previous = ""
    if manager.demo:
        device, address, mac = "eth0", "192.0.2.10", "02:00:00:00:00:01"
    else:
        device, address, mac = p.network(target)
    network["interface"] = device
    network["ipv4"] = {**p.mapping(network.get("ipv4")), "addr": address + ":0", "router_mac": mac}
    network.setdefault("tcp", {"local_flag": ["PA"], "remote_flag": ["PA"]})
    config["network"] = network
    rows = listeners(config, previous, address)
    manager.check_configuration(name, config)
    if not manager.demo:
        check_listeners(rows)
    text = yaml.safe_dump(config, sort_keys=False)
    fingerprint = hashlib.sha256((name + "\0" + text).encode()).hexdigest()
    if action == "restore":
        approved = data.get("preview")
        if not isinstance(approved, str) or not hmac.compare_digest(approved.encode(), fingerprint.encode()):
            raise p.Problem("اطلاعات بازیابی تغییر کرده است. پیش‌نمایش تازه بگیرید.")
        manager.create({"name": name, "yaml": text})
    return {"name": name, "source": source, "remote": config["server"]["addr"], "interface": device,
            "local": address, "listeners": rows, "preview": fingerprint, "demo": manager.demo}

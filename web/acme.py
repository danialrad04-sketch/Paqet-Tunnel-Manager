"""Issue certificates for receivers with Certbot's standalone HTTP-01 challenge."""
import asyncio
from datetime import datetime, timezone
from functools import lru_cache
import logging
from pathlib import Path

from cryptography import x509

import panel as p

ROOT = Path("/etc/letsencrypt")
CERTBOT = "/usr/bin/certbot"
JOB_TIMEOUT = 240


def paths(domain):
    directory = ROOT / "live" / domain
    return directory / "fullchain.pem", directory / "privkey.pem"


@lru_cache(maxsize=64)
def read_certificate(path, inode, modified):
    certificate = x509.load_pem_x509_certificate(path.read_bytes())
    names = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    not_before = getattr(certificate, "not_valid_before_utc", None)
    expires = getattr(certificate, "not_valid_after_utc", None)
    return (names.get_values_for_type(x509.DNSName),
            not_before or certificate.not_valid_before.replace(tzinfo=timezone.utc),
            expires or certificate.not_valid_after.replace(tzinfo=timezone.utc))


def inspect(domain):
    chain, key = paths(domain)
    managed = (ROOT / "renewal" / f"{domain}.conf").is_file()
    info = {"status": "missing", "expires": None, "managed": managed}
    if not (chain.exists() or key.exists()):
        return info
    try:
        fingerprint = chain.stat()
        names, not_before, expires = read_certificate(chain, fingerprint.st_ino, fingerprint.st_mtime_ns)
        info["expires"] = expires.isoformat()
        wildcard = "*." + domain.partition(".")[2]
        if not key.is_file() or domain not in names and wildcard not in names:
            return {**info, "status": "invalid"}
        now = datetime.now(timezone.utc)
        if now < not_before:
            return {**info, "status": "invalid"}
        if now >= expires:
            return {**info, "status": "expired"}
        return {**info, "status": "ready"}
    except (OSError, ValueError, x509.ExtensionNotFound):
        return {**info, "status": "invalid"}


def error_message(output):
    output = output.lower()
    if "could not bind" in output or "address already in use" in output:
        return "پورت TCP 80 در حال استفاده است. صدور و تمدید HTTP-01 به این پورت نیاز دارند."
    if "rate limit" in output or "too many" in output:
        return "Let’s Encrypt موقتاً درخواست‌های این دامنه را محدود کرده است. گزارش Certbot زمان تلاش مجدد را نشان می‌دهد."
    if "another instance" in output or "lock file" in output:
        return "Certbot در حال اجرای عملیات دیگری است. بعد از پایان آن دوباره تلاش کنید."
    if "nxdomain" in output or "no valid ip addresses" in output or "dns problem" in output:
        return "DNS دامنه آماده نیست. رکوردهای A و در صورت وجود AAAA را بررسی کنید."
    if "unauthorized" in output or "timeout during connect" in output or "connection refused" in output:
        return "Let’s Encrypt نتوانست دامنه را تأیید کند. مقصد DNS و دسترسی عمومی TCP 80 را بررسی کنید."
    return "صدور گواهی ناموفق بود. جزئیات در /var/log/letsencrypt/letsencrypt.log ثبت شده است."


async def issue(domain):
    info = inspect(domain)
    if info["status"] == "ready":
        return info
    if info["status"] != "missing" and not info["managed"]:
        raise p.Problem("این دامنه فایل TLS خارج از مدیریت Certbot دارد. فایل‌های فعلی را بررسی کنید.")
    try:
        process = await asyncio.create_subprocess_exec(
            CERTBOT, "certonly", "--standalone", "--http-01-port", "80",
            "--preferred-challenges", "http-01", "--non-interactive", "--agree-tos",
            "--register-unsafely-without-email", "--keep-until-expiring",
            "--server", "https://acme-v02.api.letsencrypt.org/directory",
            "--cert-name", domain, "--domains", domain,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
        )
    except FileNotFoundError as error:
        raise p.Problem("Certbot نصب نیست. نصب‌کنندهٔ جدید پنل را روی سرور خارج اجرا کنید.") from error
    try:
        output, _ = await asyncio.wait_for(process.communicate(), JOB_TIMEOUT)
    except (asyncio.TimeoutError, asyncio.CancelledError) as error:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.communicate()
        if isinstance(error, asyncio.CancelledError):
            raise
        raise p.Problem("صدور ACME بیش از حد طول کشید. دسترسی TCP 80 و DNS را بررسی کنید.") from error
    if process.returncode:
        logging.warning("Certbot failed for %s (%s)", domain, process.returncode)
        raise p.Problem(error_message(output.decode(errors="replace")))
    info = inspect(domain)
    if info["status"] != "ready":
        raise p.Problem("گواهی معتبر در مسیر مورد انتظار پیدا نشد. گزارش Certbot را بررسی کنید.")
    return info

"""Check the fixed upstream branch and schedule a separately supervised installer."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import panel as p

REPOSITORY = "danialrad04-sketch/Paqet-Tunnel-Manager"
FEED = f"https://api.github.com/repos/{REPOSITORY}/commits?sha=main&per_page=16"
SHA = r"[0-9a-f]{40}"
UNIT = "paqet-panel-update.service"
RUNNER = Path(__file__).resolve().parent / "update-panel.sh"


def revision(directory):
    try:
        value = (directory / "revision").read_text().strip()
    except FileNotFoundError:
        return None
    return value if re.fullmatch(SHA, value) else None


def get_commits():
    request = Request(FEED, headers={"Accept": "application/vnd.github+json", "User-Agent": "Paqet-Panel",
                                     "X-GitHub-Api-Version": "2022-11-28"})
    with urlopen(request, timeout=10) as response:
        blob = response.read(1024 * 1024 + 1)
    if len(blob) > 1024 * 1024:
        raise ValueError("GitHub response too large")
    rows = json.loads(blob)
    if not isinstance(rows, list) or not rows:
        raise ValueError("Invalid commit feed")
    commits = []
    for row in rows[:16]:
        summary = row["commit"]
        sha = row["sha"]
        if not re.fullmatch(SHA, sha):
            raise ValueError("Invalid upstream revision")
        message = summary["message"].strip()[:6000].splitlines()
        date = datetime.fromisoformat(summary["committer"]["date"].replace("Z", "+00:00"))
        commits.append({"sha": sha, "date": date.astimezone(timezone.utc).isoformat(),
                        "title": message[0][:240] if message else sha[:12],
                        "body": "\n".join(message[1:]).strip()})
    return commits


class Updates:
    def __init__(self, directory, demo=False):
        self.directory = directory
        self.demo = demo
        self.lock = threading.Lock()
        self.check = {"status": "idle"}
        self.approval = 0
        self.install_after_check = False

    def installation(self):
        try:
            result = json.loads((self.directory / "update.json").read_text())
        except (FileNotFoundError, ValueError):
            return {"status": "idle"}
        # A job interrupted by reboot has no opportunity to publish its result.
        if not isinstance(result, dict):
            return {"status": "idle"}
        if result.get("status") == "running" and time.time() - result.get("time", 0) > 8:
            try:
                status = p.systemctl("is-active", UNIT, required=False).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                return result
            if status not in ("active", "activating", "reloading", "deactivating"):
                return {**result, "status": "error", "phase": "interrupted"}
        return result

    def view(self):
        with self.lock:
            check = self.check.copy()
        installed = revision(self.directory)
        if installed and check["status"] == "idle":
            try:
                cached = json.loads((self.directory / "update-feed.json").read_text())
            except (FileNotFoundError, ValueError):
                cached = None
            if isinstance(cached, dict) and cached.get("latest") == installed:
                check = {**cached, "status": "current", "base": installed}
        return {"installed": installed, "check": check, "installation": self.installation(),
                "repo": REPOSITORY, "demo": self.demo}

    def start_check(self, install=False):
        with self.lock:
            if self.check["status"] == "checking":
                self.install_after_check |= install and not self.demo
                return
            if self.installation()["status"] == "running":
                return
            self.check = {"status": "checking"}
            self.approval = 0
            self.install_after_check = install and not self.demo
        threading.Thread(target=self.fetch, name="panel-update-check", daemon=True).start()

    def fetch(self):
        checked = int(time.time())
        try:
            current = revision(self.directory)
            commits = get_commits()
            latest = commits[0]["sha"]
            known = next((index for index, row in enumerate(commits) if row["sha"] == current), None)
            changes = commits
            if known is not None:
                changes = commits[:known or 6]
            result = {"status": "available" if current != latest else "current", "checked": checked,
                      "latest": latest, "base": current, "changes": changes,
                      "limited": known is None and current is not None}
        except HTTPError as error:
            result = {"status": "error", "checked": checked,
                      "error": "GitHub درخواست بررسی را موقتاً محدود کرده است." if error.code in (403, 429)
                      else "فهرست تغییرات از GitHub دریافت نشد."}
        except (URLError, OSError, ValueError, KeyError, TypeError, AttributeError):
            result = {"status": "error", "checked": checked, "error": "ارتباط با GitHub یا خواندن فهرست تغییرات ناموفق بود."}
        with self.lock:
            self.check = result
            if not self.demo and result["status"] in ("current", "available"):
                try:
                    p.atomic(self.directory / "update-feed.json", json.dumps(result), 0o600)
                except OSError:
                    pass  # Checking and installing can proceed if the changelog cache cannot be saved.
            self.approval = time.monotonic() + 900 if result["status"] == "available" else 0
            if self.install_after_check and self.approval:
                try:
                    self.schedule(result["latest"])
                except p.Problem as error:
                    result["install_error"] = str(error)
                except OSError:
                    result["install_error"] = "ثبت فرایند نصب روی میزبان ناموفق بود."
            self.install_after_check = False

    def apply(self, sha):
        if self.demo:
            raise p.Problem("نصب نسخه روی پنل نمایشی انجام نمی‌شود.")
        if not isinstance(sha, str) or not re.fullmatch(SHA, sha):
            raise p.Problem("شناسهٔ نسخه معتبر نیست.")
        with self.lock:
            self.schedule(sha)

    def schedule(self, sha):
        base = revision(self.directory)
        if (self.check.get("latest") != sha or self.check.get("base") != base
                or time.monotonic() >= self.approval):
            raise p.Problem("ابتدا دوباره به‌روزرسانی را بررسی کنید.")
        if self.installation()["status"] == "running":
            raise p.Problem("نصب نسخه در حال اجراست.")
        result = {"status": "running", "phase": "queued", "revision": sha, "time": int(time.time())}
        path = self.directory / "update.json"
        p.atomic(path, json.dumps(result), 0o600)
        try:
            p.run("systemd-run", "--quiet", "--collect", f"--unit={UNIT}", "--property=Type=exec",
                  "/bin/bash", str(RUNNER), sha, base or "unknown")
        except (p.Problem, OSError, subprocess.SubprocessError) as error:
            p.atomic(path, json.dumps({**result, "status": "error", "phase": "schedule"}), 0o600)
            raise p.Problem("سرویس نصب نسخه شروع نشد. گزارش systemd را بررسی کنید.") from error
        self.approval = 0

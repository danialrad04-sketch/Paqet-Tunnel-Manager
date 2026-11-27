"""Test approved revision checks and the installer lifecycle without root."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_relay import relay
import updates

ROOT = Path(relay.__file__).resolve().parent.parent
BASE = "a" * 40
TARGET = "b" * 40


class UpdateApprovalTest(unittest.TestCase):
    def test_check_and_approval_pin_the_ordered_change_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "revision").write_text(BASE + "\n")
            manager = updates.Updates(directory)
            with patch.object(updates, "get_commits", return_value=[{"sha": TARGET}, {"sha": BASE}]):
                manager.fetch()
            self.assertEqual(manager.view()["check"]["changes"], [{"sha": TARGET}])
            with self.assertRaises(relay.p.Problem):
                manager.apply("c" * 40)
            with patch.object(relay.p, "run") as launch:
                manager.apply(TARGET)
            self.assertEqual(launch.call_args.args[-2:], (TARGET, BASE))
            self.assertEqual(manager.installation()["status"], "running")
            with self.assertRaises(relay.p.Problem):
                manager.apply(TARGET)


    def test_one_click_installs_only_when_a_new_revision_is_available(self):
        for newest, demo in ((TARGET, False), (BASE, False), (TARGET, True)):
            with self.subTest(newest=newest, demo=demo), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                (directory / "revision").write_text(BASE + "\n")
                manager = updates.Updates(directory, demo)
                with patch.object(updates.threading, "Thread") as thread:
                    manager.start_check(install=True)
                    manager.start_check(install=True)
                self.assertEqual(thread.call_count, 1)
                with patch.object(updates, "get_commits", return_value=[{"sha": newest}, {"sha": BASE}]):
                    with patch.object(relay.p, "run") as launch:
                        thread.call_args.kwargs["target"]()
                if newest == TARGET and not demo:
                    self.assertEqual(launch.call_args.args[-2:], (TARGET, BASE))
                    self.assertEqual(manager.installation()["status"], "running")
                    (directory / "revision").write_text(TARGET + "\n")
                    restarted = updates.Updates(directory).view()
                    self.assertEqual(restarted["check"]["status"], "current")
                    self.assertEqual(restarted["check"]["changes"], [{"sha": TARGET}])
                else:
                    launch.assert_not_called()


@unittest.skipUnless(shutil.which("git") and shutil.which("flock"), "git and flock are required")
class UpdateWorkerTest(unittest.TestCase):
    def test_install_success_and_rollback_after_failed_install(self):
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                state, panel = base / "state", base / "panel"
                state.mkdir()
                panel.mkdir()
                (panel / "static").mkdir()
                (panel / "static" / "index.html").write_text("old interface")
                (panel / "panel.py").write_text("old Python")
                (panel / "packet-rules.sh").touch()
                unit = base / "paqetpanel.service"
                unit.write_text("old unit")
                repo = base / "source"
                repo.mkdir()
                git = lambda *args: subprocess.check_output(["git", "-C", str(repo), *args], text=True,
                                                              stderr=subprocess.PIPE).strip()
                git("init", "-b", "main")
                git("config", "user.name", "Test")
                git("config", "user.email", "example@example.org")
                (repo / "install-web.sh").touch()
                git("add", "install-web.sh")
                git("commit", "-m", "Installed version")
                current = git("rev-parse", "HEAD")
                (state / "revision").write_text(current + "\n")
                installer = [
                    f"printf 'new interface' > {shlex.quote(str(panel / 'static/index.html'))}",
                    f"printf 'new Python' > {shlex.quote(str(panel / 'panel.py'))}",
                    f"printf 'new unit' > {shlex.quote(str(unit))}",
                    'revision=$(git -C "$(dirname -- "$0")" rev-parse HEAD)',
                    f'printf "%s\\n" "$revision" > {shlex.quote(str(state / "revision"))}',
                    "exit 1" if fail else "exit 0",
                ]
                (repo / "install-web.sh").write_text("\n".join(installer) + "\n")
                git("add", "install-web.sh")
                git("commit", "-m", "Checked update")
                target = git("rev-parse", "HEAD")
                worker = (ROOT / "web/update-panel.sh").read_text()
                for line, value in {
                    "repository=https://github.com/danialrad04-sketch/Paqet-Tunnel-Manager.git": "repository=" + repo.as_uri(),
                    "state=/etc/paqet-panel": f"state={state}",
                    "panel=/opt/paqet-panel": f"panel={panel}",
                    "unit=/etc/systemd/system/paqetpanel.service": f"unit={unit}",
                    "/run/lock/paqet-panel-install.lock": str(base / "install.lock"),
                }.items():
                    worker = worker.replace(line, value)
                (base / "worker.sh").write_text(worker)
                (base / "systemctl").write_text("#!/bin/sh\nexit 0\n")
                (base / "curl").write_text("#!/bin/sh\nwhile [ \"$1\" != -o ]; do shift; done\n"
                                           f"cp {shlex.quote(str(panel / 'static/index.html'))} \"$2\"\n")
                for binary in ("systemctl", "curl"):
                    (base / binary).chmod(0o755)
                result = subprocess.run(["bash", str(base / "worker.sh"), target, current], capture_output=True,
                                        env={**os.environ, "PATH": str(base) + os.pathsep + os.environ["PATH"]}, timeout=15)
                self.assertEqual(result.returncode, 1 if fail else 0, result.stderr.decode())
                status = json.loads((state / "update.json").read_text())
                self.assertEqual(status["phase"], "rolled_back" if fail else "complete")
                self.assertEqual((state / "revision").read_text().strip(), current if fail else target)
                self.assertEqual((panel / "panel.py").read_text(), "old Python" if fail else "new Python")
                self.assertEqual(unit.read_text(), "old unit" if fail else "new unit")

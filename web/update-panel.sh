#!/bin/bash
set -euo pipefail
umask 077

target=${1:-}
base=${2:-}
[[ $target =~ ^[a-f0-9]{40}$ && ( $base == unknown || $base =~ ^[a-f0-9]{40}$ ) ]] || exit 2
repository=https://github.com/danialrad04-sketch/Paqet-Tunnel-Manager.git
state=/etc/paqet-panel
panel=/opt/paqet-panel
unit=/etc/systemd/system/paqetpanel.service
stage=$(mktemp -d)
phase=download_failed
installed=no
backed_up=no
install_options=()

record() {
    /usr/bin/python3 - "$state" "$target" "$1" "$2" <<'PY'
import json
import os
from pathlib import Path
import sys
import tempfile
import time

directory, revision, status, phase = sys.argv[1:]
path = Path(directory) / "update.json"
with tempfile.NamedTemporaryFile(mode="w", dir=directory, delete=False) as out:
    json.dump({"status": status, "phase": phase, "revision": revision, "time": int(time.time())}, out)
    temporary = out.name
os.replace(temporary, path)
PY
}

restore_panel() {
    cp -a "$stage/panel/." "$panel/" &&
    cp -a "$stage/paqetpanel.service" "$unit" || return 1
    if [[ -e "$stage/revision" ]]; then
        cp -a "$stage/revision" "$state/revision" || return 1
    else
        rm -f -- "$state/revision" || return 1
    fi
    if [[ -d "$stage/quic-venv" ]]; then
        if [[ -e "$panel/quic-venv" || -L "$panel/quic-venv" ]]; then
            mv -- "$panel/quic-venv" "$stage/failed-quic-venv" || return 1
        fi
        mv -- "$stage/quic-venv" "$panel/quic-venv" || return 1
    fi
    systemctl daemon-reload && systemctl restart paqetpanel.service || return 1
    local attempt
    for attempt in {1..10}; do
        if curl --noproxy '*' -fsS --max-time 2 http://127.0.0.1:8765/ -o "$stage/served.html" 2>/dev/null &&
            cmp -s "$stage/served.html" "$stage/panel/static/index.html"; then
            return 0
        fi
        sleep 1
    done
    return 1
}

finish() {
    local code=$?
    trap - EXIT
    if [[ $installed == yes ]]; then
        record done complete
    elif [[ $backed_up == yes ]]; then
        record running rollback
        if restore_panel; then
            record error rolled_back
        else
            record error rollback_failed
            echo "Rollback needs attention. Working files are in $stage." >&2
            exit "$code"
        fi
    else
        record error "$phase"
    fi
    rm -rf -- "$stage"
    exit "$code"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
record running download

exec 9>/run/lock/paqet-panel-install.lock
if ! flock -n 9; then
    phase=busy
    exit 1
fi
current=unknown
if [[ -r "$state/revision" ]]; then
    read -r current < "$state/revision"
fi
if [[ $current != "$base" ]]; then
    phase=changed
    exit 1
fi

export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_TERMINAL_PROMPT=0
timeout --kill-after=10s 180s git -c http.followRedirects=false clone --depth 64 --no-tags --single-branch --branch main -- "$repository" "$stage/checkout"
head=$(git -C "$stage/checkout" rev-parse HEAD)
if [[ $head != "$target" ]]; then
    phase=changed
    exit 1
fi
if [[ $base != unknown ]] && ! git -C "$stage/checkout" merge-base --is-ancestor "$base" "$target"; then
    if [[ $(git -C "$stage/checkout" rev-parse --is-shallow-repository) == true ]]; then
        timeout --kill-after=10s 180s git -C "$stage/checkout" -c http.followRedirects=false fetch --unshallow --no-tags origin main
    fi
    if ! git -C "$stage/checkout" merge-base --is-ancestor "$base" "$target"; then
        phase=diverged
        exit 1
    fi
fi

phase=backup_failed
mkdir "$stage/panel"
cp -a "$panel"/*.py "$panel"/*.sh "$panel/static" "$stage/panel/"
cp -a "$unit" "$stage/paqetpanel.service"
if [[ -r "$state/revision" ]]; then
    cp -a "$state/revision" "$stage/revision"
fi
if [[ -x "$panel/quic-venv/bin/python" ]]; then
    cp -a "$panel/quic-venv" "$stage/quic-venv"
    install_options=(--with-quic)
fi
backed_up=yes
record running install
PAQET_INSTALL_LOCK_HELD=1 bash "$stage/checkout/install-web.sh" "${install_options[@]}"
[[ $(cat "$state/revision") == "$target" ]]
installed=yes

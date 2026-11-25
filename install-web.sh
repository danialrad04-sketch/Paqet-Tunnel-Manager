#!/bin/bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  sudo bash install-web.sh   # downloads the bundled core version if missing
  sudo bash install-web.sh --public-http
  sudo bash install-web.sh --local-http
  sudo bash install-web.sh --core /path/to/paqet --sha256 SHA256
  sudo bash install-web.sh --core-url https://example.org/paqet.tar.gz --sha256 SHA256
EOF
}

core=
url=
checksum=
listen=
while (($#)); do
    case $1 in
        --public-http) listen=0.0.0.0; shift ;;
        --local-http) listen=127.0.0.1; shift ;;
        --core|--core-url|--sha256)
            [[ $# -ge 2 ]] || { usage >&2; exit 2; }
            case $1 in
                --core) core=$2 ;;
                --core-url) url=$2 ;;
                --sha256) checksum=$2 ;;
            esac
            shift 2 ;;
        --help|-h) usage; exit ;;
        *) usage >&2; exit 2 ;;
    esac
done

[[ $EUID == 0 ]] || { echo 'Run the installer with sudo.' >&2; exit 1; }
[[ -d /run/systemd/system && -x /usr/bin/apt-get ]] ||
    { echo 'This installer requires Debian/Ubuntu with systemd.' >&2; exit 1; }
if [[ -n $url || -n $core ]]; then
    [[ $checksum =~ ^[a-fA-F0-9]{64}$ ]] ||
        { echo 'Provide the expected SHA-256 for the selected core.' >&2; exit 2; }
    [[ -z $url || ( $url == https://* && -z $core ) ]] ||
        { echo 'Use one core source and an HTTPS download URL.' >&2; exit 2; }
fi
if [[ -z $core && -z $url && ! -x /usr/local/bin/paqet ]]; then
    version=v1.0.0-alpha.21
    case "$(dpkg --print-architecture)" in
        amd64) architecture=amd64; checksum=4f2f69e0493746726598485ef18df43372470a1514f8021594137e522f0f4fc7 ;;
        arm64) architecture=arm64; checksum=be5c7b35a0a93832063e1dc7fddeb76d4597fb9de76abdfdf7b8574b775e3885 ;;
        *) echo 'Automatic core installation supports amd64 and arm64. Use --core with --sha256 for other architectures.' >&2
           exit 1 ;;
    esac
    url="https://github.com/hanselime/paqet/releases/download/$version/paqet-linux-$architecture-$version.tar.gz"
fi

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
[[ -f "$source_dir/web/panel.py" ]] ||
    { echo 'Missing panel files. Use bootstrap-web.sh for installation from GitHub.' >&2; exit 1; }
export DEBIAN_FRONTEND=noninteractive
/usr/bin/apt-get update
/usr/bin/apt-get install -y python3 python3-yaml python3-cryptography libpcap-dev iptables iproute2 iputils-ping curl ca-certificates
staging=$(mktemp -d)
trap 'rm -rf -- "$staging"' EXIT

if [[ -n $url || -n $core ]]; then
    if [[ -n $url ]]; then
        curl --fail --silent --show-error --location --retry 2 --proto '=https' --proto-redir '=https' \
            --max-time 120 --max-filesize 67108864 --output "$staging/input" -- "$url"
    else
        cp -- "$core" "$staging/input"
    fi
    printf '%s  %s\n' "${checksum,,}" "$staging/input" | sha256sum --check --status ||
        { echo 'Core SHA-256 verification failed.' >&2; exit 1; }
    /usr/bin/python3 - "$staging/input" "$staging/paqet" <<'PY'
import shutil
import sys
import tarfile
from pathlib import Path

source, target = map(Path, sys.argv[1:])
with source.open("rb") as stream:
    if stream.read(4) == b"\x7fELF":
        shutil.copyfile(source, target)
    else:
        with tarfile.open(source, "r:gz") as archive:
            choices = [entry for entry in archive if entry.isfile() and
                       (Path(entry.name).name == "paqet" or Path(entry.name).name.startswith(
                           ("paqet-linux-", "paqet_linux_")))]
            if len(choices) != 1 or not 1 <= choices[0].size <= 64 * 1024 * 1024:
                sys.exit("Archive must contain exactly one Paqet executable.")
            with archive.extractfile(choices[0]) as binary, target.open("wb") as output:
                if binary.read(4) != b"\x7fELF":
                    sys.exit("The selected core is not a Linux ELF executable.")
                binary.seek(0)
                shutil.copyfileobj(binary, output)
PY
    chmod 0755 "$staging/paqet"
    timeout 10 "$staging/paqet" version
    if [[ -e /usr/local/bin/paqet ]] && ! cmp -s "$staging/paqet" /usr/local/bin/paqet; then
        echo 'A different core is already installed. Select the same core or update it separately.' >&2
        exit 1
    fi
    if [[ ! -e /usr/local/bin/paqet ]]; then
        install -m 0755 "$staging/paqet" /usr/local/bin/paqet
    fi
fi

install -d -m 0755 /opt/paqet-panel /opt/paqet-panel/static /opt/paqet-panel/static/fonts
install -d -m 0700 /etc/paqet-panel
install -m 0644 "$source_dir"/web/{panel,relay,operations,recovery}.py /opt/paqet-panel/
install -m 0755 "$source_dir/web/packet-rules.sh" /opt/paqet-panel/packet-rules.sh
install -m 0644 "$source_dir"/web/static/*.html "$source_dir"/web/static/*.css "$source_dir"/web/static/*.js /opt/paqet-panel/static/
install -m 0644 "$source_dir"/web/static/fonts/* /opt/paqet-panel/static/fonts/
if [[ ! -e /etc/paqet-panel/token ]]; then
    (umask 077; /usr/bin/python3 -c 'import secrets; print(secrets.token_urlsafe(40))' > /etc/paqet-panel/token)
fi

if [[ -n $listen ]]; then
    (umask 077; printf 'PAQET_HTTP_BIND=%s\n' "$listen" > /etc/paqet-panel/http.env)
fi

cat > /etc/systemd/system/paqetpanel.service <<'UNIT'
[Unit]
Description=Paqet local web administration
After=network.target

[Service]
Type=exec
EnvironmentFile=-/etc/paqet-panel/http.env
ExecStart=/usr/bin/python3 /opt/paqet-panel/panel.py
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable paqetpanel.service
systemctl restart paqetpanel.service
systemctl is-active --quiet paqetpanel.service
ready=
for attempt in {1..10}; do
    if curl --noproxy '*' -fsS --max-time 2 http://127.0.0.1:8765/api/session 2>/dev/null |
        /usr/bin/python3 -c 'import json,sys; s=json.load(sys.stdin); sys.exit(s.get("demo") is not False or s.get("authenticated") is not False)' 2>/dev/null; then
        ready=yes
        break
    fi
    sleep 1
done
if [[ -z $ready ]]; then
    echo 'Panel HTTP check failed. See journalctl -u paqetpanel.service -n 30.' >&2
    exit 1
fi
if [[ -f /etc/paqet-panel/http.env ]] &&
        grep -Fxq 'PAQET_HTTP_BIND=0.0.0.0' /etc/paqet-panel/http.env; then
    panel_address=$(ip -4 -o address show scope global | awk 'NR == 1 {split($4,a,"/"); print a[1]}')
    echo "Paqet Panel installed at http://${panel_address:-SERVER_IPV4}:8765"
    echo 'If the host uses NAT, open this port on its public address.'
else
    echo 'Paqet Panel installed at http://127.0.0.1:8765'
    echo 'From your computer: ssh -N -L 8765:127.0.0.1:8765 USER@SERVER'
fi
echo 'On the server, read the login token with: sudo cat /etc/paqet-panel/token'

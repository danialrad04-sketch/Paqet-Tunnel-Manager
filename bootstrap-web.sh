#!/bin/bash
set -euo pipefail

if [[ $EUID != 0 ]]; then
    echo 'Run the installer as root or with sudo.' >&2
    exit 1
fi
if [[ ! -d /run/systemd/system || ! -x /usr/bin/apt-get ]]; then
    echo 'This installer requires Debian/Ubuntu with systemd.' >&2
    exit 1
fi
if ! command -v curl >/dev/null || [[ ! -s /etc/ssl/certs/ca-certificates.crt ]]; then
    /usr/bin/apt-get update
    DEBIAN_FRONTEND=noninteractive /usr/bin/apt-get install -y curl ca-certificates
fi

checkout=$(mktemp -d)
trap 'rm -rf -- "$checkout"' EXIT
archive='https://codeload.github.com/danialrad04-sketch/Paqet-Tunnel-Manager/tar.gz/refs/heads/web-panel'
curl --fail --silent --show-error --location --retry 2 --proto '=https' --proto-redir '=https' \
    --max-time 120 --max-filesize 33554432 --output "$checkout/panel.tar.gz" -- "$archive"
tar -xzf "$checkout/panel.tar.gz" -C "$checkout" --strip-components=1 --no-same-owner --no-same-permissions
bash "$checkout/install-web.sh" "$@"

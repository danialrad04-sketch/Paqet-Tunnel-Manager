#!/bin/bash
set -euo pipefail

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
upstream_ref=v1.0.0-alpha.21
upstream_commit=4b81ce0ab56b7cc9aec7501c87c4804676cdb1b4
output=$(realpath -m -- "${1:-./paqet-health}")
stage=$(mktemp -d)
trap 'rm -rf -- "$stage"' EXIT

git -c advice.detachedHead=false clone --quiet --depth 1 --single-branch --branch "$upstream_ref" \
    https://github.com/hanselime/paqet.git "$stage/source"
cd "$stage/source"
[[ $(git rev-parse HEAD) == "$upstream_commit" ]] ||
    { echo 'Upstream source did not match the tested commit.' >&2; exit 1; }
git apply --unidiff-zero --check "$source_dir/health.patch"
git apply --unidiff-zero "$source_dir/health.patch"
go test -mod=readonly ./cmd/health
go build -mod=readonly -trimpath -o "$output" \
    -ldflags "-X paqet/cmd/version.Version=$upstream_ref+health.1 -X paqet/cmd/version.GitCommit=$upstream_commit -X paqet/cmd/version.GitTag=$upstream_ref" ./cmd
printf 'Built %s\n' "$output"

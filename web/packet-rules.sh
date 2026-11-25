#!/bin/bash
set -euo pipefail
operation=$1
name=$2
port=$3
[[ $name =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]{0,47}$ && $port =~ ^[0-9]{1,5}$ ]]
((port >= 1 && port <= 65535))
rule() {
    local table=$1 chain=$2
    shift 2
    local args=(-p tcp -m comment --comment "paqet-panel:${name}" "$@")
    if [[ $operation == add ]]; then
        iptables -w 3 -t "$table" -C "$chain" "${args[@]}" 2>/dev/null ||
            iptables -w 3 -t "$table" -A "$chain" "${args[@]}"
    elif [[ $operation == remove ]]; then
        if iptables -w 3 -t "$table" -C "$chain" "${args[@]}" 2>/dev/null; then
            iptables -w 3 -t "$table" -D "$chain" "${args[@]}"
        fi
    else
        return 2
    fi
}
rule raw PREROUTING --dport "$port" -j NOTRACK
rule raw OUTPUT --sport "$port" -j NOTRACK
rule mangle OUTPUT --sport "$port" --tcp-flags RST RST -j DROP

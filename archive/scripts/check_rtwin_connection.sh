#!/bin/sh

set -eu

HOST=${AUTO_G16_WINDOWS_HOST:?Set AUTO_G16_WINDOWS_HOST to the RTwin address}
SSH_ALIAS=${AUTO_G16_WINDOWS_TARGET:-rtwin}
ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SSH_CONFIG=${AUTO_G16_RTWIN_SSH_CONFIG:-"$ROOT_DIR/config/ssh_config"}

echo "[1/3] Checking Tailscale reachability: $HOST"
ping -c 1 "$HOST"

echo "[2/3] Checking Windows OpenSSH port: $HOST:22"
nc -vz -w 5 "$HOST" 22

echo "[3/3] Checking key login and remote command execution"
ssh -F "$SSH_CONFIG" "$SSH_ALIAS" "hostname & whoami & echo %USERPROFILE% & where ssh"

echo "RTwin connection check passed."

#!/usr/bin/env bash

set -u

printf 'hostname=%s\n' "$(hostname)"
printf 'user=%s\n' "$(id -un)"
printf 'home=%s\n' "$HOME"
printf 'shell=%s\n' "$SHELL"
printf 'kernel=%s\n' "$(uname -srmo)"
printf 'online_cpus=%s\n' "$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc)"
awk '/^MemTotal:/ { printf "memory_kib=%s\n", $2 }' /proc/meminfo
df -Pk "$HOME" | awk 'NR == 2 { printf "home_fs_kib_total=%s\nhome_fs_kib_available=%s\n", $2, $4 }'

for command_name in qsub qstat qdel pbsnodes tracejob g16 formchk cubegen; do
    command_path=$(command -v "$command_name" 2>/dev/null || true)
    if [ -n "$command_path" ]; then
        printf 'command.%s=%s\n' "$command_name" "$command_path"
    else
        printf 'command.%s=MISSING\n' "$command_name"
    fi
done

if command -v qstat >/dev/null 2>&1; then
    printf '%s\n' 'pbs.version.begin'
    qstat --version 2>&1 || true
    printf '%s\n' 'pbs.version.end'
    printf '%s\n' 'pbs.queues.begin'
    qstat -Q 2>&1 || true
    printf '%s\n' 'pbs.queues.end'
fi

if type module >/dev/null 2>&1; then
    printf '%s\n' 'modules.gaussian.begin'
    module -t avail 2>&1 | grep -i gaussian | head -n 20 || true
    printf '%s\n' 'modules.gaussian.end'
fi

env | grep -E '^(g16root|GAUSS_EXEDIR|GAUSS_SCRDIR)=' || true

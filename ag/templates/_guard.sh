# Adapted from archive/templates/g16_job.pbs.template; no legacy imports.
set -eu
# Reject existing output files rather than truncate a previous execution.
set -C
allowed_root=$allowed_root
work_dir=$work_dir
root_real=$$(realpath -e -- "$$allowed_root")
work_real=$$(realpath -e -- "$$${workdir_variable}")
test "$$root_real" = "$$allowed_root"
test "$$work_real" = "$$work_dir"
test "$$${workdir_variable}" = "$$work_dir"
case "$$work_real" in "$$allowed_root"/*) ;; *) exit 41 ;; esac
$path_checks
cd "$$work_real"
scratch="$$work_real/scratch"
test ! -e "$$scratch"
test ! -L "$$scratch"
mkdir -- "$$scratch"
export GAUSS_SCRDIR="$$scratch"
# Completion receipts adapted from the idea in
# archive/auto_g16/execution/_program_completion_wrapper.py; no legacy imports.
# Noclobber prevents a second launch from replacing either receipt.
ag_run() {
    case "$${${jobid_variable}:-}" in ''|*[!A-Za-z0-9_.-]*) exit 42 ;; esac
    test ! -e ag-start.json
    test ! -L ag-start.json
    test ! -e ag-exit.json
    test ! -L ag-exit.json
    printf '{"started_at":"%s","${receipt_job_key}":"%s"}\n' "$$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$$${jobid_variable}" > ag-start.json
    if "$$@"; then
        ag_code=0
    else
        ag_code=$$?
    fi
    test ! -e ag-exit.json
    test ! -L ag-exit.json
    printf '{"returncode":%s,"finished_at":"%s","${receipt_job_key}":"%s"}\n' "$$ag_code" "$$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$$${jobid_variable}" > ag-exit.json
    exit "$$ag_code"
}

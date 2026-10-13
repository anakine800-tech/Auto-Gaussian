# Adapted from templates/g16_job.pbs.template; no legacy imports.
set -eu
# Reject existing output files rather than truncate a previous execution.
set -C
allowed_root=$allowed_root
work_dir=$work_dir
root_real=$$(realpath -e -- "$$allowed_root")
work_real=$$(realpath -e -- "$$PBS_O_WORKDIR")
test "$$root_real" = "$$allowed_root"
test "$$work_real" = "$$work_dir"
test "$$PBS_O_WORKDIR" = "$$work_dir"
case "$$work_real" in "$$allowed_root"/*) ;; *) exit 41 ;; esac
$path_checks
cd "$$work_real"
scratch="$$work_real/scratch"
test ! -e "$$scratch"
test ! -L "$$scratch"
mkdir -- "$$scratch"
export GAUSS_SCRDIR="$$scratch"

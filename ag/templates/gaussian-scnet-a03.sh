# SCNet A.03 runtime settings, adapted from the platform's env.sh and
# Gaussian g16.profile inspected on 2026-10-14. Do not source env.sh: it
# resets scratch to the installation and appends to a shared external file.
# Configuration g16root denotes the executable directory; Gaussian's own
# g16root environment variable denotes its parent.
gaussian_dir=$g16root
export g16root=$gaussian_parent
export GAUSS_EXEDIR="$$gaussian_dir/bsd:$$gaussian_dir"
export GAUSS_LEXEDIR="$$gaussian_dir/linda-exe"
export GAUSS_ARCHDIR="$$gaussian_dir/arch"
export GAUSS_BSDDIR="$$gaussian_dir/bsd"
export PATH="$$gaussian_dir:$$gaussian_dir/bsd:$$PATH"
export LD_LIBRARY_PATH="$$gaussian_dir:$${LD_LIBRARY_PATH:-}"
export PGI_FASTMATH_CPU=sandybridge
export OMP_THREAD_LIMIT=$cores
export GAUSS_SCRDIR="$$scratch"
test ! -e $log_name
test ! -L $log_name
ag_run "$$gaussian_dir/g16" $input_name

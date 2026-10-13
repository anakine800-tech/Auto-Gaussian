# Remote server extension contract

The local-to-VM workflow is the default. A future remote backend should consume the exact reviewed Gaussian input and its JSON manifest; it should not re-interpret ChemDraw geometry.

## Required operations

```text
submit(input_path, manifest_path, scheduler_options) -> job_id, remote_workdir
status(job_id) -> queued | running | completed | failed | cancelled
fetch(job_id, destination) -> copied log/checkpoint/result files
cancel(job_id) -> confirmation
```

## Required metadata

Store the scheduler name, account/project, partition/queue, requested resources, submit timestamp, remote working directory, job ID, and checksums of the submitted `.gjf` and manifest. Never put passwords, private keys, or tokens in this Skill or in a manifest.

## SSH/Slurm implementation notes

An adapter may use a user-configured SSH host and `sbatch`, but it must quote paths, keep each job in an isolated directory, and verify that the remote input checksum matches the local manifest before submission. It should fetch the `.log` before claiming success and use Gaussian's `Normal termination` check, not just the scheduler exit code.

If the server requires a new credential, account, partition, or module setup, stop and ask the user rather than inferring it.

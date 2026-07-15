# Repository operating rules

These rules apply to the entire repository.

## Source of truth

- Treat `skills/` as the version-controlled source of truth.
- Treat `~/.codex/skills/<name>` as a deployed copy. Do not edit a deployed copy and a repository copy independently.
- Before deploying a Skill, validate the repository copy, compare the planned diff, then synchronize only that named Skill.
- Keep experimental workflow code on a feature branch. Merge it only after offline tests and an explicitly approved live smoke test.

## Auto-G16 Skill naming

- Name every repository-owned Skill in this project with the machine prefix `auto-g16-` and make its folder name exactly match the `name` in `SKILL.md`.
- Use `Auto-G16` at the beginning of each human-facing Skill display name and document title.
- Apply the same prefix to every future project Skill, including literature, mechanism-network, TS-seed, reaction-analysis, and transition-metal extensions.
- Do not rename versioned scientific artifact schemas, historical immutable records, Gaussian program terminology, or external dependency Skills solely because a Skill is renamed. Preserve their compatibility and provenance.

## Server safety boundary

- Permit Skill-managed server data and scratch only below `/home/user100/SDL`.
- Resolve the allowed root and project paths with `realpath`; reject symlinks and any path outside the allowed root.
- Never add a remote-root override.
- Never upload into a non-empty server project directory or overwrite an existing job implicitly.
- Never issue `rm`, `rmdir`, truncation, recursive replacement, or a server-data cleanup command.
- Treat active-job cancellation and terminal scheduler-zombie cleanup as different `qdel` operations. Require explicit authorization for the exact PBS job ID before cancelling a queued or running job. Permit one automatic exact `qdel` only after results are fetched and repeated stable evidence proves a terminal scheduler zombie; never retry it automatically. Neither operation authorizes file deletion.
- Do not access PBS scheduler spool directories.

## Scientific approval gates

- Do not submit a Gaussian job unless structure, stereochemistry, charge, multiplicity, route, resources, server directory, and input hash have been shown and approved.
- Do not infer a research method, basis, solvent, TS algorithm, IRC settings, or low-frequency correction from the molecule.
- Do not change chemistry or retry a failed job automatically.
- For a transition state, never accept frequency count alone: require exactly one imaginary frequency and explicit review that its normal mode follows the intended reaction coordinate.
- Do not claim IRC validation until both directions terminate and their endpoints are structurally identified.

## Development and testing

- Prefer offline builders, parsers, fixtures, and dry runs before any live PBS test.
- Use the `simple` resource tier (12 GB, 8 cores) for approved smoke tests unless a smaller custom test is explicitly approved. Use `general` (50 GB, 22 cores) and `complex` (120 GB, 44 cores) only under the established resource policy.
- Never run live SSH, PBS, Gaussian, cancellation, or deployment tests merely because a unit test is being executed.
- Keep live tests opt-in and require the same confirmation gates as normal operations.
- Preserve manifests, input hashes, logs, checkpoints, job IDs, and structured result files.

## Codex thread and worktree isolation

- Treat one independently developed Codex task as one Codex worktree and one unique `codex/` feature branch.
- When the user asks in conversation to create a new isolated task, chat, thread, or work area, use the Codex thread-creation capability with a `worktree` environment. Do not switch the branch of the current shared checkout.
- Create a fresh worktree task when the new work does not need the current conversation history. Fork the current task into a worktree when the user wants to preserve the completed conversation context.
- Start from the project's default branch unless the user explicitly names an existing branch or asks to include the current working tree and its uncommitted changes. Never include uncommitted changes implicitly.
- Keep the original repository checkout stable for inspection, integration, and release work. Do not manually reuse one feature branch across multiple active worktrees.
- Recognize requests such as `新建隔离任务：<工作内容>` and `把当前对话分叉到独立 worktree` as explicit authorization to create the corresponding Codex task and worktree.
- If the Codex thread/worktree capability is unavailable, report that limitation instead of changing the current checkout as a workaround.

## Git and secrets

- Do not commit passwords, private keys, host credentials, local SSH configuration, Gaussian outputs, checkpoints, or server scratch data.
- Inspect staged files and run a sensitive-string/private-key scan before every commit.
- Stage only files intended for the current change; do not use broad staging when unrelated untracked files exist.
- Use `codex/` as the branch prefix for feature work.

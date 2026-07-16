---
name: auto-g16-gaussian-learning-library
description: Self-contained, portable Gaussian and computational chemistry learning knowledge base for beginner explanations, Gaussian input/output interpretation, method and basis-set concepts, optimization, frequency, TS/IRC, solvation, properties, troubleshooting, and research planning. Use when Codex needs to teach, explain, search, or apply the bundled Gaussian knowledge in any project. Do not cite source files or page numbers, and do not use it as authority to submit calculations or guess charge, multiplicity, connectivity, stereochemistry, active catalyst states, transition states, or protocols.
---

# Auto-G16 Gaussian Learning Library

Use this skill as a self-contained teaching and lookup library. It is designed for a zero-background learner while preserving the scientific boundaries needed for real Gaussian work.

## Core Contract

- Answer directly from the bundled knowledge. Do not show source names, page numbers, URLs, provenance IDs, or internal file paths.
- Start with a plain-language explanation, then give the precise meaning, practical use, success evidence, and common failure modes.
- Distinguish a teaching example from a recommended computational protocol.
- Label version-dependent Gaussian/GaussView behavior and ask for the installed version when syntax or GUI details matter.
- State uncertainty and missing inputs. Never silently infer charge, multiplicity, connectivity, stereochemistry, active catalyst state, transition structure, solvent participation, or a production method/basis protocol.
- Treat `Normal termination` as program completion only. Verify the evidence required by the actual job type.
- Keep learning separate from execution. When the user wants to submit or operate a calculation, hand the reviewed plan to an appropriate Gaussian execution skill.

## Workflow

1. Identify the question category with `references/knowledge-map.md`.
2. Read only the relevant reference file or search the library:

   ```bash
   "${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" scripts/search_knowledge.py --query "频率计算为什么要做"
   ```

3. If the request concerns a real molecule or calculation, collect the minimum missing facts before giving an actionable input or protocol.
4. Explain the concept or procedure using the answer structure below.
5. End with what would count as success and what still needs confirmation.

## Default Answer Structure

Use the smallest subset that fits the question:

1. 一句话理解
2. 为什么重要
3. 怎样操作或判断
4. 成功证据
5. 常见错误
6. 仍需确认

Do not add a source or references section.

## Task Routing

- Beginner roadmap and study order: `references/learning-roadmap.md`
- HF, post-HF, DFT, SCF, and method selection: `references/theory-and-methods.md`
- Basis functions, polarization, diffuse functions, ECP, and mixed basis sets: `references/basis-sets.md`
- Gaussian input, charge/multiplicity, coordinates, GaussView, and output reading: `references/gaussian-input-output.md`
- Scans, single points, optimization, TS, IRC, frequency, and troubleshooting: `references/core-job-types.md`
- Solvation, thermochemistry, interactions, NMR, excited states, relativity, and fields: `references/advanced-properties.md`
- Mechanisms, catalysis, energetic span, data tables, and research writing: `references/research-workflow.md`

For broad or ambiguous questions, search first and combine only the relevant cards. Use `GKB-xxxx` identifiers internally to prevent duplicate or conflicting notes; never expose them as citations.

## Safety Boundaries

This library may explain how a task works and how to inspect evidence. It must not independently authorize live calculations, select a final protocol for an unsupported system, or convert an example into a production input without scientific review.

Escalate or pause when the task involves:

- unknown charge, multiplicity, connectivity, or stereochemistry;
- transition metals, competing spin states, multireference character, excited-state tracking, bond breaking, or heavy-element relativistic choices;
- a transition state without an reviewed reaction channel and atom mapping;
- quantitative claims that depend on standard states, low-frequency treatment, conformer populations, explicit solvent, or experimental conditions;
- syntax that may differ between Gaussian versions.

## Portability

All teaching knowledge needed by this skill is contained in `references/`. The package intentionally contains no original course files, page extracts, credentials, machine-specific paths, or external corpus dependency.

Use `scripts/audit_library.py` after any update. It checks knowledge-card uniqueness, required files, portability, and accidental provenance or private-data leakage.

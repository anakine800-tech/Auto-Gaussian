---
name: gaussian-ts-irc
description: Audit, prepare, pause, and analyze Gaussian 16 TS–Freq–IRC job families through the RTwin/PBS workflow. Use for reviewed single-guess, QST2, or QST3 transition-state calculations; exactly-one-imaginary-mode review; separately approved forward/reverse IRC plans; and endpoint evidence. It never infers research routes or submits IRC without explicit scientific review. All server work must remain under /home/user100/SDL.
---

# Gaussian TS–Freq–IRC

Use this Skill for the scientific layer only. Use `gaussian-rtwin-pbs` for the RTwin/PBS transport, hashing, submission, monitoring, retrieval, and scheduler safety; use `gaussian-view-rt-win` for reviewed structures and visible mode/geometry inspection.

## Safety and scope

- Keep every server project and scratch path within `/home/user100/SDL`; never override that root, overwrite, delete, or issue `qdel` without the core Skill's exact-confirmation process.
- Do not infer or silently change TS, Freq, IRC, endpoint, SCF, solvent, grid, charge, multiplicity, atom mapping, memory, or cores.
- Version 1 prepares and audits only. It deliberately has no SSH, PBS, `qsub`, `qdel`, or Gaussian execution command.
- Treat a first-order-saddle candidate as unvalidated until an explicit mode review and two separately reviewed IRC endpoint results exist.
- Refuse transition-metal, excited-state, broken-symmetry, multireference, periodic, ONIOM, and ambiguous atom-correspondence workflows unless a later revision explicitly adds them.

## Workflow

1. Require reviewed Cartesian inputs, an explicit atom map, intended forming/breaking/transferring pairs, routes, endpoint protocol, and resource tier. Read [references/protocol-contract.md](references/protocol-contract.md) before preparing a family.
2. Run `validate-inputs` for `single_guess`, `qst2`, or `qst3`. QST inputs must have exactly matching element order, charge, multiplicity, and declared atom map.
3. Create an immutable local family manifest. It contains hashes and approval states but neither submits nor writes to the server.
4. After the user approves the exact TS project, use `gaussian-rtwin-pbs` to stage and run the separately prepared TS/Freq input. Fetch the log and checkpoint before proceeding.
5. Run `analyze-ts` and create `mode-review` artifacts. Require normal TS/Freq termination, stationary-point evidence, exactly one raw negative frequency, and a complete displacement block.
6. Show the displacement table and declared-distance changes; obtain a scientific decision with `record-mode-decision --confirmed`. A distance projection is evidence, not automatic acceptance.
7. Only after exact IRC approval, use `plan-irc` to create two new, hash-bound PBS submission plans. Supply complete, verified forward/reverse routes—this Skill does not manufacture Gaussian IRC keywords.
8. Submit each direction through `gaussian-rtwin-pbs` into fresh projects, fetch results, then assess endpoints separately. Never submit a replacement automatically.

## Offline commands

```bash
TOOL="$HOME/.codex/skills/gaussian-ts-irc/scripts/ts_irc.py"

python3 "$TOOL" validate-inputs --mode qst2 \
  --reactant reactant.gjf --product product.gjf --atom-map atom_map.json
python3 "$TOOL" create-family --input-audit input_audit.json \
  --protocol approved_protocol.json --output family.json

python3 "$TOOL" analyze-ts ts_freq.log --output ts_freq_result.json
python3 "$TOOL" mode-review ts_freq_result.json --output-dir mode_review \
  --forming 1,7 --breaking 2,5
python3 "$TOOL" record-mode-decision ts_freq_result.json --decision accepted --confirmed

python3 "$TOOL" plan-irc family.json --ts-result ts_freq_result.json \
  --checkpoint ts.chk --forward-route '#p <approved route>' \
  --reverse-route '#p <approved route>' --forward-project abc_if \
  --reverse-project abc_ir --confirmed
```

`record-mode-decision` and `plan-irc` only change local artifacts. `plan-irc` refuses any status other than `accepted`, projects outside the PBS-safe naming rule, missing checkpoint hashes, or placeholder routes.

## Interpretation gates

- **G0**: approve chemical identities, atom map, coordinates, all routes, tiers, and fresh project names.
- **G1**: validate Cartesian input, atom order, charge/multiplicity, and hashes.
- **G2**: require exactly one raw imaginary frequency and review its displacement against the intended reaction coordinate.
- **G3**: approve the reviewed TS hash, checkpoint hash, each IRC route, resources, and two new project names.
- **G4**: require separately approved endpoint Opt/Freq jobs, zero imaginary frequencies at endpoints, and identity/connectivity/stereochemistry comparison before claiming a reaction path.

Do not label forward/reverse chemically until endpoint identity comparison. If anything fails, preserve evidence and report `incomplete`, `failed`, or `inconclusive`; never reinterpret it as a validated transition state.

## Resources

- `scripts/ts_irc.py`: deterministic offline validators, TS/Freq parser, displacement review artifacts, decision recording, and IRC plans.
- `references/protocol-contract.md`: required manifest fields, result schemas, stages, and non-default decisions.

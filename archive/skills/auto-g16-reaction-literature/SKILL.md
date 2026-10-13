---
name: auto-g16-reaction-literature
description: Retrieve, deduplicate, rank, and audit literature relevant to organic reaction mechanisms, active catalyst states, elementary steps, transition-state models, computed barriers, selectivity models, imaginary modes, and IRC evidence. Use when a reviewed reaction or hypothesis needs traceable Crossref/OpenAlex discovery, publisher and supporting-information verification, citation chaining, or an evidence-gap ledger before mechanism, TS-seed, asymmetric-catalysis, or Gaussian planning. This Skill discovers evidence but does not infer a mechanism, choose a computational protocol, validate a TS, or authorize calculations.
---

# Auto-G16 Reaction Literature

## Purpose

Turn an explicitly described reaction and set of hypotheses into a reproducible
literature search, a deduplicated screening queue, and a source-located evidence
ledger. Keep discovery, metadata screening, full-text review, and scientific
acceptance as separate states.

Read `references/search-and-evidence-protocol.md` before conducting a search or
reviewing a candidate publication.

## Boundaries

- Do not infer missing reactants, catalysts, active species, elementary steps,
  mechanism labels, stereochemical channels, charge, spin, method, solvent,
  TS algorithm, IRC settings, or low-frequency treatment.
- Treat Crossref, OpenAlex, search-engine snippets, titles, abstracts, keywords,
  and citation counts as discovery metadata only. They do not establish a
  mechanism, reported TS, method, barrier, normal mode, or IRC endpoint.
- Verify every accepted claim in a primary article or its supporting
  information. Record a page, figure, table, section, or stable locator and a
  concise paraphrase. Do not rely on a review article for candidate-specific
  computational details.
- Distinguish a direct precedent from a catalyst, substrate, transformation, or
  elementary-step analogy. Never silently transfer a literature protocol or
  active-catalyst assignment to the target reaction.
- A reported stationary point or one imaginary frequency is not a validated TS.
  Record whether the source reports normal-mode interpretation, IRC directions,
  and identified endpoints; leave missing evidence explicit.
- Do not download paywalled content by bypassing access controls, automate
  publisher scraping, or reproduce long copyrighted passages. Prefer metadata,
  lawful open access, user-provided papers, and short source-located paraphrases.
- Never create a Gaussian input, submit a job, access RTwin/PBS, or authorize any
  live action from this Skill. Keep `calculation_ready: false` and
  `no_submission_authorization: true` in all generated scientific artifacts.

## Workflow

Run the deterministic helper from the repository source of truth:

```bash
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" skills/auto-g16-reaction-literature/scripts/literature_search.py --help
```

Every command refuses to overwrite an existing file or retrieval directory.
The script uses only the Python standard library. Network access occurs only in
`retrieve`; all other commands are offline.

### 1. Create a reviewed intake

Write a `gaussian-reaction-literature-request/1` JSON artifact following the
reference protocol. Provide explicit search terms and synonyms rather than
asking the script to infer chemistry from a drawing or name. At minimum include:

- a stable request ID and scientific question;
- the reviewed transformation class and named reaction components;
- explicit catalyst, substrate, transformation, mechanism, and exact-phrase
  search terms as applicable;
- mechanism hypotheses as hypotheses, not facts;
- target evidence categories and known DOI seeds; and
- optional publication-year limits.

If identity, stereochemistry, catalyst state, or bond changes are unresolved,
record them as unresolved. Continue only with queries that remain scientifically
meaningful under those limits.

### 2. Build a query plan offline

```bash
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" skills/auto-g16-reaction-literature/scripts/literature_search.py \
  plan INTAKE.json --output search-plan.json
```

Review every generated lane. The planner combines only user-supplied terms and
generic evidence words. It creates exact-system, catalyst/transformation,
substrate/transformation, mechanism, TS/computational, analogy, review, and DOI
seed lanes when the intake supports them. Edit the intake and rebuild into a
fresh path if a query changes the chemistry or omits an important synonym.

### 3. Retrieve metadata

Use Crossref and OpenAlex for complementary discovery. Supply a Crossref contact
email with `--mailto` or `CROSSREF_MAILTO`; the artifact records only that a
contact was supplied, never the address. An OpenAlex API key is optional and is
read from `OPENALEX_API_KEY` by default. Never place a key in an intake, plan,
command transcript, or committed file.

```bash
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" skills/auto-g16-reaction-literature/scripts/literature_search.py \
  retrieve search-plan.json --output-dir retrieval-001 \
  --sources crossref,openalex --rows 20 --mailto "$CROSSREF_MAILTO"
```

The retrieval directory preserves raw JSON, SHA-256 hashes, sanitized request
metadata, query bindings, API status, and a manifest. Use a new directory for a
retry. Do not delete or mutate a partial retrieval to make it appear complete.
For a bounded smoke or replay, prefer `--query-ids q001,q021` over assuming the
first N plan entries cover known DOI seeds.

Use `--offline-fixture-dir` only for tests or replay. It never makes a network
request and expects files named `<query-id>.<source>.json`.

### 4. Deduplicate and rank for screening

```bash
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" skills/auto-g16-reaction-literature/scripts/literature_search.py \
  rank search-plan.json retrieval-001/retrieval.json \
  --output candidate-ledger.json --report screening-report.md
```

Ranking is transparent lexical triage. It does not use citation count as
scientific evidence and does not accept or reject a mechanism. Inspect false
positives, missing terminology, publication-type mismatches, and whether one
database failed. Add citation-chain and publisher-site candidates manually to a
reviewed intake or evidence ledger with provenance.

### 5. Create and complete the evidence review

```bash
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" skills/auto-g16-reaction-literature/scripts/literature_search.py \
  init-review candidate-ledger.json --output evidence-review.json --limit 20
```

For each retained paper, inspect the primary article and supporting information
where lawfully available. Record direct source locations for:

- proposed mechanism and alternative pathways;
- active catalyst state and its evidentiary basis;
- modeled elementary step and TS labels;
- atom inventory, charge, multiplicity, and model truncations;
- optimization/frequency, single-point, solvation, dispersion, thermochemistry,
  standard-state, temperature, and low-frequency statements;
- barrier definitions and common energy references;
- imaginary frequencies and explicit mode interpretation;
- IRC statements, directions, and structurally identified endpoints;
- selectivity model, competing channels, conformer coverage, and limitations;
  and
- coordinates or machine-readable structures in the SI.

Use `source_reports`, `not_found`, `source_ambiguous`, or `not_reviewed`. Do not
replace missing evidence with a plausible guess.

Validate the edited review before handing it downstream:

```bash
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" skills/auto-g16-reaction-literature/scripts/literature_search.py \
  validate-review evidence-review.json --output evidence-review-final.json
```

Treat the `init-review` output as an editable template. `validate-review`
refuses invalid claim/source combinations and writes a fresh hash-bound record;
it never overwrites the draft.

### 6. Hand off claims conservatively

- Bind a finalized `gaussian-reaction-literature-evidence/1` record back to
  `auto-g16-reaction-workflow`. If the exact reaction intake, species registry,
  condition model, or knowledge snapshot was not bound, keep downstream
  mechanism-support and TS-precedent promotion blocked.
- Give direct and analogous precedents to `auto-g16-asymmetric-catalysis` only
  as literature evidence with explicit analogy dimensions and gaps.
- Give a reviewed elementary-step hypothesis to a future mechanism-network or
  TS-seed Skill without turning it into a selected route.
- Use `auto-g16-ts-irc` only after a separate reviewed structure, protocol, and
  stage-specific approval exists. Literature-reported IRC is not local IRC
  validation.
- Use `auto-g16-rtwin-pbs` only after all existing scientific and exact live
  approval gates; nothing produced here authorizes input drafting or execution.
- Before formal TS input review, bind finalized literature evidence into the
  reaction-workflow scientific-maturity overlay. Its audit covers exact-system,
  catalyst/reaction, substrate-class, relevant BPh3/HBpin and pyridine lanes,
  active-state/ion-pair/Lewis-adduct coverage, computational TS/IRC/selectivity,
  both citation directions, and full-text/SI/coordinate coverage. User seeds
  remain hypotheses or verifiable seeds. Until the user confirms no obvious
  key-literature omission, formal mechanism support stays blocked. No direct
  precedent permits only reviewed minima work and at most one separate simple-
  tier pilot under the owning maturity gate.

## Required deliverables

Report the query lanes and date, databases reached or skipped, raw and unique
record counts, deduplication keys, screening tiers, direct/analogous distinction,
verified source locations, unresolved evidence gaps, retraction/correction
checks when applicable, and search limitations. State clearly when no direct
precedent was found; absence from a finite search is not proof of absence.

This Skill implements the query and evidence stages. It does not itself emit
`gaussian-reaction-mechanism-support/1` or `gaussian-ts-precedent-map/1`.
The separate offline mechanism-support and TS-precedent/de novo-planning
builders are owned by `auto-g16-reaction-workflow`. Missing direct precedent
remains an evidence gap; it is not automatically an exclusion from explicitly
reviewed novel-hypothesis exploration.

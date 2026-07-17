# Auto-G16 Main-Group Multiplicity-Family V1 Contract

## Purpose and scope

A family records two or more explicitly reviewed multiplicity/state branches for the same composition and a human-confirmed exact-structure or atom-mapping relationship. It is an offline planning and result-comparability record, not a conformer ensemble, calculation request, ground-state assignment, or submission authorization.

V1 remains limited to candidate-bound, single-reference main-group doublet or high-spin triplet minima. A doublet/quartet or singlet/triplet family retains every reviewed member, but only a member independently accepted by the electronic-state V1 contract may receive `v1_handoff_candidate`. Every other member remains `blocked_needs_specialist`; it is never dropped or converted into a supported state.

## Independent lineage

Each member owns a distinct candidate file, electronic-state review, member protocol, input-lineage record, and eventual result acceptance. The family builder rejects candidate, review, protocol, input, or result file-hash reuse across members. A protocol binds that member's candidate and review payloads plus the common comparison protocol; an input-lineage record binds that member's candidate and protocol. Unsupported members carry no input artifact hash and no V1 result acceptance.

Before a supported result can enter comparison, `bind-result` requires a sealed human source that explicitly binds the exact family plan, member protocol, member input lineage and input artifact hash, accepted result, observation artifact, raw result-source hash, common protocol, and comparison-settings hash. It emits a deterministic `member-result-lineage/1` artifact. Public validation rebuilds this artifact from its source and every transitive binding. A missing lineage produces `blocked_missing_proven_input_result_lineage`; cross-member, cross-protocol, cross-settings, cross-input, acceptance, observation, or raw-result substitutions fail closed even if a derived artifact is re-sealed.

The input-to-result association is only a confirmed supplied offline binding. Its provenance must explicitly set both transport and live-execution provenance claims to false. It neither proves nor implies that Auto-G16 transported, executed, or monitored the calculation.

The family source, plan, comparison protocol, member protocol, input lineage, member-result-lineage source, derived member-result lineage, result manifest, and comparison audit are closed V1 JSON contracts with SHA-256 payload seals. Source file hashes and payload hashes are preserved separately.

## Comparison boundary

The common comparison protocol must be explicitly human-approved and state the exact common reference, comparability statement, and settings hash. V1 records only electronic energy in hartree. It does not automatically compare thermal corrections, free energies, standard states, or low-frequency corrections.

The auditor never sorts energies, names a ground state, or infers multireference character from energy proximity. With fewer than two independently accepted, protocol-comparable V1 result lineages it emits `blocked_insufficient_supported_results`. Even with sufficient future V1-supported results, its maximum claim is `comparable_without_ordering_claim`.

## Exclusions and authority

Transition metals, spin crossing, MECP, cross-multiplicity conformer ensembles, automatic ground-state claims, thermochemistry mixing, and energy-proximity multireference inference are excluded. All artifacts retain `calculation_ready: false` and `no_submission_authorization: true`.

Use `scripts/multiplicity_family.py plan`, `bind-result`, `audit`, and `validate` offline. These commands contain no Gaussian, SSH, PBS, deployment, retry, cancellation, cleanup, or live-smoke surface.

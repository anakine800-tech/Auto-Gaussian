# Auto-G16 Knowledge Permissions and Export

Classify each record as `public`, `group_internal`, `project_restricted`, or
`confidential_unpublished`.

- Require an owner project for project-restricted records.
- Require explicit permitted principals for confidential unpublished records.
- Permit confidential export only as `metadata_redacted` or `no_export`.
- Never send unpublished structures, licensed full text, internal notes,
  credentials, or proprietary coordinates to an external search or embedding
  provider without explicit authority.
- Store only content hashes for lawful local objects. Use `metadata_only` or
  `external_reference_only` when local retention is not permitted.
- Preserve a local hash-bound decision record when a later export redacts
  fields or excludes records.

The validator checks policy consistency. W2B-1 exact queries default to public
records and can evaluate a declared offline principal for acceptance tests,
but do not authenticate users or protect files from someone who can read the
local store. Export, audit logging, and actual enforcement remain future
service work.

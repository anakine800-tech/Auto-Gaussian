PRAGMA foreign_keys = ON;
PRAGMA user_version = 1;

CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE records (
    record_type TEXT NOT NULL,
    record_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    schema_name TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    review_status TEXT NOT NULL,
    access_class TEXT NOT NULL,
    owner_project TEXT,
    permitted_principals_json TEXT NOT NULL,
    export_policy TEXT NOT NULL,
    created_at TEXT NOT NULL,
    source_path TEXT NOT NULL,
    PRIMARY KEY (record_type, record_id, revision_id),
    UNIQUE (payload_sha256)
) WITHOUT ROWID;

CREATE TABLE aliases (
    record_type TEXT NOT NULL,
    record_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    alias_type TEXT NOT NULL,
    alias_value TEXT NOT NULL,
    PRIMARY KEY (record_type, record_id, revision_id, alias_type, alias_value),
    FOREIGN KEY (record_type, record_id, revision_id)
        REFERENCES records (record_type, record_id, revision_id)
) WITHOUT ROWID;

CREATE TABLE external_identifiers (
    record_type TEXT NOT NULL,
    record_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    scheme TEXT NOT NULL,
    identifier_value TEXT NOT NULL,
    PRIMARY KEY (record_type, record_id, revision_id, scheme, identifier_value),
    FOREIGN KEY (record_type, record_id, revision_id)
        REFERENCES records (record_type, record_id, revision_id)
) WITHOUT ROWID;

CREATE TABLE issues (
    record_type TEXT NOT NULL,
    record_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    issue_class TEXT NOT NULL,
    issue_code TEXT NOT NULL,
    message TEXT NOT NULL,
    source_refs_json TEXT NOT NULL,
    PRIMARY KEY (record_type, record_id, revision_id, issue_class, issue_code, message),
    FOREIGN KEY (record_type, record_id, revision_id)
        REFERENCES records (record_type, record_id, revision_id)
) WITHOUT ROWID;

CREATE TABLE structure_keys (
    record_type TEXT NOT NULL CHECK (record_type = 'structure'),
    record_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    record_scope TEXT NOT NULL,
    formula TEXT,
    canonical_smiles TEXT,
    inchikey TEXT,
    parent_record_id TEXT,
    parent_revision_id TEXT,
    PRIMARY KEY (record_type, record_id, revision_id),
    FOREIGN KEY (record_type, record_id, revision_id)
        REFERENCES records (record_type, record_id, revision_id)
) WITHOUT ROWID;

CREATE TABLE method_facts (
    record_type TEXT NOT NULL CHECK (record_type = 'method'),
    record_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    field_name TEXT NOT NULL,
    fact_status TEXT NOT NULL,
    value_json TEXT NOT NULL,
    source_anchor_refs_json TEXT NOT NULL,
    PRIMARY KEY (record_type, record_id, revision_id, field_name),
    FOREIGN KEY (record_type, record_id, revision_id)
        REFERENCES records (record_type, record_id, revision_id)
) WITHOUT ROWID;

CREATE TABLE source_anchors (
    record_type TEXT NOT NULL CHECK (record_type = 'source'),
    record_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    anchor_id TEXT NOT NULL,
    locator_type TEXT NOT NULL,
    locator TEXT NOT NULL,
    object_sha256 TEXT,
    PRIMARY KEY (record_type, record_id, revision_id, anchor_id),
    FOREIGN KEY (record_type, record_id, revision_id)
        REFERENCES records (record_type, record_id, revision_id)
) WITHOUT ROWID;

CREATE TABLE source_claims (
    record_type TEXT NOT NULL CHECK (record_type = 'source'),
    record_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    category TEXT NOT NULL,
    statement_type TEXT NOT NULL,
    review_status TEXT NOT NULL,
    anchor_ids_json TEXT NOT NULL,
    PRIMARY KEY (record_type, record_id, revision_id, claim_id),
    FOREIGN KEY (record_type, record_id, revision_id)
        REFERENCES records (record_type, record_id, revision_id)
) WITHOUT ROWID;

CREATE TABLE links (
    record_type TEXT NOT NULL CHECK (record_type = 'link'),
    record_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    source_record_type TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    source_revision_id TEXT NOT NULL,
    source_payload_sha256 TEXT NOT NULL,
    target_record_type TEXT NOT NULL,
    target_record_id TEXT NOT NULL,
    target_revision_id TEXT NOT NULL,
    target_payload_sha256 TEXT NOT NULL,
    evidence_directness TEXT NOT NULL,
    scope TEXT NOT NULL,
    PRIMARY KEY (record_type, record_id, revision_id),
    FOREIGN KEY (record_type, record_id, revision_id)
        REFERENCES records (record_type, record_id, revision_id)
) WITHOUT ROWID;

CREATE TABLE objects (
    object_sha256 TEXT PRIMARY KEY,
    size_bytes INTEGER NOT NULL,
    media_type TEXT NOT NULL,
    present_local INTEGER NOT NULL CHECK (present_local IN (0, 1))
) WITHOUT ROWID;

CREATE TABLE record_object_refs (
    record_type TEXT NOT NULL,
    record_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    object_sha256 TEXT NOT NULL,
    ref_role TEXT NOT NULL,
    storage_status TEXT NOT NULL,
    PRIMARY KEY (record_type, record_id, revision_id, object_sha256, ref_role),
    FOREIGN KEY (record_type, record_id, revision_id)
        REFERENCES records (record_type, record_id, revision_id),
    FOREIGN KEY (object_sha256) REFERENCES objects (object_sha256)
) WITHOUT ROWID;

CREATE TABLE snapshot_members (
    snapshot_record_type TEXT NOT NULL CHECK (snapshot_record_type = 'snapshot'),
    snapshot_record_id TEXT NOT NULL,
    snapshot_revision_id TEXT NOT NULL,
    member_record_type TEXT NOT NULL,
    member_record_id TEXT NOT NULL,
    member_revision_id TEXT NOT NULL,
    member_payload_sha256 TEXT NOT NULL,
    member_review_status TEXT NOT NULL,
    member_access_class TEXT NOT NULL,
    PRIMARY KEY (
        snapshot_record_type,
        snapshot_record_id,
        snapshot_revision_id,
        member_record_type,
        member_record_id,
        member_revision_id
    ),
    FOREIGN KEY (snapshot_record_type, snapshot_record_id, snapshot_revision_id)
        REFERENCES records (record_type, record_id, revision_id)
) WITHOUT ROWID;

CREATE INDEX records_by_review ON records (review_status, record_type, record_id, revision_id);
CREATE INDEX records_by_access ON records (access_class, record_type, record_id, revision_id);
CREATE INDEX aliases_by_value ON aliases (alias_value, record_type, record_id, revision_id);
CREATE INDEX identifiers_by_value ON external_identifiers (scheme, identifier_value, record_type, record_id, revision_id);
CREATE INDEX links_by_relation ON links (relation_type, record_id, revision_id);
CREATE INDEX links_by_target ON links (target_record_type, target_record_id, target_revision_id);

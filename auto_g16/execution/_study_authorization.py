"""Native local Publisher identity review, never an effect selection."""
from contextlib import contextmanager
from contextvars import ContextVar

from . import _study_stage_session as native

_REVIEW = ContextVar('native-study-publisher-identity-review', default=None)


def selected_installation(session):
    session.require_action('authorize')
    value = _REVIEW.get()
    native._require(value is not None and value[0] is session)
    return value[1]


@contextmanager
def review_material(session, installation, authority, snapshot):
    """Hold exact installation identity only while native local readers run."""
    from auto_g16.transport import _program_rtwin as rtwin
    session.require_action('authorize')
    native._require(native._current() is session and _REVIEW.get() is None
        and session.publisher is None and session.run is None
        and rtwin._FIXED_PUBLISHER_INSTALLATION is None
        and type(installation) is rtwin._FixedPublisherInstallation)
    snapshot.assert_identity_closed()
    snapshot._assert_current_core(session.scope.stores['core'])
    native._require(installation.source_commit == session.context.facts.source_commit
        and installation.source_tree == session.context.facts.source_tree
        and authority.execution_snapshot_id == snapshot.program_execution_snapshot_id
        and authority.resolved_server_profile_id == snapshot.resolved_server_profile.resolved_server_profile_id)
    # Only the already-read original business records and original installed Q
    # can become this local reader's installation. A matching dataclass is not
    # authority to open arbitrary paths while SQLite handles are retained.
    from auto_g16.study import _xtb_files
    from auto_g16.study._model import digest, encode, plain
    publisher = _xtb_files.directory(session, 'publisher-root')
    prepared = _xtb_files.directory(session, 'prepared-root')
    native._require('snapshot.json' in prepared.seen
        and prepared.seen['snapshot.json'][1] == encode(snapshot._approval_semantics()))
    original = session.scope.stores['project'].inspect_creation_receipts(snapshot.workspace_binding.project_id)
    native._require(original['original_binding'] == snapshot.project_physical_binding.semantic_payload())
    def local_file(value, name):
        publisher.check()
        native._require(type(value) is rtwin._PublisherFileBinding
            and value.path == publisher.path + '/' + name and name in publisher.seen)
        signature, raw = publisher.seen[name]
        native._require(value.parent_chain == tuple(publisher.chain)
            and value.file_identity == signature[:2]
            and value.sha256 == digest(raw) and value.size_bytes == len(raw)
            and value.file_identity not in {tuple(b['file_identity']) for b in session._store_bindings.values()})
    local_file(installation.basis, 'v31-publisher-pilot-deployment.json')
    for evidence in installation.evidence:
        local_file(evidence, evidence.sha256)
    q = plain(session.context.facts.qualification_binding)
    native._require(installation.qualification == rtwin._PublisherFileBinding(q['path'],
        tuple(tuple(p) for p in q['parent_chain']), tuple(q['file_identity']), q['sha256'], q['size_bytes']))
    token = _REVIEW.set((session, installation))
    deployment = None
    original = None
    try:
        deployment = rtwin._read_publisher_deployment_identity(authority, snapshot)
        native._require(deployment.installation is installation)
        yield deployment
        session.require_action('authorize')
        deployment.assert_identity()
    except BaseException as error:
        original = error
        raise
    finally:
        try:
            if deployment is not None:
                try:
                    deployment.close()
                except BaseException as error:
                    if original is None:
                        raise
                    original.add_note('publisher review close unresolved: ' + type(error).__name__)
        finally:
            _REVIEW.reset(token)

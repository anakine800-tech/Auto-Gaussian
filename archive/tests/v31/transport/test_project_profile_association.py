"""Offline native-owner composition; no SSH process, scheduler or Gaussian."""
import base64
from dataclasses import asdict, fields, replace
from hashlib import sha256
import json
import os
from pathlib import Path
import unittest
import subprocess
import sys
_LOCAL_POPEN = subprocess.Popen
from unittest.mock import patch

from auto_g16 import execution, core
from auto_g16.execution import _project_association as identity
from auto_g16.execution import _project_association_source as owner
from auto_g16.execution import program
from auto_g16.execution.project_provisioning import _ProductionProvisioningJournal, _ProjectProvisioningService
from auto_g16.transport import _program_rtwin as rtwin, _driver
from tests.v31.transport import test_rtwin_successor_bridge as bridge_fixture
from tests.v31.transport import test_gaussian_successor as gaussian_fixture
from tests.v31.transport.test_gaussian_successor import TARGET_G16_PATH, TARGET_G16_SHA256, TARGET_G16_SIZE
from tests.v31.transport.test_gaussian_freq_resources import INPUT


def pin(path):
    path = Path(path).absolute()
    parents = []
    for parent in reversed(path.parents):
        info = parent.stat(); parents.append((info.st_dev, info.st_ino))
    info = path.stat(); raw = path.read_bytes()
    return rtwin._PublisherFileBinding(str(path), tuple(parents), (info.st_dev, info.st_ino), sha256(raw).hexdigest(), len(raw))


def profile_bytes(profile):
    result = {f.name: getattr(profile, f.name) for f in fields(profile)}
    result['config_files'] = [{'logical_name': k, 'content_base64': base64.b64encode(v).decode()} for k, v in profile.config_files]
    result['runtime_contents'] = {k: base64.b64encode(v).decode() for k, v in profile.runtime_contents.items()}
    return owner._raw(result)


class AssociationTests(unittest.TestCase):
    def setUp(self):
        self.b = bridge_fixture.ProductionBridgeTests(); self.b.setUp(); self.addCleanup(self.b.doCleanups)
        self.f = gaussian_fixture.GaussianSuccessorTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.o = gaussian_fixture.GaussianSuccessorTests(); self.o.setUp(); self.addCleanup(self.o.doCleanups)
        common = dict(production_generation=True, g16_path=TARGET_G16_PATH, g16_size=TARGET_G16_SIZE, g16_sha256=TARGET_G16_SHA256,
                      headroom_mib=4096, resource_memory_mb=16384)
        self.old_rows = self.o.qualified_case(startup='resource', input_raw=INPUT.replace(b'Freq', b'Opt'),
            base_profile_override=self.b.current_profile, **common)
        self.old = self.old_rows[0]
        base = replace(self.old, profile_revision=self.old.profile_revision + 1,
                       runtime_contents={k: v for k, v in self.old.runtime_contents.items() if k != identity.Q7})
        # Shared Q fixture first projects xTB, then the Gaussian fixture strips it.
        base = replace(base, platform_paths={**base.platform_paths, **{k:v for k,v in self.b.current_profile.platform_paths.items() if k in {'xtb_executable_path', 'xtb_data_path'}}},
                       runtime_contents={**base.runtime_contents, **{k:v for k,v in self.b.current_profile.runtime_contents.items() if k in {'xtb', 'xtb-runtime-data-manifest-v1.json'}}})
        self.rows = self.f.qualified_case(startup='freq-resource', input_raw=INPUT, base_profile_override=base, **common)
        self.current, self.target = self.rows[:2]
        self.old_target = execution.resolve_server_profile(self.old)
        self.root = self.f.root / 'association'; self.root.mkdir()
        path = self.root / 'creation.sqlite3'
        with _ProductionProvisioningJournal.create_new_recoverable(path, approved_root=self.root) as journal:
            old_service = _ProjectProvisioningService._from_project_attestor(
                attestor=rtwin._RTWinProjectAttestor(current_profile=self.old, target=self.old_target),
                target=self.old_target, journal=journal)
            self.project = self.f.store.load_project('project-1')
            self.original = old_service.provision_remote_project(project=self.project, target=self.old_target,
                remote_project_dir=self.f.remote_project_dir)
        self.journal = _ProductionProvisioningJournal.open_existing_readonly(path, approved_root=self.root)
        self.addCleanup(self.journal.close)
        self.service = _ProjectProvisioningService._from_project_attestor(
            attestor=rtwin._RTWinProjectAttestor(current_profile=self.current, target=self.target),
            target=self.target, journal=self.journal)
        def write(name, raw):
            p = self.root / name; p.write_bytes(raw); return pin(p)
        old_file = write('old.json', profile_bytes(self.old)); new_file = write('new.json', profile_bytes(self.current))
        source = Path(__file__).resolve().parents[3]
        names = ['auto_g16/execution/' + n + '.py' for n in ('_project_association', '_project_association_source', 'project_provisioning', 'program', 'models')]
        names += ['auto_g16/transport/' + n + '.py' for n in ('_program_rtwin', '_driver', '_bridge', 'program')]
        code = tuple(pin(source / n) for n in names)
        manifest = write('source.json', owner._raw({'commit': 'a'*40, 'tree': 'b'*40,
            'source_files': {n: {'sha256': p.sha256, 'size_bytes': p.size_bytes} for n, p in zip(names, code)}}))
        accept = write('acceptance.txt', b'offline synthetic exact-Q acceptance')
        readback = write('readback.txt', b'offline synthetic installation readback')
        review = write('review.json', owner._raw({'schema': 'project-profile-association-installation-review/1',
            'source_commit': 'a'*40, 'source_tree': 'b'*40, 'new_profile_id': self.target.resolved_server_profile_id,
            'qualification': self.target.runtime_identities[identity.Q8],
            'owner_acceptance': {'sha256': accept.sha256, 'size_bytes': accept.size_bytes},
            'installation_readback': {'sha256': readback.sha256, 'size_bytes': readback.size_bytes}}))
        output = self.root / 'published'
        self.installation = owner._AssociationInstallation(self.project.project_id, pin(path), old_file, new_file,
            manifest, review, accept, readback, 'a'*40, 'b'*40, code, str(output), pin(path).parent_chain)
        self.addCleanup(patch.stopall)
        patch.object(owner, '_FIXED_ASSOCIATION_INSTALLATION', self.installation).start()
        self.calls_before = len(self.b.wire.calls)
        self.journal_bytes = path.read_bytes()

    def issue(self):
        binding, source = self.service._associate_profile(project=self.project)
        patch.object(owner, '_FIXED_ASSOCIATION_SOURCE', source).start()
        return binding, source

    def test_owner_issue_idempotent_replay_and_old_journal_unchanged(self):
        binding, source = self.issue()
        self.assertEqual([op for op, _ in self.b.wire.calls[self.calls_before:]], ['OBSERVE_PROJECT'])
        self.assertEqual(self.service._associate_profile(project=self.project)[0], binding)
        self.assertEqual(len(self.b.wire.calls), self.calls_before + 1)
        self.assertNotEqual(binding.project_physical_binding_id, self.original.project_physical_binding_id)
        self.assertEqual(identity.decode_binding(binding.semantic_payload()), binding)
        with patch.object(_driver, '_resolve_closed_profile_authority', side_effect=AssertionError('historical driver')):
            with owner.replay(binding, source) as original:
                self.assertEqual(original, self.original)
        self.assertEqual(Path(self.journal._path).read_bytes(), self.journal_bytes)
        self.assertEqual(self.journal.load_binding(self.project.project_id), self.original)
        self.service._assert_owned_binding(binding=binding, project=self.project, target=self.target,
                                            remote_project_dir=binding.remote_project_dir)
        with self.assertRaises(ValueError):
            self.service._assert_owned_binding(binding=self.original, project=self.project, target=self.target,
                                                remote_project_dir=binding.remote_project_dir)

    def test_new_snapshot_roundtrip_and_collection_restore_without_observation(self):
        binding, source = self.issue()
        _, target, _, _, spec, _, _, material, previous = self.rows
        service = program._ProgramExecutionSnapshotService._for_production(project_provisioning=self.service, target=target)
        snapshot = service.prepare(self.f.store, attempt_id='attempt-1', calculation_plan_id='plan-1', resource_spec_id='resource-1',
            program_execution_spec=spec, project_physical_binding=binding, resolved_resource_request=previous.resolved_resource_request,
            resolved_server_profile=target, workspace_binding=self.f.workspace(), completion_rendering_material=material)
        self.assertNotEqual(snapshot.program_execution_snapshot_id, previous.program_execution_snapshot_id)
        self.assertEqual(program._decode_program_review_semantics(snapshot._approval_semantics()), snapshot)
        changed = json.loads(owner._raw(binding.project_profile_association))
        changed['payload']['issuer']['source_commit'] = 'c'*40
        changed['payload_sha256'] = identity.semantic_sha256(changed['payload'])
        changed['association_id'] = identity.semantic_id(identity.SCHEMA, changed['payload'])
        other = identity.make_binding(changed)
        self.assertNotEqual(other.project_physical_binding_id,binding.project_physical_binding_id)
        review = json.loads(owner._raw(snapshot._approval_semantics()))
        review['project_physical_binding'] = owner._plain(other.semantic_payload())
        with self.assertRaises(ValueError):program._decode_program_review_semantics(review)
        with self.assertRaises(ValueError):
            with owner.replay(other,source):pass
        # Persist an explicitly synthetic submitted state through public Core APIs.
        # This checks restoration only; it is not a submission/receipt qualification.
        self.f.store.record_submission_intent(snapshot.attempt_id, snapshot.effect_intent_id)
        self.f.store.record_submission_outcome(snapshot.attempt_id, snapshot.effect_intent_id, core.SubmissionOutcome.SUBMITTED)
        self.f.store.append_observation(core.Observation(observation_id='synthetic-submission', attempt_id=snapshot.attempt_id,
            observation_type=program._PROGRAM_EFFECT_RECEIPT_TYPE, data={'operation':'SUBMIT_QSUB_ONCE','outcome':'SUCCEEDED'}))
        before = len(self.b.wire.calls)
        restored = service.restore_for_collection(self.f.store, reviewed_semantics=snapshot._approval_semantics())
        self.assertEqual(restored, snapshot)
        self.assertEqual(len(self.b.wire.calls), before)
        from auto_g16.execution.readonly import ProgramReadSnapshot
        raw = owner._raw(snapshot._approval_semantics())
        self.assertEqual(ProgramReadSnapshot(content=raw, sha256=sha256(raw).hexdigest()).attempt_id, 'attempt-1')

    def test_partial_publication_never_reobserves(self):
        self.b.wire.fail_operation = 'OBSERVE_PROJECT'
        with self.assertRaises(Exception): self.issue()
        before = len(self.b.wire.calls)
        self.b.wire.fail_operation = None
        with self.assertRaisesRegex(ValueError, 'no completed registration'): self.issue()
        self.assertEqual(len(self.b.wire.calls), before)
        self.assertEqual(Path(self.journal._path).read_bytes(), self.journal_bytes)

    def test_missing_registry_tamper_and_symlink_are_refused(self):
        binding, source = self.issue()
        with patch.object(owner, '_FIXED_ASSOCIATION_SOURCE', None), self.assertRaises(ValueError):
            with owner.replay(binding): pass
        capture = Path(source.capture.path); renamed = capture.with_suffix('.original')
        capture.rename(renamed); capture.symlink_to(renamed)
        with self.assertRaises(Exception):
            with owner.replay(binding, source): pass
        self.assertEqual(len(self.b.wire.calls), self.calls_before + 1)

    def test_final_file_or_directory_fsync_failure_cannot_be_recovered(self):
        import stat
        real_write, real_sync = owner._Publication.write, os.fsync
        for directory in (False, True):
            with self.subTest(directory=directory):
                installation = replace(self.installation, output_directory=str(self.root / ('sync-' + str(directory))))
                active = [None]
                def write(publication, name, raw):
                    active[0] = name
                    try: return real_write(publication, name, raw)
                    finally: active[0] = None
                def sync(fd):
                    if active[0] == 'association.json' and stat.S_ISDIR(os.fstat(fd).st_mode) == directory:
                        raise OSError('injected final fsync failure')
                    return real_sync(fd)
                with patch.object(owner, '_FIXED_ASSOCIATION_INSTALLATION', installation), patch.object(owner, '_FIXED_ASSOCIATION_SOURCE', None):
                    with patch.object(owner._Publication, 'write', write), patch.object(os, 'fsync', sync), self.assertRaisesRegex(OSError, 'injected'):
                        self.service._associate_profile(project=self.project)
                    self.assertTrue((Path(installation.output_directory) / 'association.json').is_file())
                    before = len(self.b.wire.calls)
                    with self.assertRaisesRegex(ValueError, 'no completed registration'):
                        self.service._associate_profile(project=self.project)
                    self.assertEqual(len(self.b.wire.calls), before)

    def test_registered_operation_change_and_writable_service_reject(self):
        binding, source = self.issue()
        with _ProductionProvisioningJournal.open_existing(self.journal._path, approved_root=self.root) as writable:
            service = _ProjectProvisioningService._from_project_attestor(attestor=self.service._attestor,
                target=self.target, journal=writable)
            with self.assertRaisesRegex(ValueError, 'read-only'):
                service._assert_owned_binding(binding=binding, project=self.project, target=self.target,
                                              remote_project_dir=binding.remote_project_dir)
        Path(source.operation.path).write_bytes(b'changed operation')
        with self.assertRaises(Exception): self.service._associate_profile(project=self.project)
        self.assertEqual(len(self.b.wire.calls), self.calls_before + 1)

    def test_collection_rejects_wal_journal_before_sqlite_open_without_sidecars(self):
        from contextlib import ExitStack
        from types import SimpleNamespace
        import sqlite3
        from scripts import run_v31_publisher_pilot as controller
        rows = []
        for role, version in (('core',1),('approval',1),('transport',2)):
            path = self.root / (role + '.sqlite3')
            db = sqlite3.connect(path)
            try: db.execute('PRAGMA user_version=' + str(version))
            finally: db.close()
            file = pin(path); rows.append(controller._CollectionDatabaseBinding(role, file.path, file.parent_chain, file.file_identity))
        path = self.root / 'wal.sqlite3'
        with _ProductionProvisioningJournal.create_new_recoverable(path, approved_root=self.root) as db:
            db._connection.execute('PRAGMA journal_mode=WAL')
        self.assertEqual(path.read_bytes()[18:20], b'\x02\x02')
        file = pin(path); rows.append(controller._CollectionDatabaseBinding('project-journal', file.path, file.parent_chain, file.file_identity))
        run = SimpleNamespace(store_root=str(self.root), project_journal_root=None, databases=tuple(rows))
        before = {p.name for p in self.root.iterdir()}
        connect = sqlite3.connect
        def check(database, *args, **kwargs):
            self.assertNotIn(str(path), str(database), 'journal opened before rollback header check')
            return connect(database, *args, **kwargs)
        with patch.object(sqlite3, 'connect', check), ExitStack() as stack, self.assertRaisesRegex(ValueError, 'rollback-format'):
            controller._open_collection_stores(run, stack)
        self.assertEqual({p.name for p in self.root.iterdir()}, before)

    def test_production_receipt_detached_two_stage_registration(self):
        from tests.v31.transport._associated_workflow_fixture import run
        snapshot, registry = run(self)
        from tests.v31.transport._associated_loader_fixture import run as loader
        from tests.v31.transport._associated_workflow_fixture import read_registry
        from tests.v31.conformer.test_successor_freq import ROUTE, COORDS
        raw = ('%chk=gaussian.chk\n%mem=12GB\n%nprocshared=8\n' + ROUTE + '\n\nsynthetic\n\n0 1\n' +
               '\n'.join(('C' if i<4 else 'H')+' '+' '.join(map(str,p)) for i,p in enumerate(COORDS)) + '\n\n').encode()
        loader(self,snapshot,raw)
        loader(self,snapshot,raw,negative=True)
        expected = read_registry(registry)
        self.assertEqual(expected['data']['provenance']['parsed_result']['frequency_count'],36)
        script = """
import sys,os,json
from tests.v31.transport._associated_workflow_fixture import read_registry
def audit(event,args):
    if event.startswith(('socket.','subprocess.','os.exec','os.spawn','os.posix_spawn')):
        raise AssertionError('detached effect: '+event)
    if event=='open' and args[2] & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
        raise AssertionError('detached write')
sys.addaudithook(audit)
print(json.dumps(read_registry(sys.argv[1])))
"""
        with patch.object(subprocess,'Popen',_LOCAL_POPEN):
            child=subprocess.run([sys.executable,'-B','-c',script,str(registry)],capture_output=True,text=True,timeout=120)
        self.assertEqual(child.returncode,0,child.stderr)
        self.assertEqual(json.loads(child.stdout),expected)

    def test_profile_delta_rejects_config_runtime_and_revision_drift(self):
        identity.profile_delta(self.old_target, self.target)
        for current in (replace(self.current, profile_revision=self.old.profile_revision),
                        replace(self.current, config_files=((*self.current.config_files, ('extra', b'x')))),
                        replace(self.current, runtime_contents={**self.current.runtime_contents, 'extra': b'x'})):
            with self.assertRaises(ValueError): identity.profile_delta(self.old_target, execution.resolve_server_profile(current))


if __name__ == '__main__':
    unittest.main()

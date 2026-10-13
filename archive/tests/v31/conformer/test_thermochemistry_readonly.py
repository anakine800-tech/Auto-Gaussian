"""Synthetic pair persistence; no installed registry, kernel or live operation."""
from contextlib import contextmanager, ExitStack
from dataclasses import asdict, replace
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from auto_g16.conformer import thermochemistry_readonly as owner
from auto_g16.conformer import readonly
from auto_g16.thermochemistry.models import ThermodynamicEnsemble
from auto_g16.thermochemistry import _goodvibes, _service
from tests.v31.conformer import test_successor_freq as fixture
from tests.v31.transport.test_publisher_pilot_orchestration import file_binding


def destination(path):
    path = path.resolve()
    chain = tuple((p.stat().st_dev, p.stat().st_ino) for p in (*reversed(path.parents), path))
    return owner._NativeThermoDestination(path=str(path), directory_chain=chain)


@contextmanager
def no_computation():
    with ExitStack() as stack:
        for module, name in ((_goodvibes, '_load_goodvibes_kernels'),
                             (_goodvibes, 'functional_thermochemistry'),
                             (_service, '_finish_thermodynamic_ensemble')):
            stack.enter_context(patch.object(module, name, side_effect=AssertionError('read/save computed')))
        stack.enter_context(patch('auto_g16.thermochemistry._native_service._finish_thermodynamic_ensemble',
                                  side_effect=AssertionError('native aggregate called')))
        yield


class PairReadbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_fixture = fixture.NativeThermochemistryTests()
        cls.addClassCleanup(cls.source_fixture.doCleanups)
        cls.source_fixture.setUp()
        cls.pair = cls.source_fixture.build()
        cls.facts = cls.source_fixture.source_facts()
        cls.raw = owner.encode_native_thermodynamic_pair(cls.pair)
        cls.digest = sha256(cls.raw).hexdigest()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.readout = self.source_fixture.readout
        self.target = destination(self.root)

    def save(self):
        with fixture.inert_thermo_owners(), no_computation():
            return owner.save_native_thermodynamic_pair(
                self.readout, pair=self.pair, expected_sha256=self.digest, destination=self.target)

    def validate(self, pair, request=None):
        owner._validate_pair(pair, request or self.source_fixture.request,
                             self.source_fixture.profile, self.source_fixture.source, self.facts)

    def registry(self, binding):
        stages = []
        for stage, sources in (('opt', self.readout.optimization_sources), ('freq', self.readout.frequency_sources)):
            rows = []
            for index, source in enumerate(sources):
                snapshot = self.root / (stage + str(index) + '.json')
                snapshot.write_bytes(source.snapshot.content)
                rows.append(dict(member_id=source.member_id, original=asdict(source.original),
                    snapshot=asdict(file_binding(snapshot)), transport_root=source.transport_root,
                    revision=asdict(source.revision), parser_version=source.parser_version))
                # This fixture uses the /1 receipt-source shape, without an association.
                rows[-1]['original'].pop('project_association')
            stages.append(rows)
        freq = self.root / 'frequency-registration.json'
        freq.write_bytes(owner._canonical(dict(schema='auto-g16-freq-readout-registration/1',
            material=asdict(self.readout.material), optimization_sources=stages[0], frequency_sources=stages[1])))
        data = owner._canonical(dict(schema=owner._REGISTRATION,
            frequency_registration=asdict(file_binding(freq)), artifact=asdict(binding)))
        path = self.root / 'readback-registration.json'
        path.write_bytes(data)
        return path, sha256(data).hexdigest()

    def test_restart_roundtrip_has_no_kernel_and_retains_full_identity(self):
        before = owner.encode_native_thermodynamic_pair(self.pair)
        binding = self.save()
        self.assertEqual(Path(binding.path).read_bytes(), before)
        self.assertEqual(Path(binding.path).stat().st_mode & 0o777, 0o600)
        registration, digest = self.registry(binding)
        script = '''
import importlib.abc,json,sys
from pathlib import Path
class RejectKernel(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname == 'goodvibes' or fullname.startswith('goodvibes.'):
            raise AssertionError('GoodVibes imported on read')
sys.meta_path.insert(0,RejectKernel())
from tests.v31.conformer.test_thermochemistry_readonly import no_computation
from tests.v31.conformer.test_successor_freq import inert_thermo_owners
from auto_g16.conformer.thermochemistry_readonly import load_native_thermodynamic_readout,encode_native_thermodynamic_pair
with inert_thermo_owners(),no_computation():
    reader=load_native_thermodynamic_readout(Path(sys.argv[1]).read_bytes(),sys.argv[2])
    pair=reader.read()
    assert type(pair[1].source_member_ids) is tuple
    assert encode_native_thermodynamic_pair(pair)==Path(reader.artifact.path).read_bytes()
print(json.dumps([pair[0].conformer_ensemble_id,pair[1].thermodynamic_ensemble_id]))
'''
        process = subprocess.run([sys.executable, '-c', script, str(registration), digest],
                                 text=True, capture_output=True, timeout=180)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(json.loads(process.stdout), [self.pair[0].conformer_ensemble_id,
                                                     self.pair[1].thermodynamic_ensemble_id])
        self.assertEqual(owner.encode_native_thermodynamic_pair(self.pair), before)

    def test_format_model_and_request_recovery_rejects_coercion(self):
        data = json.loads(self.raw)
        request = owner._request_from_json(data['request'])
        self.assertIs(type(request['source_member_ids']), tuple)
        self.assertIs(type(request['member_policies']), tuple)
        q = owner._restore(data['qualified_conformer_ensemble'], owner.ConformerEnsemble,
                           'conformer-ensemble', self.source_fixture.profile)
        t = owner._restore(data['thermodynamic_ensemble'], ThermodynamicEnsemble, 'thermodynamic-ensemble')
        self.assertEqual(owner.encode_native_thermodynamic_pair((q, t)), self.raw)
        bad_audit = {**q.audit_evidence[-1], 'request_id': 'other'}
        fields = {key: getattr(q, key) for key in owner.signature(owner.ConformerEnsemble._create).parameters
                  if key != 'profile'}
        bad_q = owner.ConformerEnsemble._create(**{**fields, 'profile': self.source_fixture.profile,
                                                  'audit_evidence': (*q.audit_evidence[:-1], bad_audit)})
        with self.assertRaisesRegex(ValueError, 'complete eligibility audit'):
            owner.encode_native_thermodynamic_pair((bad_q, t))
        invalid = [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'\xef\xbb\xbf{}',
                   b'{}\n', b'{ "a":1}', b'{"a":1e999}', b'[] ']
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                owner._decode(raw, owner._CAP)
        with self.assertRaises(ValueError):
            owner._decode(b'{}', 1)
        for key in ('source_member_ids', 'member_policies'):
            bad = {**data['request'], key: 'anti'}
            with self.subTest(key=key), self.assertRaises(ValueError):
                owner._request_from_json(bad)
        for cls, name in ((owner.ConformerEnsemble, 'qualified_conformer_ensemble'),
                          (ThermodynamicEnsemble, 'thermodynamic_ensemble')):
            domain = 'conformer-ensemble' if cls is owner.ConformerEnsemble else 'thermodynamic-ensemble'
            for payload in ({**data[name]['payload'], 'extra': 1},
                            {**data[name]['payload'], 'schema_version': True}):
                with self.subTest(model=name, payload_keys=tuple(payload)), self.assertRaises(ValueError):
                    owner._restore({**data[name], 'payload': payload}, cls, domain, self.source_fixture.profile)

    def test_self_consistent_association_and_numeric_shape_splices_reject(self):
        q, t = self.pair
        def changed(**fields):
            return ThermodynamicEnsemble._create(**{**t._identity_payload(), **fields})
        cases = [changed(conformer_ensemble_id='other'), changed(conformer_ensemble_revision=True),
                 changed(source_member_ids=tuple(reversed(t.source_member_ids))),
                 changed(source_member_ids=t.source_member_ids[:1]),
                 changed(member_observations=t.member_observations[:1]),
                 changed(member_observations=tuple(reversed(t.member_observations))),
                 changed(temperature_k=310.0), changed(standard_state='1M'),
                 changed(thermochemistry_policy={**t.thermochemistry_policy, 'frequency_scaling_factor': .9}),
                 changed(gas_constant_binding={**t.gas_constant_binding, 'gas_constant_j_per_mol_k': 8.0}),
                 changed(method_compatibility_binding={**t.method_compatibility_binding, 'parser_version': '1.1.0'}),
                 changed(ensemble_treated_free_energy_hartree=True)]
        original = t.member_observations[0]
        for field, value in [('degeneracy', True), ('normalized_population', -0.1),
                             ('temperature_k', 301.0), ('source_provenance', t.member_observations[1]['source_provenance']),
                             ('raw_rrho', {**original['raw_rrho'], 'enthalpy_hartree': True}),
                             ('treated_qrrho', {**original['treated_qrrho'], 'enthalpy_treatment': 'other'})]:
            cases.append(changed(member_observations=({**original, field: value}, t.member_observations[1])))
        with no_computation():
            self.validate(self.pair)
            for index, bad in enumerate(cases):
                with self.subTest(index=index), self.assertRaises(ValueError):
                    self.validate((q, bad))

    def test_native_full_payload_and_identity_match_frozen_pre_extraction_builder(self):
        root = Path(__file__).resolve().parents[3]
        if not (root / '.git').exists():
            self.skipTest('source archive has no Git objects; frozen native differential is qualified locally')
        old = subprocess.check_output(['git', '-C', str(root), 'show',
            '23da24c4ec240dc65a0c2333780af9b6ea5f193a:auto_g16/thermochemistry/_native_service.py'])
        self.assertEqual(sha256(old).hexdigest(), 'e9e0a1ba2978fce13eaf83e38e311fc0859e20f5a4932fc3b117c8ad7719fe9c')
        path = self.root / 'frozen_native_service.py'
        path.write_bytes(old)
        spec = importlib.util.spec_from_file_location('auto_g16.thermochemistry._frozen_pair_baseline', path)
        baseline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(baseline)
        request = baseline._normalize_request(self.source_fixture.request)
        qualified = baseline._qualify_ensemble(self.source_fixture.source, self.source_fixture.profile, self.facts, request)
        with patch.object(_goodvibes, '_load_goodvibes_kernels', side_effect=self.source_fixture.thermo_fixture._fake_kernels):
            thermo = baseline._build_native_thermodynamic_ensemble(source_ensemble=self.source_fixture.source,
                qualified_ensemble=qualified, profile=self.source_fixture.profile, native_facts=self.facts, request=request)
        self.assertEqual(owner.encode_native_thermodynamic_pair((qualified, thermo)), self.raw)
        self.assertEqual(qualified.payload_sha256, self.pair[0].payload_sha256)
        self.assertEqual(thermo.payload_sha256, self.pair[1].payload_sha256)
        self.assertEqual(qualified.conformer_ensemble_id, self.pair[0].conformer_ensemble_id)
        self.assertEqual(thermo.thermodynamic_ensemble_id, self.pair[1].thermodynamic_ensemble_id)

    def test_wrong_digest_existing_targets_and_symlink_directory_have_zero_write(self):
        with self.assertRaises(ValueError):
            owner.save_native_thermodynamic_pair(self.readout, pair=self.pair,
                expected_sha256='0' * 64, destination=self.target)
        self.assertEqual(list(self.root.iterdir()), [])
        name = 'native-thermochemistry-' + self.digest + '.json'
        for kind in ('file', 'directory', 'symlink'):
            folder = self.root / kind
            folder.mkdir()
            leaf = folder / name
            if kind == 'file':
                leaf.write_bytes(b'keep')
            elif kind == 'directory':
                leaf.mkdir()
            else:
                leaf.symlink_to(self.root / 'missing')
            with patch.object(owner, '_replay', side_effect=AssertionError('existing target was replayed')):
                with self.subTest(kind=kind), self.assertRaises(FileExistsError):
                    owner.save_native_thermodynamic_pair(self.readout, pair=self.pair,
                        expected_sha256=self.digest, destination=destination(folder))
            if kind == 'file':
                self.assertEqual(leaf.read_bytes(), b'keep')
        link = self.root / 'alias'
        link.symlink_to(self.root, target_is_directory=True)
        bad = replace(self.target, path=str(link), directory_chain=(*self.target.directory_chain, self.target.directory_chain[-1]))
        with self.assertRaises(OSError):
            owner._Directory(bad)

    def test_file_and_source_drift_and_exit_failure_do_not_return_values(self):
        binding = self.save()
        reader = owner.NativeThermodynamicReadout(readout=self.readout, artifact=binding)
        with fixture.inert_thermo_owners(), no_computation():
            # A source failure at context exit invalidates an otherwise valid pair.
            replay = owner.frequency._replayed_frequency
            @contextmanager
            def failed_exit(*args, **kwargs):
                with replay(*args, **kwargs) as value:
                    yield value
                    raise ValueError('injected source exit')
            with patch.object(owner.frequency, '_replayed_frequency', failed_exit):
                with self.assertRaisesRegex(ValueError, 'injected source exit'):
                    reader.read()
            self.assertFalse(readonly._OPT_READ_LOCK.locked())
            bad_source = replace(self.readout, material=replace(self.readout.material, sha256='0' * 64))
            with self.assertRaises(ValueError):
                owner.NativeThermodynamicReadout(readout=bad_source, artifact=binding).read()
        forged = json.loads(self.raw)
        forged['thermodynamic_ensemble']['payload']['ensemble_treated_free_energy_hartree'] += 1.0
        payload = forged['thermodynamic_ensemble']['payload']
        identity, digest = owner._identified_payload('thermodynamic-ensemble', payload)
        forged['thermodynamic_ensemble'].update(thermodynamic_ensemble_id=identity, payload_sha256=digest)
        Path(binding.path).write_bytes(owner._canonical(forged))
        with self.assertRaises(ValueError):
            reader.read()

    def test_short_write_and_sync_failure_retain_unregistered_file(self):
        # Exercise the real descriptor writer without repeating source fixture replay.
        for failure in ('short', 'fsync', 'race'):
            folder = self.root / failure
            folder.mkdir()
            directory = owner._Directory(destination(folder))
            original_write = os.write
            calls = []
            def short_write(fd, raw):
                calls.append(len(raw))
                return original_write(fd, raw[:7]) if len(calls) == 1 else 0
            try:
                if failure == 'short':
                    with patch.object(owner.os, 'write', short_write), self.assertRaises(ValueError):
                        directory.write(self.raw, self.digest)
                elif failure == 'fsync':
                    with patch.object(owner.os, 'fsync', side_effect=OSError('sync failure')), self.assertRaises(OSError):
                        directory.write(self.raw, self.digest)
                else:
                    (folder / ('native-thermochemistry-' + self.digest + '.json')).write_bytes(b'race winner')
                    with self.assertRaises(FileExistsError):
                        directory.write(self.raw, self.digest)
            finally:
                descriptors = list(directory.fds)
                directory.close()
            files = list(folder.iterdir())
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].read_bytes(), self.raw[:7] if failure == 'short' else
                             self.raw if failure == 'fsync' else b'race winner')
            for fd in descriptors:
                with self.assertRaises(OSError):
                    os.fstat(fd)

    def test_busy_and_exact_type_fail_before_replay(self):
        with self.assertRaises(ValueError):
            owner.encode_native_thermodynamic_pair(list(self.pair))
        with self.assertRaises(ValueError):
            owner.NativeThermodynamicReadout(readout=object(), artifact=object())
        self.assertTrue(readonly._OPT_READ_LOCK.acquire(timeout=.01))
        try:
            with patch.object(readonly, '_OPT_READ_WAIT_SECONDS', .01), self.assertRaises(readonly.OptReadBusy):
                owner.save_native_thermodynamic_pair(self.readout, pair=self.pair,
                    expected_sha256=self.digest, destination=self.target)
        finally:
            readonly._OPT_READ_LOCK.release()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_save_keeps_snapshots_and_rejects_postwrite_source_exit(self):
        paths = {self.readout.material.path}
        for source in (*self.readout.optimization_sources, *self.readout.frequency_sources):
            paths.update((source.revision.path, source.original.core.path, source.original.transport.path))
        before = {p: sha256(Path(p).read_bytes()).hexdigest() for p in paths}
        original_snapshot = fixture.core.SQLiteRuntimeStore.read_snapshot
        original_replay = owner.frequency._replayed_frequency
        original_write = owner._Directory.write
        original_open = os.open
        active = [0]
        observed = []
        descriptors = []
        @contextmanager
        def tracked_snapshot(*args, **kwargs):
            with original_snapshot(*args, **kwargs) as store:
                active[0] += 1
                try:
                    yield store
                finally:
                    active[0] -= 1
        def tracked_open(*args, **kwargs):
            fd = original_open(*args, **kwargs)
            descriptors.append(fd)
            return fd
        def checked_write(directory, raw, digest):
            self.assertTrue(readonly._OPT_READ_LOCK.locked())
            self.assertEqual(active[0], 4)
            observed.append(directory.path)
            return original_write(directory, raw, digest)
        @contextmanager
        def failed_exit(*args, **kwargs):
            with original_replay(*args, **kwargs) as replay:
                yield replay
                raise ValueError('save postwrite source exit')
        with fixture.inert_thermo_owners(), no_computation(), \
                patch.object(fixture.core.SQLiteRuntimeStore, 'read_snapshot', tracked_snapshot), \
                patch.object(owner._Directory, 'write', checked_write), patch.object(owner.os, 'open', tracked_open):
            good = owner.save_native_thermodynamic_pair(self.readout, pair=self.pair,
                expected_sha256=self.digest, destination=self.target)
            self.assertEqual(Path(good.path).read_bytes(), self.raw)
            failed = self.root / 'failed'
            failed.mkdir()
            with patch.object(owner.frequency, '_replayed_frequency', failed_exit):
                with self.assertRaisesRegex(ValueError, 'save postwrite source exit'):
                    owner.save_native_thermodynamic_pair(self.readout, pair=self.pair,
                        expected_sha256=self.digest, destination=destination(failed))
        self.assertEqual(active[0], 0)
        self.assertFalse(readonly._OPT_READ_LOCK.locked())
        self.assertEqual(len(observed), 2)
        self.assertEqual(len(list(failed.iterdir())), 1)
        self.assertEqual(next(failed.iterdir()).read_bytes(), self.raw)
        self.assertEqual(before, {p: sha256(Path(p).read_bytes()).hexdigest() for p in paths})
        for fd in set(descriptors):
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_directory_replacement_and_startup_identity_are_rejected(self):
        folder = self.root / 'output'
        folder.mkdir()
        directory = owner._Directory(destination(folder))
        try:
            folder.rename(self.root / 'retained-original')
            folder.mkdir()
            with self.assertRaisesRegex(ValueError, 'directory replaced'):
                directory.write(self.raw, self.digest)
            self.assertEqual(list(folder.iterdir()), [])
        finally:
            directory.close()
        artifact = self.root / 'retained-pair.json'
        artifact.write_bytes(self.raw)
        registration, digest = self.registry(file_binding(artifact))
        raw = registration.read_bytes()
        with self.assertRaises(ValueError):
            owner.load_native_thermodynamic_readout(raw, '0' * 64)
        data = json.loads(raw)
        for key, value in [('schema', 'unknown'), ('extra', True),
                           ('frequency_registration', {**data['frequency_registration'], 'sha256': '0' * 64})]:
            changed = owner._canonical({**data, key: value})
            with self.subTest(field=key), self.assertRaises(ValueError):
                owner.load_native_thermodynamic_readout(changed, sha256(changed).hexdigest())


class PairPinCleanupTests(unittest.TestCase):
    def test_exit_and_constructor_close_errors_drain_remaining_descriptors(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / 'artifact.json'
            path.write_bytes(b'{}')
            binding = file_binding(path)
            original_open, original_close = os.open, os.close
            for construction_failure in (False, True):
                descriptors, closes = [], []
                def opened(*args, **kwargs):
                    fd = original_open(*args, **kwargs)
                    descriptors.append(fd)
                    return fd
                def closed(fd):
                    original_close(fd)
                    closes.append(fd)
                    if len(closes) == 1:
                        raise OSError('injected close error')
                candidate = replace(binding, sha256='0' * 64) if construction_failure else binding
                with patch.object(owner.os, 'open', opened), patch.object(owner.os, 'close', closed):
                    with self.assertRaisesRegex(OSError, 'injected close error'):
                        with owner._pinned(candidate):
                            pass
                self.assertEqual(set(closes), set(descriptors))
                for fd in descriptors:
                    with self.assertRaises(OSError):
                        os.fstat(fd)

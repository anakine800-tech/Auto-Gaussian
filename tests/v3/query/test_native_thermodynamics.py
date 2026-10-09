"""Saved native thermodynamics projection using complete synthetic sources only."""
from contextlib import contextmanager
from copy import copy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from auto_g16.conformer import thermochemistry_readonly as owner
from auto_g16.conformer.frequency_readonly import FreqReadout
from auto_g16.conformer.readonly import OptReadBusy
from auto_g16.core import RecordNotFoundError, RuntimeStoreSchemaError, SQLiteRuntimeStore
from auto_g16.query import NativeSource, NativeQueryService, QueryError
from auto_g16.query import native
from auto_g16.transport import TransportBoundaryError
from tests.v3.query.test_native import populate
from tests.v31.conformer import test_successor_freq as fixture
from tests.v31.conformer import test_thermochemistry_readonly as saved
from tests.v31.transport.test_publisher_pilot_orchestration import file_binding


def changed(record, **values):
    result = copy(record)
    for key, value in values.items():
        object.__setattr__(result, key, value)
    return result


class UnregisteredThermodynamicsTests(unittest.TestCase):
    def test_membership_only_and_closed_absence(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / 'core.sqlite3'
            populate(path)
            query = NativeQueryService((NativeSource(source_id='one', database=path),))
            before = path.read_bytes()
            with patch.object(NativeQueryService, '_attempt', side_effect=AssertionError('detail called')), \
                    patch.object(FreqReadout, 'read', side_effect=AssertionError('frequency called')), \
                    patch.object(owner.NativeThermodynamicReadout, 'read', side_effect=AssertionError('thermo called')):
                self.assertEqual(query.get_thermodynamics('one', 'attempt-1'), dict(
                    schema='auto-g16-native-thermodynamics-query/1', kind='thermodynamics', data=dict(
                        availability='unavailable', reason='not-registered', source_id='one', attempt_id='attempt-1',
                        selected_member_id=None, result=None)))
                for source, attempt, code in [('one', 'absent', 'not-found'), ('absent', 'attempt-1', 'not-found'),
                                              ('bad/path', 'attempt-1', 'invalid-id'), ('one', '../bad', 'invalid-id')]:
                    with self.subTest(source=source, attempt=attempt), self.assertRaisesRegex(QueryError, '^' + code + '$'):
                        query.get_thermodynamics(source, attempt)
            self.assertEqual(path.read_bytes(), before)

    def test_missing_store_is_unavailable_without_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / 'absent.sqlite3'
            query = NativeQueryService((NativeSource(source_id='one', database=path),))
            with self.assertRaisesRegex(QueryError, '^store-unavailable$'):
                query.get_thermodynamics('one', 'attempt-1')
            self.assertFalse(path.exists())


class NativeThermodynamicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = fixture.NativeThermochemistryTests()
        cls.addClassCleanup(cls.fixture.doCleanups)
        cls.fixture.setUp()
        cls.pair = cls.fixture.build()
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        cls.root = Path(temporary.name).resolve()
        artifact = cls.root / 'synthetic-pair.json'
        artifact.write_bytes(owner.encode_native_thermodynamic_pair(cls.pair))
        cls.reader = owner.NativeThermodynamicReadout(readout=cls.fixture.readout, artifact=file_binding(artifact))

    def source(self, index=0, **changes):
        selected = self.reader.readout.frequency_sources[index]
        values = dict(source_id='member-' + str(index), database=Path(selected.revision.path),
                      snapshots=(selected.snapshot,), freq_readout=self.reader.readout,
                      thermodynamic_readout=self.reader)
        return NativeSource(**{**values, **changes})

    def query(self, **changes):
        return NativeQueryService((self.source(**changes),))

    def project(self, pair=None):
        return native._thermodynamics_result(self.reader, self.pair if pair is None else pair, 'anti')

    def test_complete_read_once_after_exits_zero_compute_and_exact_values(self):
        source = self.source()
        query = NativeQueryService((source,))
        paths = {self.reader.artifact.path, self.reader.readout.material.path}
        for member in (*self.reader.readout.optimization_sources, *self.reader.readout.frequency_sources):
            paths.update((member.revision.path, member.original.core.path, member.original.transport.path))
        before = {p: sha256(Path(p).read_bytes()).hexdigest() for p in paths}
        original = owner.NativeThermodynamicReadout.read
        with fixture.inert_thermo_owners(), saved.no_computation(), \
                patch.object(owner.NativeThermodynamicReadout, 'read', autospec=True, side_effect=original) as read, \
                patch.object(FreqReadout, 'read', side_effect=AssertionError('nested Freq read')), \
                patch.object(NativeQueryService, '_read', side_effect=AssertionError('extra query snapshot')):
            result = query.get_thermodynamics(source.source_id, source.snapshots[0].attempt_id)
        read.assert_called_once_with(self.reader)
        self.assertFalse(owner.frequency.opt_reader._OPT_READ_LOCK.locked())
        self.assertEqual(set(result), {'schema', 'kind', 'data'})
        self.assertEqual(result['schema'], 'auto-g16-native-thermodynamics-query/1')
        self.assertEqual(result['kind'], 'thermodynamics')
        data = result['data']
        self.assertEqual(set(data), {'availability', 'reason', 'source_id', 'attempt_id', 'selected_member_id', 'result'})
        self.assertEqual((data['availability'], data['reason'], data['selected_member_id']), ('available', None, 'anti'))
        public = data['result']
        self.assertEqual(set(public), {'artifact_sha256', 'source_ensemble', 'qualified_ensemble', 'thermodynamic_ensemble',
            'sampling_profile', 'request', 'parameters', 'members', 'ensemble_treated_free_energy_hartree',
            'population_normalization', 'coverage_scope', 'scientific_acceptance'})
        q, t = self.pair
        self.assertEqual(public['artifact_sha256'], self.reader.artifact.sha256)
        self.assertEqual(public['qualified_ensemble'], dict(id=q.conformer_ensemble_id, payload_sha256=q.payload_sha256, revision=q.revision))
        self.assertEqual(public['thermodynamic_ensemble'], dict(id=t.thermodynamic_ensemble_id, payload_sha256=t.payload_sha256))
        self.assertEqual(public['ensemble_treated_free_energy_hartree'], t.ensemble_treated_free_energy_hartree)
        self.assertEqual(public['population_normalization'], dict(t.population_normalization))
        self.assertEqual(public['scientific_acceptance'], 'unavailable')
        self.assertEqual(set(public['parameters']), {'temperature_k', 'standard_state', 'entropy_method', 'enthalpy_method',
            'entropy_frequency_cutoff_cm1', 'enthalpy_frequency_cutoff_cm1', 'frequency_scaling_factor', 'zpe_scaling_factor',
            'moment_of_inertia', 'degeneracy_excludes_rotational_symmetry', 'functional_kernel_implementation_id'})
        for actual, expected in zip(public['members'], t.member_observations):
            self.assertEqual(set(actual), {'member_id', 'is_selected', 'degeneracy', 'degeneracy_rationale', 'inclusion_status',
                'raw_rrho', 'treated_qrrho', 'normalized_population', 'source'})
            for key in ('member_id', 'degeneracy', 'degeneracy_rationale', 'inclusion_status', 'normalized_population', 'raw_rrho', 'treated_qrrho'):
                self.assertEqual(actual[key], expected[key])
            self.assertEqual(set(actual['source']), {'optimization_attempt_id', 'frequency_attempt_id', 'optimization_parsed_result',
                'frequency_parsed_result', 'optimization_result_source', 'frequency_result_source', 'two_stage_minimum_authority_id'})
            for stage in ('optimization', 'frequency'):
                self.assertEqual(actual['source'][stage + '_parsed_result'], expected['source_provenance']['minimum_authority'][stage]['parsed_result'])
                self.assertEqual(actual['source'][stage + '_result_source'], expected['source_provenance']['minimum_authority'][stage]['result_source'])
        self.assertEqual([m['is_selected'] for m in public['members']], [True, False])
        encoded = json.dumps(result, allow_nan=False)
        for private in (*paths, 'transport_root', 'directory_chain', 'thermo_facts', 'source_provenance'):
            self.assertNotIn(private, encoded)
        self.assertEqual(before, {p: sha256(Path(p).read_bytes()).hexdigest() for p in paths})

    def test_registration_exact_complete_binding_and_no_startup_read(self):
        with patch.object(owner.NativeThermodynamicReadout, 'read', side_effect=AssertionError('startup read')):
            self.source()
            self.source(thermodynamic_readout=None)
            for changed_readout in (
                replace(self.reader.readout, material=replace(self.reader.readout.material, sha256='0' * 64)),
                replace(self.reader.readout, optimization_sources=self.reader.readout.optimization_sources[::-1]),
                replace(self.reader.readout, frequency_sources=self.reader.readout.frequency_sources[::-1]),
            ):
                with self.subTest(readout=changed_readout), self.assertRaisesRegex(QueryError, 'invalid-thermodynamic-registration'):
                    self.source(thermodynamic_readout=replace(self.reader, readout=changed_readout))
            for value in (object(), None):
                with self.assertRaises(QueryError):
                    self.source(freq_readout=value)
            class Subclass(owner.NativeThermodynamicReadout):
                pass
            with self.assertRaises(QueryError):
                self.source(thermodynamic_readout=Subclass(readout=self.reader.readout, artifact=self.reader.artifact))
            with self.assertRaises(QueryError):
                self.source(database=Path(self.reader.readout.frequency_sources[1].revision.path))
            with self.assertRaises(QueryError):
                self.source(snapshots=(self.reader.readout.frequency_sources[1].snapshot,))
            # An unpinned physical integer 1 and boolean True compare equal in dataclasses.
            material = replace(self.reader.readout.material, size_bytes=1)
            freq = replace(self.reader.readout, material=material)
            wrong = replace(freq, material=replace(material, size_bytes=True))
            self.assertEqual(freq, wrong)
            with self.assertRaisesRegex(QueryError, 'invalid-thermodynamic-registration'):
                self.source(freq_readout=freq, thermodynamic_readout=replace(self.reader, readout=wrong))

    def test_foreign_source_attempt_rejects_before_read(self):
        query = NativeQueryService((self.source(), self.source(1)))
        with patch.object(owner.NativeThermodynamicReadout, 'read', side_effect=AssertionError('read foreign')) as read:
            for source, attempt in [('member-0', 'attempt-4'), ('member-1', 'attempt-2'), ('missing', 'attempt-2')]:
                with self.subTest(source=source, attempt=attempt), self.assertRaisesRegex(QueryError, '^not-found$'):
                    query.get_thermodynamics(source, attempt)
        read.assert_not_called()

    def test_second_member_retains_canonical_saved_order(self):
        source = self.source(1)
        with patch.object(owner.NativeThermodynamicReadout, 'read', return_value=self.pair) as read:
            data = NativeQueryService((source,)).get_thermodynamics(source.source_id, source.snapshots[0].attempt_id)['data']
        read.assert_called_once()
        self.assertEqual(data['selected_member_id'], 'gauche')
        self.assertEqual([m['member_id'] for m in data['result']['members']], ['anti', 'gauche'])
        self.assertEqual([m['is_selected'] for m in data['result']['members']], [False, True])

    def test_old_source_project_list_and_detail_unchanged(self):
        source = self.source()
        old = NativeQueryService((replace(source, thermodynamic_readout=None),))
        new = NativeQueryService((source,))
        with fixture.inert_thermo_owners(), saved.no_computation(), \
                patch.object(owner.NativeThermodynamicReadout, 'read', side_effect=AssertionError('old API read thermo')):
            self.assertEqual(old.list_sources(), new.list_sources())
            projects = old.list_projects()
            self.assertEqual(projects, new.list_projects())
            project = projects['data']['items'][0]['project_id']
            self.assertEqual(old.list_attempts(source.source_id, project), new.list_attempts(source.source_id, project))
            self.assertEqual(old.get_attempt(source.source_id, source.snapshots[0].attempt_id),
                             new.get_attempt(source.source_id, source.snapshots[0].attempt_id))

    def test_projection_rejects_malformed_closed_numeric_and_member_values(self):
        q, t = self.pair
        row = t.member_observations[0]
        variants = [changed(t, member_observations=t.member_observations[::-1]),
                    changed(t, member_observations=(row, row)),
                    changed(t, member_observations=t.member_observations[:1]),
                    changed(t, ensemble_treated_free_energy_hartree=float('nan')),
                    changed(t, temperature_k=True), changed(t, temperature_k=0),
                    changed(t, population_normalization={**t.population_normalization, 'extra': 0})]
        for field, value in [('member_id', 'bad/path'), ('degeneracy', True), ('normalized_population', float('inf')),
                             ('normalized_population', 1.01), ('normalized_population', -.01), ('inclusion_status', 'other'),
                             ('raw_rrho', {**row['raw_rrho'], 'extra': 0}), ('raw_rrho', {}),
                             ('treated_qrrho', {**row['treated_qrrho'], 'enthalpy_hartree': True}),
                             ('treated_qrrho', {**row['treated_qrrho'], 'enthalpy_treatment': 'other'})]:
            variants.append(changed(t, member_observations=({**row, field: value}, t.member_observations[1])))
        for value in variants:
            with self.subTest(value=value), self.assertRaises(QueryError):
                self.project((q, value))
        for field, value in [('revision', True), ('payload_sha256', 'A' * 64), ('conformer_ensemble_id', 'bad/path')]:
            with self.subTest(field=field), self.assertRaises(QueryError):
                self.project((changed(q, **{field: value}), t))

    def test_registered_errors_are_bounded_no_fallback(self):
        schema_io = RuntimeStoreSchemaError('private database')
        schema_io.__cause__ = PermissionError('private path')
        transport_io = TransportBoundaryError('private transport')
        transport_io.__cause__ = FileNotFoundError('private path')
        cases = [(OptReadBusy('private'), 'store-unavailable'), (FileNotFoundError('private'), 'store-unavailable'),
            (schema_io, 'store-unavailable'), (transport_io, 'store-unavailable'),
            (RecordNotFoundError('private'), 'invalid-evidence'), (RuntimeStoreSchemaError('private'), 'invalid-evidence'),
            (ValueError('private'), 'invalid-evidence'), (KeyError('private'), 'invalid-evidence'),
            (RuntimeError('private'), 'internal-error'),
            (TransportBoundaryError('publisher-not-qualified: installed bytes/identity drift'), 'invalid-evidence'),
            (TransportBoundaryError('completion owner is busy'), 'store-unavailable'),
            (TransportBoundaryError('program transport store must be a strict descendant of an existing root'), 'internal-error'),
            (TransportBoundaryError('unknown private path'), 'internal-error')]
        for code, expected in [(sqlite3.SQLITE_CORRUPT, 'invalid-evidence'), (sqlite3.SQLITE_BUSY, 'store-unavailable')]:
            error = sqlite3.DatabaseError('private')
            error.sqlite_errorcode = code
            cases.append((error, expected))
        query = self.query()
        for error, code in cases:
            with self.subTest(error=type(error), code=code), patch.object(owner.NativeThermodynamicReadout, 'read', side_effect=error) as read:
                with self.assertRaises(QueryError) as caught:
                    query.get_thermodynamics('member-0', 'attempt-2')
                self.assertEqual(str(caught.exception), code)
                self.assertIsNone(caught.exception.__cause__)
                read.assert_called_once()

    def test_real_artifact_hash_drift_and_source_exit_failure_block_projection(self):
        path = self.root / 'synthetic-drifted.json'
        path.write_bytes(Path(self.reader.artifact.path).read_bytes().replace(b'grimme', b'Grimme', 1))
        binding = replace(file_binding(path), sha256=self.reader.artifact.sha256)
        query = self.query(thermodynamic_readout=replace(self.reader, artifact=binding))
        with patch.object(native, '_thermodynamics_result', side_effect=AssertionError('premature DTO')):
            with self.assertRaisesRegex(QueryError, '^invalid-evidence$'):
                query.get_thermodynamics('member-0', 'attempt-2')
        original = owner._replay
        @contextmanager
        def failed_exit(*args, **kwargs):
            with original(*args, **kwargs) as result:
                yield result
                raise ValueError('private source exit failure')
        with fixture.inert_thermo_owners(), saved.no_computation(), patch.object(owner, '_replay', failed_exit), \
                patch.object(native, '_thermodynamics_result', side_effect=AssertionError('premature DTO')):
            with self.assertRaisesRegex(QueryError, '^invalid-evidence$'):
                self.query().get_thermodynamics('member-0', 'attempt-2')
        self.assertFalse(owner.frequency.opt_reader._OPT_READ_LOCK.locked())


class ThermodynamicsErrorMappingTests(unittest.TestCase):
    def test_explicit_gaussian_receipt_and_store_association_errors_are_evidence(self):
        reasons = (
            'mixed V30/successor execution or Result generation',
            'Gaussian source requires a supported pure stage adapter',
            'Gaussian completion source is not unique',
            'Gaussian source input/log inventory differs',
            'read-only receipt proof requires persisted success',
            'read-only receipt proof was invalidated',
            'historical runtime attestation differs or is missing',
            'captured bytes differ from persisted FETCH',
            'completion assessment or prefix is corrupt',
            'persisted successor receipt is malformed',
        )
        for reason in reasons:
            with self.subTest(reason=reason):
                self.assertEqual(native._thermodynamics_error(TransportBoundaryError(reason)), 'invalid-evidence')

    def test_ambiguous_or_new_owner_reason_is_not_guessed(self):
        for reason in ('program transport store must be a strict descendant of an existing root',
                       'program transport store parent must be a real directory',
                       'new owner condition', 'Gaussian completion source is not unique with extra private text'):
            with self.subTest(reason=reason):
                self.assertEqual(native._thermodynamics_error(TransportBoundaryError(reason)), 'internal-error')
        error = RuntimeError('unexpected wrapper')
        error.__cause__ = OSError('private cause')
        self.assertEqual(native._thermodynamics_error(error), 'internal-error')

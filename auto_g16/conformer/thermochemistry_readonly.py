"""Private, fixed-byte pair persistence; no thermochemistry is computed here."""
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from hashlib import sha256
from inspect import signature
import json
import os
import re
import stat

from auto_g16.thermochemistry.models import (
    ThermodynamicEnsemble, _identified_payload, _plain_value,
)
from auto_g16.thermochemistry._native_service import (
    _normalize_request, _qualify_ensemble, _native_method, _native_member_binding, _eligibility_audit,
)
from auto_g16.thermochemistry._service import (
    _require, _closed, _finite, _policy_identity, _implementation_binding,
    _standard_state_binding, _POPULATION_TOLERANCE,
)
from auto_g16.transport._program_rtwin import _PublisherFileBinding, _PinnedPublisherFile
from . import frequency_readonly as frequency
from .models import ConformerEnsemble
from ._successor_thermo_source import _native_input_facts_from_replay

_SCHEMA = 'auto-g16-native-thermochemistry-pair/1'
_REGISTRATION = 'auto-g16-native-thermochemistry-readout-registration/1'
_CAP = 16 * 1024 * 1024
_GAS_CONSTANT = 8.3144621
_J_TO_AU = 4.184 * 627.509541 * 1000.0
_BINDING_KEYS = {'path', 'parent_chain', 'file_identity', 'sha256', 'size_bytes'}
_RAW_KEYS = {'electronic_energy_hartree', 'zero_point_energy_hartree', 'enthalpy_hartree',
             'entropy_hartree_per_kelvin', 'gibbs_free_energy_hartree'}
_TREATED_NUMBERS = {'enthalpy_hartree', 'entropy_hartree_per_kelvin', 'gibbs_free_energy_hartree'}


def _canonical(value):
    return json.dumps(_plain_value(value), ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(',', ':')).encode('utf-8')


def _same(left, right, label):
    # Canonical bytes distinguish bool/int and other equality coercions.
    _require(_canonical(left) == _canonical(right), label + ' differs')


def _digest(value):
    _require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None,
             'invalid expected digest')
    return value


def _decode(raw, cap):
    _require(type(raw) is bytes and 0 < len(raw) <= cap, 'invalid pair bytes/size')
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, 'duplicate pair key')
            result[key] = value
        return result
    def constant(_value):
        raise ValueError('non-finite JSON constant')
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
    _same_bytes = _canonical(value)
    _require(_same_bytes == raw, 'non-canonical pair bytes')
    return value


def _identity(record, cls, domain):
    _require(type(record) is cls, 'pair record type differs')
    payload = record._identity_payload()
    _require(type(record.schema_version) is int and record.schema_version == 1,
             'pair model version differs')
    identity, digest = _identified_payload(domain, payload)
    key = domain.replace('-', '_') + '_id'
    _require(getattr(record, key) == identity and record.payload_sha256 == digest,
             'pair model identity is stale')
    return {key: identity, 'payload_sha256': digest, 'payload': payload}


def encode_native_thermodynamic_pair(pair):
    """Canonical candidate bytes only; this does not issue a trusted digest."""
    _require(type(pair) is tuple and len(pair) == 2, 'pair must be exact two-tuple')
    qualified, thermo = pair
    first = _identity(qualified, ConformerEnsemble, 'conformer-ensemble')
    second = _identity(thermo, ThermodynamicEnsemble, 'thermodynamic-ensemble')
    _require(type(thermo.source_member_ids) is tuple, 'member identities are not immutable')
    _require(bool(qualified.audit_evidence), 'eligibility audit missing')
    audit = qualified.audit_evidence[-1]
    _require(audit.get('stage') == 'native_thermochemistry_eligibility', 'eligibility audit missing')
    request = _normalize_request(audit['request_payload'])
    _same(request, audit['request_payload'], 'normalized request')
    _same(audit, _eligibility_audit(request), 'complete eligibility audit')
    raw = _canonical({'schema': _SCHEMA, 'request': request,
                      'qualified_conformer_ensemble': first, 'thermodynamic_ensemble': second})
    _require(len(raw) <= _CAP, 'pair exceeds file cap')
    return raw


def _request_from_json(value):
    _require(type(value) is dict, 'invalid saved request')
    supplied = dict(value)
    for key in ('source_member_ids', 'member_policies'):
        _require(type(supplied.get(key)) is list, 'request member array missing')
        supplied[key] = tuple(supplied[key])
    normalized = _normalize_request(supplied)
    _same(normalized, value, 'saved request')
    return normalized


def _restore(envelope, cls, domain, profile=None):
    key = domain.replace('-', '_') + '_id'
    row = _closed(envelope, {key, 'payload_sha256', 'payload'}, 'saved model')
    keys = set(cls.__dataclass_fields__) - {key, 'payload_sha256'}
    payload = _closed(row['payload'], keys, 'saved model payload')
    if cls is ConformerEnsemble:
        args = {k: payload[k] for k in signature(cls._create).parameters if k != 'profile'}
        model = cls._create(profile=profile, **args)
    else:
        _require(type(payload['source_member_ids']) is list, 'saved member ids are not an array')
        args = {k: v for k, v in payload.items() if k != 'schema_version'}
        args['source_member_ids'] = tuple(args['source_member_ids'])
        model = cls._create(**args)
    _same(_identity(model, cls, domain), row, 'restored complete model')
    return model


def _policy_bindings(thermo, policy):
    identity, digest = _policy_identity(policy)
    implementation_id, implementation = _implementation_binding(policy)
    expected = dict(
        temperature_k=float(policy['temperature_k']), standard_state=policy['standard_state'],
        standard_state_binding=_standard_state_binding(policy, _GAS_CONSTANT),
        gas_constant_binding={'gas_constant_j_per_mol_k': _GAS_CONSTANT,
            'joule_per_hartree_mol': _J_TO_AU,
            'gas_constant_hartree_per_mol_k': _GAS_CONSTANT / _J_TO_AU,
            'unit_convention': 'per_mole_hartree_kelvin'},
        thermochemistry_policy_id=identity, thermochemistry_policy_payload_sha256=digest,
        thermochemistry_policy=policy, functional_kernel_implementation_id=implementation_id,
        functional_kernel_implementation_binding=implementation,
        low_frequency_treatment={
            'entropy_method': policy['qrrho_entropy_method'],
            'entropy_frequency_cutoff_cm1': policy['entropy_frequency_cutoff_cm1'],
            'entropy_damping_function': policy['entropy_damping_function'],
            'enthalpy_method': policy['qrrho_enthalpy_method'],
            'enthalpy_frequency_cutoff_cm1': policy['enthalpy_frequency_cutoff_cm1'],
            'enthalpy_damping_function': policy['enthalpy_damping_function'],
            'frequency_scaling_factor': policy['frequency_scaling_factor'],
            'zpe_scaling_factor': policy['zpe_scaling_factor'],
            'moment_of_inertia': policy['moment_of_inertia'],
            'scheme_identity': 'goodvibes-4.3.0-functional-grimme-head-gordon',
            'degeneracy_excludes_rotational_symmetry': policy['degeneracy_excludes_rotational_symmetry'],
        })
    for key, value in expected.items():
        _same(getattr(thermo, key), value, key)


def _numeric_shape(thermo):
    """Validate stored shapes/ranges; never derive new thermochemical values."""
    for row in thermo.member_observations:
        raw = _closed(row['raw_rrho'], _RAW_KEYS, 'raw RRHO')
        treated = _closed(row['treated_qrrho'], _TREATED_NUMBERS | {'entropy_treatment', 'enthalpy_treatment'}, 'treated qRRHO')
        for value in raw.values():
            _finite(value, 'raw RRHO value')
        for key in _TREATED_NUMBERS:
            _finite(treated[key], 'treated qRRHO value')
        _require(treated['entropy_treatment'] == 'grimme' and treated['enthalpy_treatment'] == 'head_gordon',
                 'stored treatment differs')
        population = _finite(row['normalized_population'], 'stored population')
        _require(0 <= population <= 1, 'stored population outside range')
        weight = _closed(row['relative_statistical_weight'], {'log_value', 'representation'}, 'stored weight')
        _finite(weight['log_value'], 'stored log weight')
        _require(weight['representation'] == 'natural_log_relative_to_reference_gibbs', 'stored weight representation differs')
    partition = _closed(thermo.partition_evidence, {
        'reference_member_id', 'reference_gibbs_hartree', 'representation', 'log_scale',
        'scaled_relative_partition_function', 'log_relative_partition_function'}, 'stored partition')
    _require(partition['reference_member_id'] in thermo.source_member_ids
             and partition['representation'] == 'stable_logsumexp', 'stored reference differs')
    for key in ('reference_gibbs_hartree', 'log_scale', 'log_relative_partition_function'):
        _finite(partition[key], key)
    _finite(partition['scaled_relative_partition_function'], 'scaled partition', positive=True)
    norm = _closed(thermo.population_normalization, {
        'population_sum', 'absolute_error', 'numeric_tolerance', 'status', 'tolerance_purpose'}, 'stored normalization')
    _finite(norm['population_sum'], 'stored population sum', positive=True)
    error = _finite(norm['absolute_error'], 'stored normalization error')
    _same(norm['numeric_tolerance'], _POPULATION_TOLERANCE, 'numeric tolerance')
    _require(0 <= error <= _POPULATION_TOLERANCE and norm['status'] == 'normalized'
             and norm['tolerance_purpose'] == 'floating_point_normalization_only_not_scientific_selection',
             'stored normalization status differs')
    _finite(thermo.ensemble_treated_free_energy_hartree, 'stored ensemble free energy')


def _validate_pair(pair, request, profile, source, facts):
    qualified, thermo = pair
    _identity(qualified, ConformerEnsemble, 'conformer-ensemble')
    _identity(thermo, ThermodynamicEnsemble, 'thermodynamic-ensemble')
    expected = _qualify_ensemble(source, profile, facts, request)
    _same(qualified._identity_payload(), expected._identity_payload(), 'qualified revision')
    _require(thermo.conformer_ensemble_id == qualified.conformer_ensemble_id
             and thermo.conformer_ensemble_payload_sha256 == qualified.payload_sha256,
             'thermodynamic source differs')
    _same(thermo.conformer_ensemble_revision, qualified.revision, 'thermodynamic source revision')
    _require(type(thermo.source_member_ids) is tuple
             and thermo.source_member_ids == qualified.thermodynamic_eligible_members,
             'thermodynamic members differ')
    _require(len(thermo.member_observations) == len(facts['members']), 'member observation count differs')
    method = _native_method(request)
    method_id, _ = _identified_payload('native-thermochemistry-method', method)
    _same(thermo.method_compatibility_binding, method, 'method binding')
    _same(thermo.method_compatibility_id, method_id, 'method identity')
    for row, source_row, member_policy in zip(thermo.member_observations, facts['members'], request['member_policies']):
        association = _native_member_binding(qualified, source_row, member_policy, request)
        _closed(row, set(association) | {'raw_rrho', 'treated_qrrho', 'relative_statistical_weight', 'normalized_population'},
                'stored member observation')
        _same({key: row[key] for key in association}, association, 'member source/policy association')
    _policy_bindings(thermo, request['thermochemistry_policy'])
    _numeric_shape(thermo)


@contextmanager
def _locked(readout):
    _require(type(readout) is frequency.FreqReadout, 'requires exact FreqReadout')
    lock = frequency.opt_reader._OPT_READ_LOCK
    if not lock.acquire(timeout=frequency.opt_reader._OPT_READ_WAIT_SECONDS):
        raise frequency.opt_reader.OptReadBusy('two-stage read slot is busy')
    try:
        yield
    finally:
        lock.release()


@contextmanager
def _replay(readout):
    with frequency._replayed_frequency(readout) as (profile, _prior, source, opts, freqs):
        facts = _native_input_facts_from_replay(profile, source, opts, freqs)
        yield profile, source, facts


@contextmanager
def _pinned(binding, cap=_CAP):
    pin = _PairPin(binding, cap)
    try:
        yield pin
    finally:
        try:
            pin._read_and_check()
        finally:
            pin.close()


def _close_descriptors(fds):
    errors = []
    while fds:
        try:
            os.close(fds.pop())
        except BaseException as error:
            errors.append(error)
    if errors:
        raise errors[0]


class _PairPin(_PinnedPublisherFile):
    """Retain the existing read checks, drain all fds on any close failure."""
    def close(self):
        _close_descriptors(self.fds)


@dataclass(frozen=True, kw_only=True)
class _NativeThermoDestination:
    path: str
    directory_chain: tuple[tuple[int, int], ...]


class _Directory:
    def __init__(self, destination):
        self.fds = []
        _require(type(destination) is _NativeThermoDestination, 'invalid destination binding')
        self.path, self.chain = destination.path, destination.directory_chain
        _require(type(self.path) is str and self.path.startswith('/') and len(self.path.encode()) <= 4096
                 and not any(c in self.path for c in '\x00\r\n'), 'invalid destination path')
        self.parts = self.path[1:].split('/')
        _require(all(p not in {'', '.', '..'} for p in self.parts) and len(self.parts) < 128,
                 'non-canonical destination path')
        _require(type(self.chain) is tuple and len(self.chain) == len(self.parts) + 1
                 and all(type(node) is tuple and len(node) == 2 and type(node[0]) is int
                         and type(node[1]) is int and 0 <= node[0] < 2**63 and 0 < node[1] < 2**63
                         for node in self.chain), 'invalid destination identities')
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0)
        try:
            self.fds.append(os.open('/', flags))
            for part in self.parts:
                self.fds.append(os.open(part, flags, dir_fd=self.fds[-1]))
            self.check()
        except BaseException:
            self.close()
            raise

    def check(self):
        for index, (fd, identity) in enumerate(zip(self.fds, self.chain)):
            opened = os.fstat(fd)
            named = (os.stat('/', follow_symlinks=False) if index == 0 else
                     os.stat(self.parts[index - 1], dir_fd=self.fds[index - 1], follow_symlinks=False))
            _require(stat.S_ISDIR(named.st_mode) and stat.S_ISDIR(opened.st_mode)
                     and (named.st_dev, named.st_ino) == (opened.st_dev, opened.st_ino) == identity,
                     'destination directory replaced')

    def require_absent(self, name):
        self.check()
        try:
            os.stat(name, dir_fd=self.fds[-1], follow_symlinks=False)
        except FileNotFoundError:
            return
        raise FileExistsError('native thermochemistry destination already exists')

    def write(self, raw, digest):
        self.check()
        name = 'native-thermochemistry-' + digest + '.json'
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0)
        fd = os.open(name, flags, 0o600, dir_fd=self.fds[-1])
        try:
            before = os.fstat(fd)
            _require(stat.S_ISREG(before.st_mode), 'destination is not a regular file')
            view = memoryview(raw)
            while view:
                count = os.write(fd, view)
                _require(count > 0, 'short pair write')
                view = view[count:]
            os.fsync(fd)
            os.fsync(self.fds[-1])
            os.lseek(fd, 0, os.SEEK_SET)
            chunks, count = [], 0
            while count <= len(raw):
                block = os.read(fd, min(1048576, len(raw) + 1 - count))
                if not block:
                    break
                chunks.append(block)
                count += len(block)
            _require(b''.join(chunks) == raw, 'written pair bytes differ')
            after = os.fstat(fd)
            named = os.stat(name, dir_fd=self.fds[-1], follow_symlinks=False)
            _require(stat.S_ISREG(named.st_mode) and after.st_size == named.st_size == len(raw)
                     and (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino) == (named.st_dev, named.st_ino),
                     'written pair identity differs')
            self.check()
            return _PublisherFileBinding(self.path + '/' + name, self.chain,
                                         (after.st_dev, after.st_ino), digest, len(raw))
        finally:
            os.close(fd)

    def close(self):
        _close_descriptors(self.fds)


def save_native_thermodynamic_pair(readout, *, pair, expected_sha256, destination):
    """Save accepted values once; expected_sha256 must come from trusted intake."""
    raw = encode_native_thermodynamic_pair(pair)
    _require(sha256(raw).hexdigest() == _digest(expected_sha256), 'accepted pair digest differs')
    with _locked(readout):
        directory = _Directory(destination)
        try:
            directory.require_absent('native-thermochemistry-' + expected_sha256 + '.json')
            with ExitStack() as stack:
                with _replay(readout) as (profile, source, facts):
                    request = _normalize_request(pair[0].audit_evidence[-1]['request_payload'])
                    _validate_pair(pair, request, profile, source, facts)
                    binding = directory.write(raw, expected_sha256)
                    stack.enter_context(_pinned(binding))
                directory.check()
            directory.check()
        finally:
            directory.close()
    return binding


@dataclass(frozen=True, kw_only=True)
class NativeThermodynamicReadout:
    readout: frequency.FreqReadout
    artifact: _PublisherFileBinding

    def __post_init__(self):
        _require(type(self.readout) is frequency.FreqReadout and type(self.artifact) is _PublisherFileBinding,
                 'invalid thermodynamic startup registration')

    def read(self):
        with _locked(self.readout), _pinned(self.artifact) as pin:
            data = _closed(_decode(pin.raw, _CAP), {
                'schema', 'request', 'qualified_conformer_ensemble', 'thermodynamic_ensemble'}, 'saved pair')
            _require(data['schema'] == _SCHEMA, 'unsupported pair schema')
            request = _request_from_json(data['request'])
            with _replay(self.readout) as (profile, source, facts):
                qualified = _restore(data['qualified_conformer_ensemble'], ConformerEnsemble, 'conformer-ensemble', profile)
                thermo = _restore(data['thermodynamic_ensemble'], ThermodynamicEnsemble, 'thermodynamic-ensemble')
                pair = (qualified, thermo)
                _validate_pair(pair, request, profile, source, facts)
                _require(encode_native_thermodynamic_pair(pair) == pin.raw, 'restored pair bytes differ')
        return pair


def load_native_thermodynamic_readout(content: bytes, digest: str):
    """Trusted startup only; never acquire a source registration from HTTP."""
    _require(type(content) is bytes and sha256(content).hexdigest() == _digest(digest), 'invalid startup digest')
    data = _closed(_decode(content, 1024 * 1024), {'schema', 'frequency_registration', 'artifact'}, 'startup registration')
    _require(data['schema'] == _REGISTRATION, 'unsupported startup schema')
    def binding(value):
        value = _closed(value, _BINDING_KEYS, 'startup physical binding')
        _require(type(value['parent_chain']) is list and type(value['file_identity']) is list
                 and all(type(node) is list for node in value['parent_chain']), 'invalid startup physical arrays')
        return _PublisherFileBinding(value['path'], tuple(tuple(n) for n in value['parent_chain']),
                                     tuple(value['file_identity']), value['sha256'], value['size_bytes'])
    source, artifact = binding(data['frequency_registration']), binding(data['artifact'])
    with _pinned(source, 2 * 1024 * 1024) as pin:
        readout = frequency.load_freq_readout(pin.raw, source.sha256)
    return NativeThermodynamicReadout(readout=readout, artifact=artifact)

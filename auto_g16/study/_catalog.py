"""Composition of native historical owners; no execution or scientific calculation."""
from contextlib import ExitStack, contextmanager
from dataclasses import fields, is_dataclass
from inspect import signature
import errno
import os
from pathlib import Path

from auto_g16.core import SQLiteRuntimeStore
from auto_g16.execution.readonly import ProgramReadQuery, ProgramReadSnapshot
from auto_g16.execution.program import _decode_program_review_semantics
from auto_g16.execution._receipt_source import _FixedReceiptSource, _historical_receipt_sources
from auto_g16.execution._crest_seed_handoff import _restore_receipt_seed_handoff
from auto_g16.transport._program_rtwin import _PublisherFileBinding, _PinnedPublisherFile
from auto_g16.transport.program import _ProgramTransportStore
from auto_g16.conformer.frequency_readonly import load_freq_readout
from auto_g16.conformer.thermochemistry_readonly import load_native_thermodynamic_readout
from auto_g16.conformer.populations_readonly import load_native_population_readout
from auto_g16.conformer.models import SamplingProfile
from auto_g16.conformer.ingest import _ingest_receipt_crest_conformers_xyz
from auto_g16.query.native import NativeSource, NativeQueryService
from auto_g16.query.models import QueryError
from auto_g16.conformer.readonly import OptReadBusy
from auto_g16.transport._canonical import TransportBoundaryError

from ._model import STAGES, StudyError, binding, closed, decode, digest, encode, plain, require


def verify(value):
    """Return detached data only after all native owners and physical pins exit."""
    try:
        return _verify(value)
    except FileNotFoundError as exc:
        raise StudyError('source-unavailable') from exc
    except Exception as exc:
        code = _availability_error(exc)
        if code:
            raise StudyError(code) from exc
        raise


def _availability_error(error):
    """Do not turn native lock contention into corrupt scientific evidence."""
    if isinstance(error, QueryError) and error.code == 'store-unavailable':
        return 'source-unavailable'  # Query intentionally erases the private cause.
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, OptReadBusy):
            return 'busy'
        if isinstance(error, TransportBoundaryError):
            if str(error) == 'completion owner is busy':
                return 'busy'
            if (str(error) == 'completion physical owner is busy or unsupported'
                    and isinstance(error.__cause__, OSError)
                    and error.__cause__.errno in {errno.EAGAIN, errno.EWOULDBLOCK}):
                return 'busy'
        error = error.__cause__
    return None


@contextmanager
def _pinned_sources():
    with ExitStack() as stack:
        pins = {}
        def close_pins():
            for current in reversed(tuple(pins.values())):
                current.close()
        def check_pins():
            for current in pins.values():
                current._read_and_check()
                require(os.fstat(current.fds[-1]).st_nlink == 1)
        # These are registered first: every owner exits before the final physical
        # check, and every pin remains held through that check.
        stack.callback(close_pins)
        stack.callback(check_pins)
        def pin(bound):
            key = encode(bound)
            if key not in pins:
                current = _PinnedPublisherFile(bound, 64 * 1024 * 1024)
                pins[key] = current
            current = pins[key]
            require(os.fstat(current.fds[-1]).st_nlink == 1)
            return current.raw
        def pin_tree(obj):
            if type(obj) is _PublisherFileBinding:
                pin(obj)
            elif is_dataclass(obj):
                for field in fields(obj):
                    pin_tree(getattr(obj, field.name))
            elif isinstance(obj, (tuple, list)):
                for item in obj:
                    pin_tree(item)

        yield stack, pin, pin_tree


def _verify(value):
    with _pinned_sources() as (stack, pin, pin_tree):
        cat = closed(decode(pin(binding(value['catalog'])), 'invalid-catalog'),
            {'schema', 'stages', 'frequency_readout', 'thermodynamic_readout',
             'population_readout', 'xtb_crest'}, 'invalid-catalog')
        require(cat['schema'] == 'auto-g16-direct-study-catalog/1', 'invalid-catalog')
        require(type(cat['stages']) is list and len(cat['stages']) == 6, 'invalid-catalog')
        registrations, snapshots, typed, cores, stage_data, databases = {}, {}, {}, {}, [], {}
        for stage, row in zip(STAGES[:6], cat['stages']):
            closed(row, {'stage', 'database', 'snapshot'}, 'invalid-catalog')
            require(row['stage'] == stage, 'invalid-catalog')
            db, snap = binding(row['database']), binding(row['snapshot'])
            pin(db)
            raw = pin(snap)
            registration = ProgramReadSnapshot(content=raw, sha256=snap.sha256)
            snapshot = _decode_program_review_semantics(decode(raw))
            require(snapshot.program_execution_spec.program_kind ==
                    (stage if stage in {'xtb', 'crest'} else 'gaussian'), 'invalid-catalog')
            store = stack.enter_context(SQLiteRuntimeStore.read_snapshot(db.path))
            reader = ProgramReadQuery(store)
            summary, lifecycle = reader.get_summary(registration), reader.get_lifecycle(registration)
            require(lifecycle['core_state'] == 'SUCCEEDED' and
                    lifecycle['collection']['state'] == 'collected' and
                    lifecycle['program']['state'] == 'completed')
            task = store.load_task(store.load_attempt(snapshot.attempt_id).task_id)
            run = store.load_workflow_run(task.workflow_run_id)
            stage_data.append(dict(stage=stage, project_id=run.project_id, task_id=task.task_id,
                                   attempt_id=snapshot.attempt_id, summary=summary, lifecycle=lifecycle))
            registrations[stage], typed[stage], cores[stage] = registration, snapshot, store
            snapshots[stage], databases[stage] = raw, db
        require(len({s['attempt_id'] for s in stage_data}) == 6, 'invalid-catalog')
        xtb = typed['xtb']
        spec = xtb.program_execution_spec
        require(len(spec.exact_inputs) == 1)
        expected_initial = dict(input_sha256=spec.exact_inputs[0]['sha256'],
            charge=spec.program_data['charge'], multiplicity=spec.program_data['unpaired_electrons'] + 1,
            **{k: getattr(xtb.resolved_resource_request, k) for k in
               ('cores', 'memory_mb', 'walltime_seconds', 'queue')})
        require(expected_initial == value['initial_xtb'], 'invalid-request')

        def load(key, loader):
            bound = binding(cat[key])
            return loader(pin(bound), bound.sha256)
        freq = load('frequency_readout', load_freq_readout)
        thermo = load('thermodynamic_readout', load_native_thermodynamic_readout)
        population = load('population_readout', load_native_population_readout)
        require(freq == thermo.readout and thermo == population.thermodynamic_readout, 'invalid-catalog')
        _gaussian_stage_links(freq, databases, registrations)
        for reader in (freq, thermo, population):
            pin_tree(reader)

        xc = closed(cat['xtb_crest'], {'sources', 'seed', 'handoff'}, 'invalid-catalog')
        closed(xc['sources'], {'xtb', 'crest'}, 'invalid-catalog')
        fixed, transports = {}, {}
        receipt_cores = {}
        for kind in ('xtb', 'crest'):
            row = closed(xc['sources'][kind], {'snapshot_id', 'core', 'transport',
                'bootstrap_source_sha256', 'bootstrap_source_size_bytes'}, 'invalid-catalog')
            core, transport = binding(row['core']), binding(row['transport'])
            require(core == databases[kind] and row['snapshot_id'] ==
                    typed[kind].program_execution_snapshot_id, 'invalid-catalog')
            fixed[kind] = _FixedReceiptSource(row['snapshot_id'], core, transport,
                row['bootstrap_source_sha256'], row['bootstrap_source_size_bytes'])
            pin(core)
            pin(transport)
            # Receipt ownership requires idle original read-only connections;
            # ProgramReadQuery's transaction views above remain independent.
            receipt_cores[kind] = SQLiteRuntimeStore._open_readonly_existing(core.path)
            stack.callback(receipt_cores[kind].close)
            transports[kind] = _ProgramTransportStore._open_readonly_existing(
                transport.path, approved_root=Path(transport.path).parent)
            stack.callback(transports[kind].close)
        material = decode(pin(freq.material), cap=64 * 1024 * 1024)
        profile_payload = material['profile']
        profile = SamplingProfile._create(**{k: profile_payload[k] for k in
            signature(SamplingProfile._create).parameters if k in profile_payload})
        require(plain(profile._identity_payload()) == profile_payload)
        original = material['original']
        require(original['project_id'] == typed['crest'].project_physical_binding.project_id
                and original['calculation_plan_id'] == typed['crest'].calculation_plan_id
                and original['calculation_plan_revision'] == typed['crest'].calculation_plan_revision)
        observations = original['sampling_observations']
        descriptors, relevance = {}, {}
        for observation in observations:
            index = observation['source_binding']['source_member_index']
            require(index not in descriptors)
            descriptors[index] = observation['descriptors']
            relevance[index] = observation['relevance_tags']
        handoff_binding = binding(xc['handoff'])
        handoff = _restore_receipt_seed_handoff(pin(handoff_binding), handoff_binding.sha256)
        with _historical_receipt_sources(fixed):
            parsed = _ingest_receipt_crest_conformers_xyz(profile=profile,
                program_execution_snapshot=typed['crest'], core_store=receipt_cores['crest'],
                program_transport_store=transports['crest'], preoptimization_handoff=handoff,
                xtb_core_store=receipt_cores['xtb'], xtb_program_execution_snapshot=typed['xtb'],
                xtb_program_transport_store=transports['xtb'], crest_exact_input_bytes=pin(binding(xc['seed'])),
                descriptors_by_member_index=descriptors, relevance_tags_by_member_index=relevance)
        require(plain(parsed) == observations)
        selected = freq.frequency_sources[0]
        source = NativeSource(source_id='historical-anti-frequency', database=Path(selected.revision.path),
            snapshots=(selected.snapshot,), freq_readout=freq,
            thermodynamic_readout=thermo, population_readout=population)
        query = NativeQueryService((source,))
        thermodynamics = query.get_thermodynamics(source.source_id, selected.snapshot.attempt_id)
        populations = query.get_populations(source.source_id, selected.snapshot.attempt_id)
        require(thermodynamics['data']['availability'] == populations['data']['availability'] == 'available')
        result = dict(mode='historical-reuse', execution_enabled=False, execution_performed=False,
            fresh_execution_e2e=False, new_attempt_state='PLANNED', result_origin='historical-native-source',
            stages=stage_data, edges={key: 'verified' for key in (
                'xtb->crest', 'crest->anti_opt', 'crest->gauche_opt', 'anti_opt->anti_freq',
                'gauche_opt->gauche_freq', 'frequencies->thermodynamics', 'thermodynamics->populations')},
            thermodynamics=thermodynamics, populations=populations)
    return result


def _gaussian_stage_links(freq, databases, registrations):
    require(len(freq.optimization_sources) == len(freq.frequency_sources) == 2, 'invalid-catalog')
    for prefix, opt, fr in zip(('anti', 'gauche'), freq.optimization_sources, freq.frequency_sources):
        require(opt.member_id == fr.member_id, 'invalid-catalog')
        for suffix, source in (('opt', opt), ('freq', fr)):
            key = prefix + '_' + suffix
            require(source.original.core == databases[key] and source.snapshot == registrations[key],
                    'invalid-catalog')

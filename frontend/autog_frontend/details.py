"""Versioned read-only projections over public records and pinned local artifacts.

No parser, write-capable store, network or execution operation runs on GET.
The operator catalog is trusted configuration, never selected by HTTP input.
"""
import json
from pathlib import Path
import re
import sqlite3

from auto_g16.core import SQLiteRuntimeStore, RecordNotFoundError, RuntimeStoreError
from auto_g16.result import GaussianResultQuery, ResultProvenanceService, ParseOutcome
from auto_g16.execution import RemoteEffectReceipt, ResolvedResourceRequest
from auto_g16.query import QueryError
from .archive import read_pinned, _object, LIMIT, PARSE_LIMIT
from .archive_import import plain
from .parser_contract import qualified_parser
from .result_context import native_context, bind_result, archive_context

SCHEMA = "auto-g16-detail-evidence/1"


def unavailable(reason):
    return {"availability": "unavailable", "reason": reason, "data": None, "source": None}


def available(data, source):
    return {"availability": "available", "reason": None, "data": data, "source": source}


def document(ref, *, limit=LIMIT):
    if not isinstance(ref, dict) or set(ref) != {"path", "sha256", "size_bytes"}:
        raise ValueError("invalid local artifact reference")
    if not isinstance(ref['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', ref['sha256']):
        raise ValueError("invalid artifact pin")
    raw = read_pinned(Path(ref['path']), ref['sha256'], limit=limit)
    if type(ref['size_bytes']) is not int or len(raw) != ref['size_bytes']:
        raise ValueError("artifact size mismatch")
    return raw


def read_json(ref, *, limit=LIMIT):
    return json.loads(document(ref, limit=limit), object_pairs_hook=_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def public_ref(ref, role):
    return {"kind": role, "sha256": ref['sha256'], "size_bytes": ref['size_bytes']}


def full_result(outcome):
    f = plain(outcome.facts)
    if outcome.parse_status.value != 'parsed' or not qualified_parser(outcome.parser_name, outcome.parser_version):
        return unavailable('qualified-attributed-result-required')
    geometry = f['geometry_blocks'][-1] if f['geometry_blocks'] else None
    return available({
        'final_energy_hartree': f['final_energy_hartree'],
        'frequencies_cm1': f['frequencies_cm-1'], 'frequency_blocks': f['frequency_blocks'],
        'frequency_availability': 'available' if f['frequency_count'] else 'missing',
        'thermochemistry': f['thermochemistry'], 'thermochemistry_unit': 'Hartree',
        'last_geometry': geometry, 'geometry_selection': 'last-recorded-orientation-not-scientific-selection',
        'geometry_unit': 'angstrom', 'geometry_block_count': len(f['geometry_blocks']),
        # Program/parser observations only. Candidate screening belongs to the
        # read-only display; this does not run or persist scientific validation.
        'scientific_facts': {
            'schema': 'auto-g16-scientific-display-facts/1',
            **{key: f[key] for key in (
                'job_section', 'program_status', 'normal_termination_count',
                'error_termination_count', 'termination_evidence',
                'optimization_completed_marker', 'optimization_completed_evidence',
                'stationary_point_marker', 'stationary_point_evidence',
                'frequency_parse_complete', 'frequency_count', 'imaginary_frequency_count',
            )},
        },
    }, {'kind': 'persisted-attributed-result', 'result_id': outcome.result_id,
        'parser': outcome.parser_name, 'parser_version': outcome.parser_version,
        'artifact': f['source_artifact']})


def historical_review(bundle, view, attempt, plan, outcome, ref):
    """Compare saved public rendering to exact current public records.

    This reads a historical report; it neither re-runs validation nor rebuilds
    ReviewBundle from the write-capable ScientificValidation store.
    """
    binding = view.input_binding
    envelope = next(e for e in view.envelopes if e.observation_id == view.selected_envelope_id)
    expected = {
        'attempt': {'attempt_id': attempt.attempt_id, 'task_id': attempt.task_id, 'ordinal': attempt.ordinal},
        'calculation_plan': {'calculation_plan_id': plan.calculation_plan_id, 'task_id': plan.task_id,
                             'revision': plan.revision, 'intent': plain(plan.intent)},
        'input_binding': {**plain(binding.payload()), 'observation_id': binding.observation_id},
        'output_envelope': {**plain(envelope.payload()), 'observation_id': envelope.observation_id},
        'parse_outcome': {**plain(outcome.payload()), 'result_id': outcome.result_id},
        'execution_snapshot_id': binding.execution_snapshot_id,
    }
    if bundle.get('schema_version') != 1 or any(bundle.get(k) != v for k, v in expected.items()):
        raise ValueError('historical Review source chain mismatch')
    validation = bundle['minimum_validation_outcome']
    for k, value in {
        'attempt_id': attempt.attempt_id, 'calculation_plan_id': plan.calculation_plan_id,
        'calculation_plan_revision': plan.revision, 'input_binding_observation_id': binding.observation_id,
        'envelope_observation_id': envelope.observation_id, 'parse_result_id': outcome.result_id,
        'parser_name': outcome.parser_name, 'parser_version': outcome.parser_version, 'result_kind': outcome.result_kind,
    }.items():
        if validation.get(k) != value:
            raise ValueError('historical validation chain mismatch')
    f = plain(outcome.facts)
    if (validation['selected_geometry_block'] not in f['geometry_blocks']
            or any(b not in f['frequency_blocks'] for b in validation['selected_frequency_blocks'])
            or validation['selected_frequencies_cm1'] != [v for b in validation['selected_frequency_blocks'] for v in b['frequencies_cm-1']]
            or bundle['selected_final_geometry'] != validation['selected_geometry_block']
            or bundle['selected_frequency_blocks'] != validation['selected_frequency_blocks']
            or bundle['selected_frequencies_cm1'] != validation['selected_frequencies_cm1']
            or bundle['minimum_validation_classification'] != validation['classification']
            or bundle['primary_reason_code'] != validation['reason_code']):
        raise ValueError('historical selected facts mismatch')
    acceptances = bundle['scientific_acceptances']
    for acceptance in acceptances:
        if any(acceptance[k] != validation[k] for k in ('minimum_validation_outcome_id', 'attempt_id',
                'calculation_plan_id', 'calculation_plan_revision', 'classification', 'parse_result_id',
                'validation_policy_id', 'validation_policy_version')):
            raise ValueError('acceptance does not bind exact validation')
    expected_state = ('accepted' if acceptances else 'eligible-unaccepted') if validation['classification'] == 'VALIDATED_MINIMUM' else 'ineligible'
    if bundle['scientific_acceptance_state'] != expected_state or (acceptances and expected_state == 'ineligible'):
        raise ValueError('invalid historical acceptance state')
    source = {**public_ref(ref, 'historical-review-report'), 'review_bundle_id': bundle['review_bundle_id']}
    return available({'classification': validation['classification'], 'reason_code': validation['reason_code'],
                      'outcome_id': validation['minimum_validation_outcome_id'],
                      'selected_final_geometry': validation['selected_geometry_block'],
                      'selected_frequencies_cm1': validation['selected_frequencies_cm1'],
                      'acceptance_state': bundle['scientific_acceptance_state'],
                      'acceptances': [{k:a[k] for k in ('scientific_acceptance_id','reviewer_id','minimum_validation_outcome_id','review_evidence')} for a in acceptances],
                      'scope': 'historical-report-only-not-new-validation'}, source)


class DetailQuery:
    def __init__(self, database, archive_query, catalog=None, digest=None):
        if (catalog is None) != (digest is None):
            raise ValueError('evidence catalog and hash must be supplied together')
        if digest is not None and not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('invalid evidence catalog hash')
        self.database, self.archives, self.catalog, self.digest = database, archive_query, catalog, digest

    def _entry(self, kind, identity):
        if self.catalog is None:
            return {}
        data = json.loads(read_pinned(Path(self.catalog), self.digest), object_pairs_hook=_object)
        if set(data) != {'schema', 'entries'} or data['schema'] != 'auto-g16-local-evidence-catalog/1' or not isinstance(data['entries'], list) or len(data['entries']) > 1000:
            raise ValueError('unsupported evidence catalog')
        seen = set()
        for item in data['entries']:
            if not isinstance(item, dict) or set(item) - {'kind', 'id', 'log', 'parse_outcome', 'job', 'review', 'execution', 'vibrations', 'history_links', 'conditions', 'input_conditions', 'browse', 'workflow', 'analysis'} or not {'kind','id'} <= set(item):
                raise ValueError('invalid catalog entry')
            key = (item['kind'], item['id'])
            if key[0] not in ('attempt', 'archive') or not isinstance(key[1], str) or key in seen:
                raise ValueError('duplicate or invalid catalog identity')
            seen.add(key)
        return next((x for x in data['entries'] if x['kind'] == kind and x['id'] == identity), {})

    def get_workflow(self,identity):
        try:
            self.archives.get_archive(identity);entry=self._entry('archive',identity)
            from .workflow_evidence import project
            return project(read_json(entry['workflow']),identity,document) if 'workflow' in entry else dict(schema='autog-historical-workflow/1',id=identity,items=[],live_scheduler='unavailable',native_core_binding='unknown')
        except QueryError:raise
        except (ValueError,KeyError,TypeError,OSError):raise QueryError('invalid-evidence') from None

    def execution_source(self, identity):
        """Pinned application evidence for a separate read-only execution projection.

        This does not require a successful Result. Consumers must cross-check
        the packet against public Core receipts before exposing any fields.
        """
        entry = self._entry('attempt', identity)
        if 'execution' not in entry:
            return None
        return {'packet': read_json(entry['execution']),
                'source': public_ref(entry['execution'], 'pinned-execution-packet')}

    def get_conditions(self, identity):
        from .condition_query import conditions
        return conditions(self,identity)

    def get_history_links(self, identity):
        try:
            self.archives.get_archive(identity)
            entry=self._entry('archive',identity)
            from .history_links import project_links,SCHEMA
            return project_links(read_json(entry['history_links']),identity) if 'history_links' in entry else dict(schema=SCHEMA,id=identity,candidates=[])
        except QueryError:raise
        except (ValueError,OSError,TypeError,KeyError):raise QueryError('invalid-evidence') from None

    def get_details(self, kind, identity):
        return self._invoke(kind, identity, False)

    def get_log(self, kind, identity):
        return self._invoke(kind, identity, True)

    def get_vibrations(self, kind, identity):
        return self._invoke(kind, identity, False, modes_only=True)

    def _invoke(self, kind, identity, log_only, modes_only=False):
        try:
            entry = self._entry(kind, identity)
            if kind == 'archive':
                record = self.archives.get_archive(identity)['data']
                result, expected_log = self._archive(record, entry)
            elif kind == 'attempt':
                with SQLiteRuntimeStore.read_snapshot(self.database) as store:
                    result, expected_log = self._attempt(store, identity, entry)
            else:
                raise QueryError('not-found')
            result.update(schema=SCHEMA, kind=kind, id=identity)
            if modes_only:
                from .vibrations import validate_modes
                modes = unavailable('vibration-sidecar-not-connected')
                if 'vibrations' in entry and result['result']['availability'] == 'available':
                    packet = validate_modes(read_json(entry['vibrations']), result)
                    modes = available(packet, public_ref(entry['vibrations'], 'pinned-offline-vibration-modes'))
                return {'schema': 'auto-g16-mode-evidence/1', 'kind': kind, 'id': identity, 'vibrations': modes}
            if not log_only:
                return result
            if expected_log is None or 'log' not in entry:
                return {'schema': SCHEMA, 'kind': kind, 'id': identity, 'log': unavailable('local-log-not-connected')}
            ref = entry['log']
            if ref['sha256'] != expected_log['sha256'] or ref['size_bytes'] != expected_log['size_bytes']:
                raise ValueError('log is not bound to selected result')
            if ref['size_bytes'] > 2 * 1024 * 1024 and kind == 'archive':
                return {'schema': SCHEMA, 'kind': kind, 'id': identity, 'log': unavailable('log-exceeds-inline-limit')}
            raw = document(ref)
            if len(raw) > 2 * 1024 * 1024:
                raise QueryError('response-too-large')
            text = raw.decode('utf-8')
            return {'schema': SCHEMA, 'kind': kind, 'id': identity, 'log': available(
                {'text': text, 'line_count': len(text.splitlines()), 'logical_name': expected_log['logical_name']}, public_ref(ref, 'verified-local-log'))}
        except QueryError:
            raise
        except RecordNotFoundError:
            raise QueryError('not-found') from None
        except (OSError, sqlite3.Error, RuntimeStoreError):
            raise QueryError('store-unavailable') from None
        except (ValueError, TypeError, KeyError, StopIteration, AttributeError, RecursionError):
            raise QueryError('invalid-evidence') from None

    def _archive(self, record, entry):
        out = {'result': unavailable('archive-detail-not-connected'), 'review': unavailable('no-historical-review'),
               'execution': unavailable('historical-job-not-connected')}
        log = next(a for a in record['artifacts'] if a['role'] == 'log')
        if 'parse_outcome' in entry:
            payload = read_json(entry['parse_outcome'], limit=PARSE_LIMIT)
            if payload.get('schema') == 'autog-local-parse-outcome/1':
                from .archive_outcome import ArchiveParseOutcome
                parsed = ArchiveParseOutcome.from_payload(payload)
            else:
                parsed = ParseOutcome.from_payload(payload)
            if parsed.attempt_id != record['archive_id']:
                raise ValueError('archive parse identity mismatch')
            if record['parser'] != {'name': parsed.parser_name, 'version': parsed.parser_version,
                                    'status': parsed.parse_status.value, 'diagnostics': list(parsed.diagnostics)}:
                raise ValueError('archive parser mismatch')
            if parsed.parse_status.value == 'parsed':
                source = parsed.facts['source_artifact']
                if any(source[k] != log[k] for k in ('sha256', 'size_bytes', 'logical_name')):
                    raise ValueError('archive parse source mismatch')
                s = record['summary']; f = parsed.facts
                expected = {'termination':f['program_status'],'energy_hartree':f['final_energy_hartree'],
                            'normal_count':f['normal_termination_count'],'error_count':f['error_termination_count'],
                            'optimization':f['optimization_completed_marker'],'stationary_point':f['stationary_point_marker'],
                            'frequency_count':f['frequency_count'] or None,
                            'imaginary_count':f['imaginary_frequency_count'] if f['frequency_count'] else None}
                if s != expected:
                    raise ValueError('archive facts conflict')
            out['result'] = full_result(parsed)
        if 'job' in entry:
            ref = entry['job']; artifact = next(a for a in record['artifacts'] if a['role'] == 'legacy_metadata')
            if any(ref[k] != artifact[k] for k in ('sha256', 'size_bytes')):
                raise ValueError('legacy job is not bound to archive')
            job = read_json(ref)
            input_artifact = next(a for a in record['artifacts'] if a['role'] == 'input')
            if job.get('schema') != 'codex-gaussian-pbs/1' or job.get('input_sha256') != input_artifact['sha256'] or job.get('result',{}).get('log') != log['logical_name']:
                raise ValueError('legacy job bindings conflict')
            scheduler = job.get('scheduler', {}); gaussian = job.get('gaussian', {})
            out['execution'] = available({'resource_scope': 'historical-declarations-not-measured-allocation',
                'resources': {k: gaussian.get(k) for k in ('nprocshared','memory')},
                'scheduler': {k: scheduler.get(k) for k in ('type','queue','resources','job_id','submitted_at_server','started_at_server','last_observed_state')},
                'receipts': [], 'live_state': 'unavailable'}, public_ref(ref, 'legacy-job-sidecar'))
        out['context'] = archive_context(record, out['result']['source'])
        return out, log

    def _attempt(self, store, identity, entry):
        attempt = store.load_attempt(identity)
        summary = GaussianResultQuery(store).get_summary(identity)
        out = {'result': unavailable('qualified-result-required'), 'review': unavailable('historical-review-not-connected'),
               'execution': unavailable('qualified-execution-binding-required')}
        out['context'] = native_context(store, attempt)
        if summary['availability'] != 'available':
            return out, None
        view = ResultProvenanceService(store).current_view(identity)
        outcome = next(o for o in view.selected_results if o.result_id == summary['source']['result_id'])
        plan = store.load_calculation_plan(view.input_binding.calculation_plan_id)
        out['result'] = full_result(outcome)
        if out['result']['availability'] == 'available':
            envelope = next(e for e in view.envelopes if e.observation_id == view.selected_envelope_id)
            out['context'] = bind_result(out['context'], plan, view.input_binding, outcome, out['result']['source'], envelope)
        log = plain(outcome.facts['source_artifact'])
        if 'review' in entry:
            out['review'] = historical_review(read_json(entry['review']), view, attempt, plan, outcome, entry['review'])
        receipts = []
        receipt_intents = set()
        for observation in store.observations_for_attempt(identity):
            if observation.observation_type != 'v3.remote-effect-receipt':
                continue
            receipt = RemoteEffectReceipt.from_payload(observation.data)
            if (observation.attempt_id != identity or receipt.attempt_id != identity or receipt.execution_snapshot_id != view.input_binding.execution_snapshot_id
                    or receipt.remote_effect_receipt_id != observation.observation_id):
                raise ValueError('execution receipt identity mismatch')
            receipt_intents.add(receipt.submission_intent_id)
            receipts.append({'receipt_id': receipt.remote_effect_receipt_id, 'sequence': receipt.effect_sequence,
                             'kind': receipt.effect_kind.value, 'state': receipt.effect_state.value, 'job_id': receipt.job_id})
        if len(receipt_intents) > 1:
            raise ValueError('conflicting execution intents')
        out['execution'] = available({'resource_scope': 'submission-request-not-measured-allocation',
            'resources': None, 'scheduler': None, 'receipts': sorted(receipts, key=lambda r:r['sequence']),
            'live_state': 'unavailable'}, {'kind': 'public-Core-execution-receipts', 'execution_snapshot_id': view.input_binding.execution_snapshot_id})
        if 'execution' in entry:
            packet = read_json(entry['execution'])
            snapshot = packet['execution_snapshot']
            binding = view.input_binding
            expected_input = {k:plain(binding.payload())[k] for k in ('attempt_id','calculation_plan_id','calculation_plan_revision','input_format','logical_name','prepared_input_binding_id','sha256','size_bytes')}
            if (snapshot['execution_snapshot_id'] != binding.execution_snapshot_id or snapshot['attempt_id'] != identity
                    or snapshot['calculation_plan_id'] != plan.calculation_plan_id or snapshot['calculation_plan_revision'] != plan.revision
                    or snapshot['prepared_input_binding'] != expected_input
                    or receipt_intents != {snapshot['submission_intent_id']}):
                raise ValueError('execution snapshot source mismatch')
            request = snapshot['resolved_resource_request']
            spec = store.load_resource_spec(request['resource_spec_id'])
            if spec.task_id != attempt.task_id:
                raise ValueError('resource task mismatch')
            resolved = ResolvedResourceRequest(resource_spec=spec, **{k:request[k] for k in ('cores','memory_mb','walltime_seconds','queue')})
            if plain(resolved.semantic_payload()) != request:
                raise ValueError('resource request mismatch')
            out['execution']['data']['resources'] = {k:request[k] for k in ('cores','memory_mb','walltime_seconds','queue')}
            out['execution']['source']['resource_report'] = public_ref(entry['execution'],'historical-execution-packet')
        return out, log

"""Single-use submission. Ambiguous qsub outcomes stop the entire batch."""
from hashlib import sha256
from contextlib import contextmanager, nullcontext, ExitStack
from datetime import datetime, timezone
from pathlib import Path
import os
import tempfile
import sys
from ag import node_targeting, approval, attempt, cards, confirm, journal, parent_chk, remote, state, status, slurm, submission, budget
from ag.config import (for_manifest, scheduler_kind, committed_cap, shared_cap_summary,
                       optional_resource_caps, validate_walltime)
from ag.transport import bound_transport
from ag.locks import claim, submission_lock
from ag.transport import require_ok, TransportError


class UnknownSubmission(RuntimeError):
    pass


class UserCancelled(ValueError):
    pass


class WaitingForRoute(ValueError):
    """No placement is available; this is not a new submission or failure."""
    pass


@contextmanager
def autonomous_transaction(cfg):
    """Fixed lock order, for local check/reserve/consume only."""
    from ag.autonomy_submission import machine_lock
    # Waiting on an existing manual submit must not hold the all-study mutex.
    # Manual writer completion takes the machine mutex after releasing this
    # config lock; autonomy begin/start/resume never take a config lock.
    with submission_lock(cfg):
        with machine_lock():
            yield


def autonomy_context(value, study_id):
    from ag import study
    required = {'run_id', 'token', 'plan_sha256', 'policy_name', 'object_id', 'job_class'}
    if (not isinstance(value, dict) or not required <= set(value)
            or set(value) - required - {'failure_class', 'reroute_source'}):
        raise ValueError('Complete autonomous run, policy, plan and object context required')
    for key in ('run_id', 'policy_name', 'object_id'):
        study.identifier(value[key])
    if not isinstance(value['token'], str) or not value['token']:
        raise ValueError('Current lease token is required')
    if value['job_class'] not in ('main', 'small'):
        raise ValueError('Autonomous object class must be main or small')
    failure = value.get('failure_class')
    if failure is not None:
        study.identifier(failure)
    reroute = value.get('reroute_source')
    if reroute is not None:
        study.identifier(reroute)
        if failure is not None:
            raise ValueError('A reroute successor cannot also claim a failure remedy')
    return dict(value, study_id=study_id, failure_class=failure, reroute_source=reroute)


def autonomous_configuration(cfg):
    """Reread the actual configured bytes; an in-memory rule is not authority."""
    from ag.config import load_config
    if '_config_path' not in cfg:
        raise ValueError('Autonomous actions require a persisted local configuration')
    current = load_config(cfg['_config_path'])
    if (current['_config_dir'] != cfg['_config_dir']
            or current['local']['studies_root'] != cfg['local']['studies_root']):
        raise ValueError('Autonomous configuration or study root changed')
    return current


def bound_policy(cfg, snapshot, context):
    from ag import autonomy, autonomy_policy, autonomy_submission, route, study
    if not hasattr(route, 'ladder_config_identity'):
        raise ValueError('Reviewed routing ladder is not integrated in this checkout')
    policy = autonomy_policy.read_policy(cfg, context['policy_name'])
    plan = snapshot['plans'][snapshot['current_plan']]
    autonomy_policy.check_plan_bounds(policy, plan['body']['spec'])
    digest = autonomy_policy.check_binding(policy, study_id=context['study_id'],
        study_key=autonomy_submission.study_identity(study.locate(cfg, context['study_id']))['study_key'],
        round_id=snapshot['current_round'], plan_sha256=context['plan_sha256'],
        routing_sha256=route.ladder_config_identity(cfg),
        now=datetime.fromtimestamp(autonomy.now(), timezone.utc))
    return policy, digest


def match_selection(manifest, selection):
    choice = selection['result']['recommendation']
    if choice is None:
        raise WaitingForRoute('No currently eligible routing cell: ' + selection['result']['reason'])
    for key in ('cluster', 'tier', 'cores', 'mem_gb'):
        if manifest[key] != choice[key]:
            raise ValueError('Frozen Attempt differs from selected routing resource: ' + key)
    target = manifest.get('node_target', {})
    if (target.get('name') != choice['target_node']
            or target.get('fraction') != choice.get('node_fraction')):
        raise ValueError('Frozen Attempt differs from selected routing node/fraction')
    return choice


class AutonomousSubmission:
    """One Attempt's action boundaries; no cached value is an action permit."""

    def __init__(self, cfg, path, context):
        self.cfg, self.path = cfg, path
        self.context = autonomy_context(context, path.parent.parent.name)
        self.requested_failure_class = self.context['failure_class']
        self.remedy_source = None
        self.reroute_source = None
        self.rule_sha256 = None
        self.reservation = None
        self.dispatch_started = False
        self.live = None
        self.slurm_probe = None
        self.scheduler_target = None
        self.prepared_remedy = None
        self.prepared_reroute = None
        self.prepared_stops = None

    def guard(self):
        from ag import autonomy
        c = self.context
        return autonomy.submission_guard(self.cfg, c['study_id'], c['run_id'], c['token'],
                                         plan_sha256=c['plan_sha256'])

    def checked(self, guard, *, consumed=False):
        from ag import autonomy, autonomy_policy, autonomy_submission, route
        from ag.config import select_cluster, shared_clusters
        cfg = autonomous_configuration(self.cfg)
        snapshot = guard.snapshot
        policy, digest = bound_policy(cfg, snapshot, self.context)
        if self.rule_sha256 is not None and digest != self.rule_sha256:
            raise ValueError('Autonomous rule changed during this submission')
        self.rule_sha256 = digest
        verified = autonomy_policy.check_attempt(cfg, self.path, policy)
        manifest = attempt.read_manifest(self.path)
        excluded = self.path.name if consumed else None
        if self.context['reroute_source'] is not None:
            if self.context['job_class'] != self.prepared_reroute.job_class:
                raise ValueError('Reroute object class differs from its original routing request')
            self.reroute_source = autonomy_submission.verify_reroute_evidence(cfg, snapshot,
                self.context['object_id'], self.prepared_reroute, exclude_attempt=excluded)
            if (manifest.get('reroute_source') != self.reroute_source
                    or self.reroute_source['attempt_id'] != self.context['reroute_source']):
                raise ValueError('Reroute source differs from the frozen prepared Attempt')
            files = attempt.verified_files(cfg, self.path, manifest)
            if attempt.reroute_input_identity(manifest, files) != self.prepared_reroute.scientific_identity:
                raise ValueError('Reroute scientific input differs from its original submission')
            self.remedy_source = None
        else:
            if 'reroute_source' in manifest:
                raise ValueError('A prepared reroute successor requires its explicit original source')
            self.remedy_source = autonomy_submission.verify_remedy_evidence(cfg, snapshot, self.context['object_id'],
                self.prepared_remedy, exclude_attempt=excluded)
        actual_failure = self.remedy_source['failure_class'] if self.remedy_source else None
        if consumed and (self.remedy_source != self.reservation['record']['remedy_source']
                         or actual_failure != self.reservation['record']['failure_class']
                         or self.reroute_source != self.reservation['record'].get('reroute_source')):
            raise ValueError('Frozen remedy evidence changed after reservation')
        if self.requested_failure_class is not None and self.requested_failure_class != actual_failure:
            raise ValueError('Claimed remedy class differs from verified failure evidence')
        self.context['failure_class'] = actual_failure
        selection = route.autonomous_selection(cfg, snapshot, self.context,
            template=manifest['template'], walltime=manifest['walltime'],
            requested_tier=manifest['tier'],
            parent_cluster=manifest.get('parent_chk', {}).get('cluster'),
            exclude_ownership=self.reservation['sha256'] if consumed else None,
            evaluate_from=({key: self.reroute_source[key] for key in
                            ('study_key', 'attempt_id', 'record_sha256')}
                           if self.reroute_source is not None else None),
            prepared_stops=self.prepared_stops)
        choice = match_selection(manifest, selection)
        if consumed:
            original = self.reservation['record']['selection']['result']['recommendation']
            keys = ('cell_id', 'capacity_node', 'target_node', 'node_fraction',
                    'batch_input_sha256', 'config_sha256')
            # A first member has a newly timed input on each recheck; subsequent
            # members must continue to reference the exact first batch origin.
            keys = tuple(key for key in keys if key != 'batch_input_sha256')
            if any(choice.get(key) != original.get(key) for key in keys):
                raise ValueError('Routing position changed after reservation')
        records = [v for v in snapshot.get('submissions', {}).values()
                   if v['round_id'] == snapshot['current_round']]
        existing = snapshot.get('submissions', {}).get(self.path.name)
        if consumed:
            if (not existing or existing['ownership_sha256'] != self.reservation['sha256']
                    or existing['aborted_before_dispatch'] is not None
                    or existing['dispatch_started'] is not None):
                raise ValueError('Autonomous Attempt is not an undispatched owned reservation')
            records = [v for v in records if v['attempt_id'] != self.path.name]
        selected = select_cluster(cfg, manifest['cluster'])
        placements = selection['input']['placements']
        usage = route._ladder_usage(cfg, manifest['cluster'], selection['input']['snapshots'],
                                    placements, datetime.fromtimestamp(autonomy.now(), timezone.utc))
        occupancy = [dict(clusters=list(shared_clusters(selected)),
            committed_cores=usage['committed'], queued_cores=usage['queued'],
            jobs=sum(p.get('run_id') is not None for p in usage['active']),
            requested_cores=manifest['cores'], requested_jobs=1)]
        account_job_cap = route.autonomous_account_job_cap(cfg, manifest['cluster'])
        if account_job_cap is not None and occupancy[0]['jobs'] + 1 > account_job_cap:
            raise ValueError('Bound routing shared-account autonomous job limit exceeded')
        if self.live is not None:
            username, jobs = self.live
            is_slurm = scheduler_kind(selected) == 'slurm'
            running, queued = (slurm.core_breakdown(jobs, username) if is_slurm
                               else status.core_breakdown(jobs, username))
            observed = {job['job_id']: job for job in jobs
                        if (job['owner'] if is_slurm else job['Job_Owner'].split('@')[0]) == username}
            relevant = [p for p in placements if p['cluster'] in shared_clusters(selected)]
            for p in relevant:
                if p['job_id'] in observed:
                    row = observed[p['job_id']]
                    if row.get('name' if is_slurm else 'Job_Name') != p['scheduler_job_name']:
                        raise ValueError('Live scheduler job disagrees with immutable ownership')
            pending = [p for p in relevant if p['job_id'] not in observed and p['state'] != 'finished']
            held = sum(p['cores'] for p in pending)
            # Use both sources conservatively. A newer live inventory cannot
            # weaken a stricter policy cap merely because monitor lags behind.
            occupancy[0]['committed_cores'] = max(occupancy[0]['committed_cores'], running + queued + held)
            occupancy[0]['queued_cores'] = max(occupancy[0]['queued_cores'], queued + held)
        autonomy_policy.check_budget(policy, plan_spec=snapshot['plans'][snapshot['current_plan']]['body']['spec'],
            round_attempts=len(records), requested_attempts=1, occupancy=occupancy)
        bound_policy(cfg, guard.snapshot, self.context)
        guard.check_current('submit')
        if not approval.timestamp(policy['set_at']).timestamp() <= autonomy.now() < approval.timestamp(policy['expires_at']).timestamp():
            raise ValueError('Autonomous rule expired during action-boundary verification')
        return cfg, policy, manifest, verified, selection

    def validate(self):
        self.refresh_remedy()
        with autonomous_transaction(self.cfg):
            with self.guard() as guard:
                self.checked(guard)

    def refresh_remedy(self):
        """Read/hash scientific sources before taking any submission mutex."""
        from ag import autonomy, autonomy_submission
        current = autonomy.status(self.cfg, self.context['study_id'])['state']
        self.prepared_stops = autonomy_submission.prepare_stopped_reservations(self.cfg)
        options = {'exclude_attempt': self.path.name if self.reservation is not None else None}
        if self.context['reroute_source'] is not None:
            if self.prepared_reroute is None:
                self.prepared_reroute = autonomy_submission.prepare_reroute_evidence(self.cfg, current,
                    self.context['object_id'], self.context['reroute_source'], **options)
            else:
                self.prepared_reroute = autonomy_submission.refresh_reroute_evidence(self.cfg, current,
                    self.context['object_id'], self.prepared_reroute, **options)
            return
        if self.prepared_remedy is None:
            self.prepared_remedy = autonomy_submission.prepare_remedy_evidence(self.cfg, current,
                self.context['object_id'], **options)
        else:
            self.prepared_remedy = autonomy_submission.refresh_remedy_evidence(self.cfg, current,
                self.context['object_id'], self.prepared_remedy, **options)

    def collect_slurm_probe(self, transport):
        """Collect only the reviewed optional origin probe before consumption."""
        if not hasattr(status, 'slurm_submission_probe'):
            # T186 alone retains ordinary submission, without original-instance
            # evidence or any automatic reroute qualification.
            return
        self.validate()
        try:
            probe = status.slurm_submission_probe(self.cfg, self.path, transport)
        except Exception as exc:
            evidence = getattr(exc, 'evidence', None)
            if evidence is not None:
                # Diagnostics from a failed read are never promoted to an
                # ownership record or fetched scientific output. Preserve them
                # outside the study even if the owner expired during the read.
                from ag import _autonomy_store as disk
                directory = Path(tempfile.mkdtemp(prefix='ag-slurm-probe-'))
                with (directory / 'failed-probe.json').open('xb') as handle:
                    handle.write(disk.encode(evidence))
                print('Failed submission probe diagnostic: ' + str(directory / 'failed-probe.json'), file=sys.stderr)
            raise
        self.validate()
        self.slurm_probe = probe

    def scheduler_submission(self, cfg, manifest):
        if manifest.get('scheduler') != 'slurm':
            return remote.submit(cfg, manifest)
        probe = self.reservation['record'].get('slurm_probe', {}).get('record', {})
        if probe.get('bound_submit_format_candidate') is True:
            if not hasattr(remote, 'slurm_submit_bound'):
                raise ValueError('Reviewed bound Slurm submission constructor is unavailable')
            command = remote.slurm_submit_bound(cfg, manifest, scheduler_cluster=probe['scheduler_cluster'])
            self.scheduler_target = probe['scheduler_cluster']
            return command
        return remote.slurm_submit(cfg, manifest)

    def scheduler_query_options(self):
        probe = (self.reservation['record'].get('slurm_probe', {}).get('record', {})
                 if self.reservation is not None else (self.slurm_probe or {}).get('record', {}))
        return ({'scheduler_cluster': probe['scheduler_cluster']}
                if probe.get('bound_submit_format_candidate') is True else {})

    def consume(self, summary, manifest, files):
        from ag import autonomy_submission
        self.refresh_remedy()
        with autonomous_transaction(self.cfg), self.guard() as guard:
            cfg, policy, current_manifest, verified, selection = self.checked(guard)
            if current_manifest != manifest or attempt.verified_files(cfg, self.path, current_manifest) != files:
                raise ValueError('Frozen submission bytes changed before consumption')
            c = self.context
            record = dict(round_id=guard.snapshot['current_round'], run_id=c['run_id'],
                object_id=c['object_id'], failure_class=c['failure_class'],
                remedy_source=self.remedy_source,
                max_attempts=policy['max_attempts'], plan_sha256=c['plan_sha256'],
                rule_sha256=self.rule_sha256, routing_sha256=policy['routing_sha256'],
                policy_name=c['policy_name'], quote=policy['quote'], summary=summary, selection=selection)
            if self.slurm_probe is not None:
                record['slurm_probe'] = self.slurm_probe
            if self.reroute_source is not None:
                record['reroute_source'] = self.reroute_source
            selected = for_manifest(cfg, manifest)
            ledger = None
            if scheduler_kind(selected) == 'slurm':
                ledger = budget.shared_ledgers(selected)[selected['_cluster']]
                budget.check(selected, budget.requested(manifest), ledger=ledger)
            evidence = autonomy_submission.read_reservations(cfg,
                states={str(self.path.parent.parent): guard.snapshot}, prepared_stops=self.prepared_stops)
            saved = autonomy_submission.write_reservation(cfg, self.path, record,
                batch_inputs=evidence['batch_inputs'], verified_state=guard.snapshot,
                validate_consume=guard.validate_consume, prepared_remedy=self.prepared_remedy,
                prepared_reroute=self.prepared_reroute)
            self.reservation = saved
            if self.slurm_probe is not None:
                from ag import _autonomy_store as disk
                fd = disk.directory(self.path)
                try:
                    disk.Store(fd).exclusive('slurm-origin-probe.json', disk.encode(self.slurm_probe['record']))
                finally:
                    os.close(fd)
            claim(self.path / '.submit-claim')
            approval.archive(self.path, saved['authorization'], summary)
            guard.consume(saved['consume'])
            if ledger is not None:
                budget.reserve(selected, manifest, ledger)
            # Global audits read status together with its journal. Publish both
            # while the same machine transaction still owns the reservation.
            state.write(self.path, 'submitting')
            return saved['authorization']

    def boundary(self, stage):
        self.refresh_remedy()
        with autonomous_transaction(self.cfg), self.guard() as guard:
            self.checked(guard, consumed=True)
            if stage == 'dispatch':
                # Linearization point: pause can run during the subsequent
                # remote call, but cannot undo an already started dispatch.
                guard.dispatch_started(self.path.name)
                self.dispatch_started = True

    def failed(self, target, note):
        from ag import autonomy
        if self.reservation is None:
            return
        c = self.context
        with autonomous_transaction(self.cfg):
            current = state.read(self.path)
            if current['state'] in ('submitting', 'unknown', 'failed_presubmit'):
                state.write(self.path, target, note=note)
            else:
                # A separate current observer may already have reconciled a
                # delayed dispatch. Preserve its exact known-job progression.
                manifest = attempt.read_manifest(self.path)
                submission.verified_job(self.path, manifest, current)
            autonomy.boundary_failure(self.cfg, c['study_id'], self.path.name,
                self.reservation['sha256'], run_id=c['run_id'], token=c['token'],
                dispatched=self.dispatch_started, reason=target)
            if not self.dispatch_started:
                manifest = attempt.read_manifest(self.path)
                selected = for_manifest(self.cfg, manifest)
                if scheduler_kind(selected) == 'slurm':
                    ledger = budget.shared_ledgers(selected)[selected['_cluster']]
                    budget.reject(selected, manifest, ledger)

    def observe_placement(self, cfg, manifest, job_id, transport):
        """Query outside locks; fence only the existing placement publication."""
        from ag import autonomy
        c = self.context

        autonomy.check(self.cfg, c['study_id'], c['run_id'], c['token'],
                       action='observe', plan_sha256=c['plan_sha256'])
        try:
            response = transport.run(remote.jobs(job_id))
            if response.returncode and status.scheduler_absent(response):
                observed = None
            else:
                jobs = status.parse_jobs(require_ok(response, 'target placement qstat'))
                if (len(jobs) != 1 or jobs[0]['job_id'] != job_id
                        or jobs[0].get('Job_Name') != manifest['pbs_job_name']):
                    raise ValueError('Target placement scheduler identity mismatch')
                observed = jobs[0]
        except (OSError, ValueError, TransportError):
            with self.publication():
                current = state.read(self.path)
                state.write(self.path, current['state'],
                    node_placement=dict(state='unverified', target=manifest['node_target']['name']),
                    note='Job accepted; placement query failed; stop')
            raise
        with self.publication():
            return node_targeting.retain_placement(self.path, manifest, observed)

    def publication(self):
        """Fence local observations without extending ownership across IO."""
        from ag import autonomy
        c = self.context
        return autonomy.observation_publication_guard(self.cfg, c['study_id'], c['run_id'],
            c['token'], action='observe', plan_sha256=c['plan_sha256'])

    def capture_origin(self, transport, reported_cluster):
        """Preserve a known job while separately collecting optional origin data."""
        from ag import autonomy_submission
        if self.slurm_probe is None or not hasattr(status, 'capture_slurm_origin'):
            return None
        probed_cluster = self.slurm_probe['record'].get('scheduler_cluster')
        if probed_cluster is not None and reported_cluster is not None and probed_cluster != reported_cluster:
            raise ValueError('Submitted scheduler cluster differs from the original controller probe')

        @contextmanager
        def publication():
            with self.publication() as current:
                saved = autonomy_submission.verified_reservation(self.path, verified_state=current)
                if saved != {key: self.reservation[key] for key in ('record', 'sha256')}:
                    raise ValueError('Initial scheduler observation ownership changed')
                yield current

        if probed_cluster is not None and reported_cluster is None:
            # The existing fixed sbatch command does not select an actual
            # cluster. A controller probe alone cannot fill an omitted reply
            # field: inherited scheduler environment may select another one.
            result = dict(status='unavailable', reason='Submission did not report its actual scheduler cluster',
                          scheduler_probe_sha256=self.slurm_probe['sha256'], reroute_authorized=False)
            with publication():
                journal.append(self.path.parent.parent, 'slurm_origin', self.path.name, 'unavailable', result)
            return result
        return status.capture_slurm_origin(self.cfg, self.path, transport,
            probe_sha256=self.slurm_probe['sha256'], ownership_sha256=self.reservation['sha256'],
            publication=publication)


def prepare_autonomous(cfg, *, study_name, context, options):
    """Prepare with current ownership and trusted selection, never a JSON receipt."""
    from ag import autonomy, autonomy_submission, route
    c = autonomy_context(context, study_name)
    prepared_stops = autonomy_submission.prepare_stopped_reservations(cfg)
    prepared_reroute = None
    if c['reroute_source'] is not None:
        if options.get('parent_chk') is not None or options.get('relaxed_input'):
            raise ValueError('Reroute cannot add a checkpoint dependency or relaxed input')
        prepared_reroute = autonomy_submission.prepare_reroute_evidence(cfg,
            autonomy.status(cfg, study_name)['state'], c['object_id'], c['reroute_source'])
        if c['job_class'] != prepared_reroute.job_class:
            raise ValueError('Reroute object class differs from its original routing request')
    parent_cluster = None
    if options.get('parent_chk'):
        parent_id = options['parent_chk'].split(':', 1)[0]
        parent_cluster = attempt.read_manifest(attempt.find(cfg, parent_id)).get('cluster', 'default')
    with autonomous_transaction(cfg), autonomy.submission_guard(cfg, study_name, c['run_id'], c['token'],
                                    plan_sha256=c['plan_sha256']) as guard:
        current = autonomous_configuration(cfg)
        policy, digest = bound_policy(current, guard.snapshot, c)
        reroute_source = (autonomy_submission.verify_reroute_evidence(current, guard.snapshot,
            c['object_id'], prepared_reroute) if prepared_reroute is not None else None)
        evaluate_from = ({key: reroute_source[key] for key in ('study_key', 'attempt_id', 'record_sha256')}
                         if reroute_source is not None else None)
        selection = route.autonomous_selection(current, guard.snapshot, c,
            template=options['template'], walltime=options['walltime'],
            requested_tier=options.get('tier'), parent_cluster=parent_cluster,
            evaluate_from=evaluate_from, prepared_stops=prepared_stops)
        choice = selection['result']['recommendation']
        if choice is None:
            evidence = autonomy_submission.read_reservations(current,
                states={str(Path(current['local']['studies_root']) / study_name): guard.snapshot},
                prepared_stops=prepared_stops)
            saved = autonomy_submission.write_waiting(current, study_name, selection,
                                                       batch_inputs=evidence['batch_inputs'])
            guard.waiting(c['object_id'], saved)
            raise WaitingForRoute('No currently eligible routing cell: ' + selection['result']['reason'])
        if options['template'] not in policy['templates'] or choice['cluster'] not in policy['clusters']:
            raise ValueError('Selected template/cluster is outside the confirmed policy')
    # Parsing and CREST's fixed read-only install check run outside both local
    # mutexes. Publication recaptures authorization instead of reusing this read.
    values = dict(options, cluster=choice['cluster'], tier=choice['tier'],
                  target_node=choice['target_node'], node_fraction=choice.get('node_fraction'))
    if prepared_reroute is not None:
        values['reroute_evidence'] = dict(source=reroute_source,
                                        scientific_identity=prepared_reroute.scientific_identity)
        parents = list(values.get('parents') or [])
        relation = dict(attempt_id=reroute_source['attempt_id'], relation='reroute')
        if any(parent.get('relation') == 'reroute' and parent != relation for parent in parents):
            raise ValueError('Reroute parent differs from its exact original source')
        if relation not in parents:
            parents.append(relation)
        values['parents'] = parents

    @contextmanager
    def publication():
        # Parse all retained stop proofs before acquiring shared locks; their
        # unchanged identities and actual cancellation ledgers are checked in it.
        fresh_stops = autonomy_submission.prepare_stopped_reservations(cfg)
        with autonomous_transaction(cfg), autonomy.submission_guard(cfg, study_name, c['run_id'], c['token'],
                                        plan_sha256=c['plan_sha256']) as guard:
            fresh = autonomous_configuration(cfg)
            fresh_policy, fresh_digest = bound_policy(fresh, guard.snapshot, c)
            if fresh_digest != digest or fresh != current:
                raise ValueError('Configuration or rule changed during preparation')
            if prepared_reroute is not None:
                source = autonomy_submission.verify_reroute_evidence(fresh, guard.snapshot,
                    c['object_id'], prepared_reroute)
                if source != reroute_source:
                    raise ValueError('Reroute stopping or lineage evidence changed during preparation')
            selected = route.autonomous_selection(fresh, guard.snapshot, c,
                template=values['template'], walltime=values['walltime'],
                requested_tier=values['tier'], parent_cluster=parent_cluster,
                evaluate_from=evaluate_from, prepared_stops=fresh_stops)['result']['recommendation']
            keys = ('cell_id', 'cluster', 'tier', 'cores', 'mem_gb', 'capacity_node', 'target_node', 'node_fraction')
            if selected is None or any(selected.get(k) != choice.get(k) for k in keys):
                raise ValueError('Routing selection changed before Attempt publication')
            consumed = [row for row in guard.snapshot.get('submissions', {}).values()
                        if row['round_id'] == guard.snapshot['current_round']]
            if len(consumed) * 10 >= fresh_policy['max_attempts'] * 9:
                guard.pause('Round Attempt consumption reached 90%')
                raise ValueError('Round Attempt budget reached 90%')
            bound_policy(fresh, guard.snapshot, c)
            guard.check_current('prepare')
            if not approval.timestamp(fresh_policy['set_at']).timestamp() <= autonomy.now() < approval.timestamp(fresh_policy['expires_at']).timestamp():
                raise ValueError('Autonomous rule expired during preparation-boundary verification')
            yield

    manifest = attempt._prepare(current, study_name=study_name, publication=publication, **values)
    # Verify the actual frozen bytes, rather than a model's method declaration.
    from ag.autonomy_policy import check_attempt
    check_attempt(current, attempt.find(current, manifest['attempt_id']), policy)
    return manifest


def metadata(transport, cfg, manifest, name, *, checkpoint=False):
    command = remote.parent_chk_metadata if checkpoint else remote.metadata
    text = require_ok(transport.run(command(cfg, manifest, name)), 'remote file verification')
    lines = text.splitlines()
    if len(lines) != 2 or not lines[0].isdigit():
        raise ValueError('Invalid remote file metadata')
    digest, _, reported_name = lines[1].partition('  ')
    expected_name = remote.attempt_dir(cfg, manifest) + '/' + remote.filename(name)
    if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest) or reported_name != expected_name:
        raise ValueError('Invalid remote hash response')
    return int(lines[0]), digest


def capacity(cfg):
    """Admission counts all running and queued cores, independent of hardware."""
    return committed_cap(cfg)


def preflight(cfg, ids):
    """Reject changed hard limits before constructing or recording a transport."""
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('Expected unique Attempt IDs')
    manifests = [attempt.read_manifest(attempt.find(cfg, id_)) for id_ in ids]
    if len({m.get('cluster', 'default') for m in manifests}) != 1:
        raise ValueError('Submit one cluster per confirmed batch')
    cfg = for_manifest(cfg, manifests[0])
    if any('node_target' in m for m in manifests) and len(ids) != 1:
        raise ValueError('Submit exactly one targeted Attempt per confirmation')
    for m in manifests:
        node_targeting.validate_binding(cfg, m)
        validate_walltime(cfg, m['walltime'])
    return cfg


def submit(cfg, ids, transport, *, approval_id=None, policy_name=None, autonomous=None):
    from ag import autonomy, autonomy_submission
    if autonomous is not None and (approval_id is not None or policy_name is not None):
        raise ValueError('Autonomous authorization cannot fall back to manual approval')
    if autonomous is not None:
        try:
            return _submit(cfg, ids, transport, autonomous=autonomous)
        except WaitingForRoute:
            raise
        except (ValueError, UnknownSubmission, TransportError):
            # A valid local journal can record the stop even if the lease/rule
            # has just expired. Damaged state remains untouched and blocking.
            for id_ in ids:
                name = attempt.find(cfg, id_).parent.parent.name
                autonomy.pause_if_current_owner(cfg, name, autonomous.get('run_id'), autonomous.get('token'),
                    'Autonomous submission stopped; review retained evidence')
            raise
    with ExitStack() as writers:
        names = sorted({attempt.find(cfg, id_).parent.parent.name for id_ in ids})
        for name in names:
            members = [id_ for id_ in ids if attempt.find(cfg, id_).parent.parent.name == name]
            writers.enter_context(autonomy.manual_write_guard(cfg, name, action='submit', attempt_ids=members))
        return _submit(cfg, ids, transport, approval_id=approval_id,
                       policy_name=policy_name, autonomous=autonomous)


def _submit(cfg, ids, transport, *, approval_id=None, policy_name=None, autonomous=None):
    root_cfg = cfg
    cfg = preflight(cfg, ids)
    if 'node_targeting' in cfg and policy_name is not None:
        raise ValueError('Targeted submission requires explicit node-bound approval or dialog, not a standing policy')
    transport = bound_transport(transport, cfg)
    is_slurm = scheduler_kind(cfg) == 'slurm'
    scheduler_command = 'sbatch' if is_slurm else 'qsub'
    if hasattr(transport, 'record_to'):
        # Autonomous status/journal publication belongs to the short local
        # transactions below, not a transport callback during network IO.
        transport.record_to([] if autonomous is not None else [attempt.find(cfg, id_) for id_ in ids])
    # Existing manual submission keeps its config budget mutex. Autonomous
    # submission takes it only in the short machine -> config transactions.
    configuration_lock = nullcontext() if autonomous is not None else submission_lock(cfg)
    with configuration_lock:
        prepared = []
        for id_ in ids:
            path = attempt.find(cfg, id_)
            m = attempt.read_manifest(path)
            if state.read(path)['state'] != 'prepared' or (path / '.submit-claim').exists():
                raise ValueError('Attempt already consumed or not prepared; submission refused locally')
            if m['cores'] > cfg['resources']['max_cores']:
                raise ValueError('Single job exceeds max_cores')
            files = attempt.verified_files(cfg, path, m)
            prepared.append((path, m, files))
        # Batch confirmation is for a single template and scientific method/card.
        if len({(m['template'], m['science']['route'], m['science']['method_basis']) for _, m, _ in prepared}) != 1:
            raise ValueError('Batch requires the same template, route and method basis')
        autonomous_run = None
        if autonomous is not None:
            if len(prepared) != 1:
                raise ValueError('Each autonomous call binds exactly one object and Attempt')
            autonomous_run = AutonomousSubmission(root_cfg, prepared[0][0], autonomous)
            autonomous_run.validate()
            if is_slurm:
                autonomous_run.collect_slurm_probe(transport)
            authorization = None
        else:
            authorization = approval.authorize(cfg, prepared, approval_id=approval_id, policy_name=policy_name)
        ledgers = budget.shared_ledgers(cfg) if is_slurm else None
        budget_ledger = ledgers[cfg['_cluster']] if is_slurm else None
        query_options = autonomous_run.scheduler_query_options() if autonomous_run is not None else {}
        username, jobs, used = status.inventory(transport, cfg, **query_options)
        if autonomous_run is not None:
            autonomous_run.live = (username, jobs)
        attachments = {}
        for path, m, _ in prepared:
            if 'parent_chk' in m:
                parent = parent_chk.resolve(cfg, m, jobs)
                observed = metadata(transport, cfg, parent, m['parent_chk']['source_name'], checkpoint=True)
                attachments[path.name] = (parent, observed)
        running, queued = (slurm.core_breakdown(jobs, username) if is_slurm else status.core_breakdown(jobs, username))
        if is_slurm:
            held = budget.shared_unobserved_cores(cfg, jobs, ledgers)
            used += held
            queued += held
        cap = capacity(cfg)
        limits = optional_resource_caps(cfg)
        queue_cap = limits.get('max_queued_cores')
        requested = sum(m['cores'] for _, m, _ in prepared)
        if used + requested > cap:
            raise ValueError(f'Core limit exceeded: {used} occupied + {requested} requested / {cap} cap')
        if queue_cap is not None and queued + requested > queue_cap:
            raise ValueError(f'Queued core limit exceeded: {queued} queued + {requested} requested / {queue_cap} cap')
        if is_slurm:
            budget.check(cfg, sum(budget.requested(m) for _, m, _ in prepared), ledger=budget_ledger)
        budget_text = budget.summary(cfg, sum(budget.requested(m) for _, m, _ in prepared)) if is_slurm else None
        destination = f"Cluster: {cfg['_cluster']}\n"
        if 'display_name' in cfg:
            destination = f"Cluster: {cfg['display_name']}（{cfg['_cluster']}）\n"
        if is_slurm:
            destination += f"Partition: {cfg.get('partition', 'scheduler default')}\n"
        text = destination + '\n'.join(f"{m['attempt_id']} | {m['template']} | {m['tier']} {m['cores']} cores | "
                         f"{m['walltime']} | {cards.label(m)} | SHA256 {m['bundle_sha256'][:12]}" +
                         ('' if is_slurm else '\n' + attempt.cost_line(m)) for _, m, _ in prepared)
        shared_text = shared_cap_summary(cfg)
        if shared_text:
            text += '\n' + shared_text
        for path, m, _ in prepared:
            text += '\n' + path.name + '\n' + attempt.resource_summary(cfg, m) + node_targeting.summary(m)
            if path.name in attachments:
                text += '\n' + path.name + ' | ' + parent_chk.summary(m['parent_chk'], attachments[path.name][1])
        text += (f'\n当前占用 {used} 核（运行 {running}、排队 {queued}；按集群上本人全部作业统计，含其他电脑和非 ag 提交的作业），'
                 f'\n提交后合计 {used + requested} / 上限 {cap} 核。'
                 f'\nag 不限制运行中的核数：集群空闲时，排队作业可能同时运行，最多 {used + requested} 核。')
        text += f'\n单作业上限 {cfg["resources"]["max_cores"]} 核。'
        if queue_cap is not None:
            text += f'\n当前排队 {queued} / 排队上限 {queue_cap} 核。'
            text += f'\n提交后排队及未观测预留最多 {queued + requested} / 排队上限 {queue_cap} 核（同集群入口共享）。'
        if 'scheduler_max_running_cores' in limits:
            text += (f'\n配置记录的调度器运行上限 {limits["scheduler_max_running_cores"]} 核；'
                     '由调度器执行，ag 未核实；必须由管理员实施，ag 未设置或验证该限制。')
        if budget_text:
            text += '\n' + budget_text
        # Keep stdout machine-readable for ag submit --json.
        print(text, file=sys.stderr, flush=True)
        if autonomous_run is None and authorization['method'] == 'dialog' and not confirm.confirm(text):
            for path, m, _ in prepared:
                journal.append(path.parent.parent, 'submit', path.name, 'user_cancelled')
            raise UserCancelled('Submission cancelled; Attempts remain prepared')
        # Validate the entire batch before consuming authorization or touching
        # any remote directory; a mismatch in a later Attempt rejects all.
        for path, m, files in prepared:
            if attempt.read_manifest(path) != m or attempt.verified_files(cfg, path, m) != files:
                raise ValueError('Inputs changed during confirmation')
        # Re-query after human confirmation, before authorization/Claim consumption.
        for _, m, _ in prepared:
            node_targeting.fresh_check(cfg, m, transport)
        if autonomous_run is None:
            approval.consume(cfg, prepared, authorization)
        results = []
        submitted = {}
        for path, m, files in prepared:
            # Detect changes while the human was reading the dialog. Upload a private
            # snapshot of the exact bytes already hashed, never mutable source paths.
            if attempt.read_manifest(path) != m or attempt.verified_files(cfg, path, m) != files:
                raise ValueError('Inputs changed during confirmation')
            if autonomous_run is None:
                claim(path / '.submit-claim')
            else:
                # Full per-Attempt science/resource/input summary is frozen
                # before the permanent claim and before any remote mutation.
                summary_options = {'files': files} if hasattr(attempt, 'program_input_name') else {}
                authorization = autonomous_run.consume(attempt.summary(cfg, m, **summary_options) + '\n\n' + text, m, files)
            if is_slurm and autonomous_run is None:
                budget.reserve(cfg, m, budget_ledger)
            if autonomous_run is None:
                state.write(path, 'submitting')
            qsub_started = False
            try:
                # Archive only claimed members; an interrupted batch must leave
                # later prepared members free to submit with fresh authorization.
                if autonomous_run is None:
                    approval.archive(path, authorization, text)
                # Other scheduler clients can submit during the confirmation window.
                if is_slurm:
                    jobs = slurm.parse_queue(require_ok(transport.run(remote.slurm_jobs(user=username, **query_options)), 'squeue'))
                    fresh_running, fresh_queued = slurm.core_breakdown(jobs, username)
                    fresh_used = fresh_running + fresh_queued
                    # Read every peer again; the current reservation is now on
                    # disk, and earlier batch submissions must remain counted.
                    fresh_held = budget.shared_unobserved_cores(
                        cfg, jobs, budget.shared_ledgers(cfg), exclude=m['attempt_id'])
                    fresh_used += fresh_held
                    fresh_queued += fresh_held
                else:
                    jobs = status.parse_jobs(require_ok(transport.run(remote.jobs()), 'qstat'))
                    fresh_running, fresh_queued = status.core_breakdown(jobs, username)
                    fresh_used = fresh_running + fresh_queued
                # qstat can lag behind successful qsub. Reserve earlier batch jobs
                # until visible; do not double count them or reserve visible C jobs.
                visible = {job['job_id'] for job in jobs
                           if (job['owner'] if is_slurm else job['Job_Owner'].split('@')[0]) == username}
                if not is_slurm:
                    fresh_held = sum(cores for job_id, cores in submitted.items() if job_id not in visible)
                    fresh_used += fresh_held
                    fresh_queued += fresh_held
                if fresh_used + m['cores'] > cap:
                    raise ValueError('Core limit changed during confirmation; stop')
                if queue_cap is not None and fresh_queued + m['cores'] > queue_cap:
                    raise ValueError('Queued core limit changed during confirmation; stop')
                if path.name in attachments:
                    parent, observed = attachments[path.name]
                    if parent_chk.resolve(cfg, m, jobs) != parent:
                        raise ValueError('Parent manifest changed during confirmation')
                if autonomous_run is not None:
                    autonomous_run.live = (username, jobs)
                    autonomous_run.boundary('create-directory')
                require_ok(transport.run(remote.create_attempt(cfg, m)), 'new remote Attempt directory')
                if path.name in attachments:
                    attachment = m['parent_chk']
                    detail = dict(source_attempt=parent['attempt_id'], source_name=attachment['source_name'],
                                  target_attempt=m['attempt_id'], target_name='parent.chk',
                                  size=observed[0], sha256=observed[1])
                    with autonomous_run.publication() if autonomous_run is not None else nullcontext():
                        journal.append(path.parent.parent, 'copy_parent_chk', path.name, 'started', detail)
                    try:
                        if autonomous_run is not None:
                            autonomous_run.boundary('copy-parent-checkpoint')
                        require_ok(transport.run(remote.copy_parent_chk(cfg, parent, m)), 'parent chk copy')
                        source_result = metadata(transport, cfg, parent, attachment['source_name'], checkpoint=True)
                        target_result = metadata(transport, cfg, m, 'parent.chk', checkpoint=True)
                        if source_result != observed or target_result != observed:
                            raise ValueError('Parent chk hash/size changed after confirmation or copy; stop')
                    except BaseException:
                        with autonomous_run.publication() if autonomous_run is not None else nullcontext():
                            journal.append(path.parent.parent, 'copy_parent_chk', path.name, 'failed_presubmit', detail)
                        raise
                    with autonomous_run.publication() if autonomous_run is not None else nullcontext():
                        journal.append(path.parent.parent, 'copy_parent_chk', path.name, 'verified', detail)
                with tempfile.TemporaryDirectory(prefix='ag-submit-') as temp:
                    for name, data in files.items():
                        local = Path(temp) / name
                        local.write_bytes(data)
                        if autonomous_run is not None:
                            autonomous_run.boundary('upload')
                        transport.upload(local, m, name)
                        size, digest = metadata(transport, cfg, m, name)
                        if (size, digest) != (len(data), sha256(data).hexdigest()):
                            raise ValueError('Uploaded file hash mismatch; stop')
                # Upload can take time: do not admit using the earlier observation.
                node_targeting.fresh_check(cfg, m, transport)
                if autonomous_run is not None:
                    live_user, live_jobs, _ = status.inventory(transport, cfg, **query_options)
                    autonomous_run.live = (live_user, live_jobs)
                    dispatch_command = autonomous_run.scheduler_submission(cfg, m)
                    autonomous_run.boundary('dispatch')
                else:
                    dispatch_command = remote.slurm_submit(cfg, m) if is_slurm else remote.submit(cfg, m)
                qsub_started = True
                result = transport.run(dispatch_command)
                if result.returncode:
                    if (autonomous_run is None and not is_slurm and result.returncode != 255
                            and result.stderr.lstrip().startswith('qsub:')):
                        qsub_started = False  # scheduler explicitly rejected the request
                        raise ValueError(f'{scheduler_command} explicitly rejected submission; do not resubmit this Attempt')
                    # A diagnostic prefix is not proof that the scheduler never
                    # accepted the request. Autonomous dispatch failures retain
                    # UNKNOWN; only the recorded pre-dispatch abort proves no
                    # submission. Keep the existing manual PBS behavior above.
                    raise UnknownSubmission(f'{scheduler_command} outcome unknown; stop and use read-only status')
                try:
                    job, reported_cluster = slurm.parse_submission(result.stdout) if is_slurm else (remote.job_id(result.stdout.strip()), None)
                    # A known target may only come from the actual fixed bound
                    # command we dispatched, never from a controller probe alone.
                    if reported_cluster is None and autonomous_run is not None:
                        reported_cluster = autonomous_run.scheduler_target
                    # A late exact response may bind an already dispatched job.
                    # Do not hold a study guard: authorization verification reads
                    # that same state, and does not authorize another action.
                    with autonomous_transaction(root_cfg) if autonomous_run is not None else nullcontext():
                        submission.record(path, m, job, scheduler_cluster=reported_cluster,
                                          authorization=authorization)
                        accepted = state.read(path)
                        if autonomous_run is None or accepted['state'] in ('submitting', 'unknown'):
                            accepted = state.write(path, 'submitted', job_id=submission.qualified(m, job))
                        else:
                            # Exact late binding is allowed; rewinding a newer
                            # observer's running/finished/fetched state is not.
                            submission.verified_job(path, m, accepted)
                except ValueError as exc:
                    raise UnknownSubmission(f'Unparseable {scheduler_command} response; stop and use read-only status') from exc
                results.append(dict(attempt_id=path.name, **accepted))
                submitted[job] = m['cores']
            except BaseException as exc:
                if is_slurm and not qsub_started and autonomous_run is None:
                    budget.reject(cfg, m, budget_ledger)
                target = 'unknown' if qsub_started else 'failed_presubmit'
                note = str(exc) if isinstance(exc, (ValueError, TransportError, UnknownSubmission)) else 'Submission interrupted'
                if autonomous_run is not None:
                    autonomous_run.failed(target, note)
                else:
                    state.write(path, target, note=note)
                if qsub_started:
                    raise UnknownSubmission(f'{scheduler_command} outcome unknown; no further remote writes') from exc
                raise
            if autonomous_run is not None and is_slurm:
                # Submission is already known. An extra evidence failure may
                # stop/pause this wake, but never downgrades or resubmits it.
                origin = autonomous_run.capture_origin(transport, reported_cluster)
                if origin is not None:
                    results[-1]['origin'] = origin
            if 'node_target' in m:
                # Acceptance is already durably bound. A placement-query failure
                # must not turn a known job into an ambiguous qsub outcome.
                observed = (autonomous_run.observe_placement(cfg, m, job, transport)
                            if autonomous_run is not None else node_targeting.observe(cfg, path, m, job, transport))
                results[-1] = dict(attempt_id=path.name, **observed)
        return results

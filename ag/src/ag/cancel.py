"""Explicit, separately confirmed cancellation of a recorded exact job ID."""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import os
from pathlib import Path
from ag import attempt, confirm, journal, remote, state, submission
from ag.config import for_manifest, scheduler_kind
from ag.transport import bound_transport
from ag.locks import claim, submission_lock
from ag.submit import UserCancelled
from ag.transport import require_ok


@contextmanager
def _manual_guard(cfg, path):
    from ag import autonomy
    guard = getattr(autonomy, 'manual_write_guard', None)
    if guard is None:
        if os.path.lexists(path.parent.parent / 'autonomy'):
            raise ValueError('Autonomous study requires the integrated manual write guard before cancellation')
        yield
    else:
        try:
            from ag import autonomy_submission  # noqa: F401 — guard dependency, deliberately delayed
        except ImportError as exc:
            raise ValueError('Manual cancellation write guard is not fully integrated') from exc
        with guard(cfg, path.parent.parent.name, action='cancel', attempt_ids=[path.name]):
            yield


def cancel(cfg, path, transport):
    cfg = for_manifest(cfg, attempt.read_manifest(path))
    transport = bound_transport(transport, cfg)
    is_slurm = scheduler_kind(cfg) == 'slurm'
    if hasattr(transport, 'record_to'):
        transport.record_to([path])
    with submission_lock(cfg), _manual_guard(cfg, path):
        m, current = attempt.read_manifest(path), state.read(path)
        residue = current['state'] in ('finished', 'fetched') and current.get('scheduler_residue')
        active = current['state'] in ('submitted', 'running', 'stalled')
        if not (active or residue) or not current.get('job_id'):
            raise ValueError('Cancellation requires an active job or scheduler residue and recorded job ID')
        if (path / '.cancel-claim').exists():
            raise ValueError('Exact-job cancellation already attempted; no retry')
        job = submission.verified_job(path, m, current)
        text = (f"{path.name}\nCluster: {cfg['_cluster']}\nJob: {current['job_id']}\n{m['template']} | {m['tier']} {m['cores']} cores | "
                f"{m['walltime']} | SHA256 {m['bundle_sha256'][:12]}\n"
                f"点「终止作业」将停止 {cfg['_cluster']}:{job}，不会自动重提；"
                "点「保留作业」或按回车保持运行。")
        if not confirm.confirm(text, '取消作业'):
            journal.append(path.parent.parent, 'cancel', path.name, 'user_cancelled')
            raise UserCancelled('Cancellation declined')
        if state.read(path) != current or attempt.read_manifest(path) != m or submission.verified_job(path, m, current) != job:
            raise ValueError('Status changed during confirmation; no cancellation issued')
        # qdel may succeed before SSH drops; an exclusive local claim prevents
        # a later manual invocation from issuing it again after ambiguity.
        claim(path / '.cancel-claim')
        try:
            result = transport.run(remote.slurm_cancel(job) if is_slurm else remote.cancel(job))
            require_ok(result, 'scancel' if is_slurm else 'qdel')
        except BaseException:
            journal.append(path.parent.parent, 'cancel', path.name, 'failed_or_unknown', 'No automatic retry')
            raise
        journal.append(path.parent.parent, 'cancel', path.name, 'succeeded', {'job_id': current['job_id']})
        if is_slurm:
            if residue:
                return state.write(path, current['state'], exit_status=current.get('exit_status'),
                                   note='Confirmed exact-job scancel accepted', cleanup_status='scancel_accepted')
            return state.write(path, 'cancelled', note='Confirmed exact-job scancel accepted')
        if residue:
            return state.write(path, current['state'], exit_status=current.get('exit_status'),
                               note='Scheduler cleanup qdel accepted; removal not yet verified',
                               cleanup_status='qdel_accepted')
        return state.write(path, 'cancelled', note='Confirmed exact-job qdel succeeded')


class AutonomousCancellationUnknown(ValueError):
    """A consumed cancellation has no reliable completed local acknowledgement."""


def _accepted_cancellation(path, ownership, reads):
    """Read and hash immutable ownership outside every publication mutex."""
    from ag import autonomy_cancel as evidence
    from ag import _autonomy_store as disk
    def pin_directories():
        reads.directory(path / 'inputs')  # Its complete file set is part of the bundle.
        for name in ('autonomy-reservations', 'autonomy-studies'):
            directory = Path.home() / '.config/ag' / name
            fd = disk.directory(directory)
            try:
                info = os.fstat(fd)
            finally:
                os.close(fd)
            identity = (info.st_dev, info.st_ino)
            if reads.identities.setdefault(directory, identity) != identity:
                raise ValueError('Original autonomous ownership registry directory was replaced')
    pin_directories()
    request, request_sha = evidence._canonical_slurm_record(path / 'autonomy-cancel-request.json')
    response, response_sha = evidence._canonical_slurm_record(path / 'autonomy-cancel-response.json')
    record, owner_hash = ownership._scientific_reservation(path)
    ownership._owned_audit(path, record, owner_hash)
    binding = evidence.bound_attempt(path)
    evidence.read_bytes(path / '.cancel-claim')
    pin_directories()
    return dict(binding=binding, ownership_sha256=owner_hash, reservation=record,
                request=request, request_sha256=request_sha, response=response, response_sha256=response_sha,
                consumption_sha256=response.get('consumption_sha256'))


def _check_accepted_cancellation(path, current, ownership, prepared):
    """Compare prepared bytes with freshly replayed consumption, without IO."""
    request, response = prepared['request'], prepared['response']
    binding, owner_hash = prepared['binding'], prepared['ownership_sha256']
    ownership._check_consumption(prepared['reservation'], owner_hash, current)
    consumed = current.get('cancellations', {}).get(path.name)
    result = current.get('cancellation_results', {}).get(path.name)
    if (request.get('schema') != 'ag-autonomy-cancel-request/1'
            or response.get('schema') != 'ag-autonomy-cancel-response/1'
            or not isinstance(consumed, dict) or not isinstance(result, dict)
            or request.get('binding') != binding or consumed.get('binding') != binding
            or request.get('ownership_sha256') != owner_hash
            or consumed.get('ownership_sha256') != owner_hash
            or consumed.get('evidence_sha256') != prepared['request_sha256']
            or response.get('request_sha256') != prepared['request_sha256']
            or response.get('consumption_sha256') != consumed.get('consumption_sha256')
            or result.get('consumption_sha256') != consumed.get('consumption_sha256')
            or result.get('evidence_sha256') != prepared['response_sha256']
            or response.get('outcome') != 'accepted' or result.get('outcome') != 'accepted'
            or response.get('dispatched') is not True
            or any(request.get(key) != consumed.get(key) for key in
                   ('kind', 'reason', 'round_id', 'run_id', 'plan_sha256'))
            or result.get('run_id') != consumed.get('run_id')):
        raise ValueError('Stopping proof requires an intact accepted cancellation and its actual consumption')
    return deepcopy(dict(consumed=consumed, result=result))


def verify_stopped(cfg, path, transport, *, run_id, token, plan_sha256):
    """Observe one accepted cancellation and publish exact-instance stop proof.

    This path never sends a cancellation or prepares a replacement. A paused
    owner may observe; later preparation still requires current action checks.
    """
    from ag import autonomy, autonomy_cancel as evidence, status, study, submit
    from ag import _autonomy_store as disk
    study.identifier(run_id)
    autonomy.text(token, 'Current run token')
    autonomy._cancellation_hash(plan_sha256)
    try:
        from ag import autonomy_submission as ownership
        if any(not callable(getattr(module, name, None)) for module, name in (
                (submit, 'autonomous_configuration'), (autonomy, 'observation_publication_guard'),
                (autonomy, 'pause_if_current_owner'), (ownership, '_capture_reads'),
                (ownership, '_scientific_reservation'), (ownership, '_owned_audit'),
                (ownership, '_check_consumption'))):
            raise ImportError('Required owner publication interface is absent')
    except ImportError as exc:
        raise ValueError('T186 ownership and observation publication interfaces are not integrated') from exc
    original = deepcopy(submit.autonomous_configuration(cfg))
    path = study.local_path(Path(original['local']['studies_root']), Path(path))
    name = path.parent.parent.name
    if path.parent.name != 'attempts' or path.parent.parent != study.locate(original, name):
        raise ValueError('Stopping proof requires an exact Attempt inside its study')
    selected = for_manifest(original, attempt.read_manifest(path))
    if scheduler_kind(selected) != 'slurm':
        raise ValueError('Autonomous stopping proof currently requires Slurm evidence')
    directory = disk.directory(path)
    store = disk.Store(directory)
    filename = 'autonomy-cancel-stopped.json'

    @contextmanager
    def publication():
        with submission_lock(selected):
            fresh = submit.autonomous_configuration(cfg)
            if fresh != original or for_manifest(fresh, attempt.read_manifest(path)) != selected:
                raise ValueError('Configuration changed during stopping observation')
            fd = disk.directory(path)
            try:
                held, named = os.fstat(directory), os.fstat(fd)
                if (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino):
                    raise ValueError('Stopping proof Attempt directory was replaced')
            finally:
                os.close(fd)
            with autonomy.observation_publication_guard(original, name, run_id, token,
                    action='observe', plan_sha256=plan_sha256) as current:
                yield current

    def recheck_owner(current):
        versions = autonomy.versions()
        at = autonomy.number(autonomy.now())
        if at < current['updated_at']:
            raise ValueError('Autonomy clock moved backwards during stopping review')
        autonomy.eligible(current, run_id, sha256(token.encode()).hexdigest(), versions,
                          at, 'observe', plan_sha256)

    try:
        cancellation_exists = False
        try:
            with publication() as current:
                cancellation_exists = path.name in current.get('cancellations', {})
            with ownership._capture_reads() as reads:
                initial = _accepted_cancellation(path, ownership, reads)
            with publication() as current:
                reads.verify()
                initial_ledger = _check_accepted_cancellation(path, current, ownership, initial)
                recheck_owner(current)
        except (ValueError, OSError):
            if cancellation_exists:
                autonomy.pause_if_current_owner(original, name, run_id, token,
                    'Existing cancellation acknowledgement cannot be verified; preserve evidence and do not replace the job')
            raise
        try:
            os.stat(filename, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ValueError('Stopping proof already published; inspect its immutable record')
        transport = bound_transport(transport, selected)
        if hasattr(transport, 'record_to'):
            transport.record_to([])
        try:
            observation = status.capture_slurm_evidence(selected, path, transport,
                include_cancel_version=True, publication=publication)
            with ownership._capture_reads() as reads:
                final = _accepted_cancellation(path, ownership, reads)
                if final != initial:
                    raise ValueError('Cancellation binding changed during stopping observation')
                proof = evidence.verify_slurm_stopped(path,
                    ownership_sha256=final['ownership_sha256'], observation=observation,
                    cancel_response=dict(response='autonomy-cancel-response.json',
                                         response_sha256=final['response_sha256']))
                value = dict(schema='ag-autonomy-cancel-stopped/1', **proof,
                             verified_run_id=run_id, verified_plan_sha256=plan_sha256,
                             recorded_at=autonomy.now())
                raw = disk.encode(value)
            with publication() as current:
                reads.verify()
                final_ledger = _check_accepted_cancellation(path, current, ownership, final)
                if final_ledger != initial_ledger:
                    raise ValueError('Cancellation consumption or result changed during stopping review')
                recheck_owner(current)
                store.exclusive(filename, raw)
        except (ValueError, OSError) as exc:
            autonomy.pause_if_current_owner(original, name, run_id, token,
                'Cancellation stopping evidence is insufficient; preserve consumption and do not replace the job')
            raise ValueError('Exact-instance stopping proof unavailable; no replacement is permitted') from exc
        return dict(value, evidence=filename, evidence_sha256=sha256(raw).hexdigest())
    finally:
        os.close(directory)


def _reroute_cancellation_selection(cfg, current, context, reservation, manifest, policy, prepared_stops):
    """Use the existing exact-source selector; never duplicate its ordering."""
    from datetime import datetime, timezone
    from ag import approval, autonomy, autonomy_policy, route
    from ag.config import select_cluster, shared_clusters
    record, owner_hash = reservation['record'], reservation['sha256']
    if 'reroute_source' in record or owner_hash in current.get('reroute_lineages', {}):
        raise ValueError('Reroute already consumed for this original submission lineage')
    original = record.get('selection', {})
    original_request = original.get('input', {}).get('request', {})
    original_result = original.get('result', {})
    original_choice = original_result.get('recommendation')
    if (original_result.get('schema') != 'ag-routing-ladder/1'
            or original_request.get('job_class') not in ('main', 'small')
            or not isinstance(original_choice, dict) or not original_choice.get('cell_id')):
        raise ValueError('Reroute requires the original verified ladder position and job class')
    source = dict(study_key=record['study_key'], attempt_id=record['attempt_id'], record_sha256=owner_hash)
    selection = route.autonomous_selection(cfg, current,
        dict(context, object_id=record['object_id'], job_class=original_request['job_class']),
        template=manifest['template'], walltime=manifest['walltime'], requested_tier=manifest['tier'],
        parent_cluster=manifest.get('parent_chk', {}).get('cluster'), evaluate_from=source,
        prepared_stops=prepared_stops)
    result = selection.get('result', {})
    choice = result.get('recommendation')
    if (selection.get('input', {}).get('request', {}).get('evaluate_from') != source
            or result.get('evaluation_only') is not True or result.get('evaluate_from') != source
            or not isinstance(choice, dict) or choice.get('eligible') is not True
            or choice.get('needs_queue') is not False
            or choice.get('capacity', {}).get('availability') != 'enough'
            or choice.get('cell_id') == original_choice['cell_id']):
        raise ValueError('Reroute requires a strictly higher selector candidate with current immediate capacity')
    cluster, cores = choice['cluster'], choice['cores']
    if (manifest['template'] not in policy['templates'] or cluster not in policy['clusters']
            or type(cores) is not int or not 0 < cores <= policy['max_cores_per_job']
            or approval.walltime_seconds(manifest['walltime']) > approval.walltime_seconds(policy['max_walltime'])):
        raise ValueError('Reroute candidate exceeds the current policy template, cluster, cores or walltime scope')
    nodes = policy['clusters'][cluster]['nodes']
    target = choice.get('target_node')
    if (target is None and nodes) or (target is not None and target not in nodes):
        raise ValueError('Reroute candidate does not match the current policy node scope')
    selected = select_cluster(cfg, cluster)
    usage = route._ladder_usage(cfg, cluster, selection['input']['snapshots'], selection['input']['placements'],
                                datetime.fromtimestamp(autonomy.now(), timezone.utc))
    occupancy = [dict(clusters=list(shared_clusters(selected)), committed_cores=usage['committed'],
        queued_cores=usage['queued'], jobs=sum(p.get('run_id') is not None for p in usage['active']),
        requested_cores=cores, requested_jobs=1)]
    account_job_cap = route.autonomous_account_job_cap(cfg, cluster)
    if account_job_cap is not None and occupancy[0]['jobs'] + 1 > account_job_cap:
        raise ValueError('Bound routing shared-account autonomous job limit exceeded')
    budget = autonomy_policy.check_budget(policy, plan_spec=current['plans'][current['current_plan']]['body']['spec'],
        round_attempts=sum(item['round_id'] == current['current_round'] for item in current['submissions'].values()),
        requested_attempts=1, occupancy=occupancy)
    if budget['pause_after_consumption']:
        raise ValueError('Reroute successor would pause at its submission consumption; cancellation refused')
    return dict(lineage_sha256=owner_hash, routing_selection=selection)


def autonomous_cancel(cfg, path, transport, *, run_id, token, plan_sha256,
                      policy_name, kind, reason, reviews=None):
    """Cancel one owned Slurm instance once; acceptance never proves it stopped.

    Network IO is outside config/machine/study locks. Immutable late responses
    belong to the original consumed operation, not to a new lease or action.
    """
    from ag import autonomy, autonomy_cancel as evidence, status, study, submit
    from ag import _autonomy_store as disk
    study.identifier(run_id)
    study.identifier(policy_name)
    autonomy.text(token, 'Current run token')
    autonomy.text(reason, 'Cancellation reason')
    autonomy._cancellation_hash(plan_sha256)
    if kind not in ('no_progress', 'reroute'):
        raise ValueError('Unsupported autonomous cancellation kind')
    if kind == 'no_progress' and (not isinstance(reviews, list) or len(reviews) != 2):
        raise ValueError('No-progress cancellation requires two formal snapshot reviews')
    if kind == 'reroute':
        if reviews is not None:
            raise ValueError('Reroute uses formal queue evidence, not no-progress reviews')
        from inspect import signature
        from ag import route
        if any(not callable(getattr(route, name, None)) or 'evaluate_from' not in signature(
                getattr(route, name)).parameters for name in ('autonomous_selection', 'select_ladder')):
            raise ValueError('Autonomous reroute cancellation requires the integrated T185 exact-source selector')
        if ('prepared_stops' not in signature(route.autonomous_selection).parameters
                or any(not callable(getattr(route, name, None)) for name in
                       ('_ladder_usage', 'autonomous_account_job_cap'))):
            raise ValueError('Autonomous reroute cancellation requires the integrated T186 stopped-reservation adapter')
    try:
        from ag import autonomy_submission as ownership
        if any(not callable(getattr(module, name, None)) for module, name in (
                (submit, 'autonomous_configuration'), (submit, 'bound_policy'),
                (autonomy, 'observation_publication_guard'), (autonomy, '_cancellation_guard'),
                (ownership, 'machine_lock'), (ownership, '_capture_reads'),
                (ownership, '_scientific_reservation'), (ownership, '_owned_audit'),
                (ownership, '_check_consumption'), (ownership, 'authorization'))):
            raise ImportError('Required autonomous ownership/publication interface is absent')
        if kind == 'reroute':
            from ag import autonomy_policy
            if (not callable(getattr(ownership, 'prepare_stopped_reservations', None))
                    or not callable(getattr(autonomy_policy, 'check_budget', None))):
                raise ImportError('Required reroute budget and stopped-reservation interface is absent')
    except ImportError as exc:
        raise ValueError('T186 autonomous ownership and publication interfaces are not integrated') from exc

    original_cfg = deepcopy(submit.autonomous_configuration(cfg))
    path = study.local_path(Path(original_cfg['local']['studies_root']), Path(path))
    if path.parent.name != 'attempts' or path.parent.parent != study.locate(original_cfg, path.parent.parent.name):
        raise ValueError('Cancellation requires an exact Attempt inside its study')
    selected = for_manifest(original_cfg, attempt.read_manifest(path))
    if scheduler_kind(selected) != 'slurm':
        raise ValueError('Autonomous exact-instance cancellation currently requires Slurm evidence')
    context = dict(study_id=path.parent.parent.name, run_id=run_id, token=token,
                   policy_name=policy_name, plan_sha256=plan_sha256)
    reviews = deepcopy(reviews)
    request_name, response_name = 'autonomy-cancel-request.json', 'autonomy-cancel-response.json'
    directory = disk.directory(path)
    store = disk.Store(directory)

    def same_directory():
        fd = disk.directory(path)
        try:
            current, held = os.fstat(fd), os.fstat(directory)
            if (current.st_dev, current.st_ino) != (held.st_dev, held.st_ino):
                raise ValueError('Cancellation Attempt directory was replaced')
        finally:
            os.close(fd)

    def fresh_configuration():
        fresh = submit.autonomous_configuration(cfg)
        if fresh != original_cfg or for_manifest(fresh, attempt.read_manifest(path)) != selected:
            raise ValueError('Autonomous configuration changed during cancellation; no cached transport target')
        same_directory()
        return fresh

    def unclaimed():
        for name in ('.cancel-claim', request_name, response_name):
            try:
                os.stat(name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise ValueError('Exact-job cancellation already attempted or has preserved evidence; no retry')

    def prepare(current, observation=None):
        # The real T186 receipt records metadata while all input/log hashing
        # and scheduler parsing run outside config, machine and study locks.
        prepared_stops = (ownership.prepare_stopped_reservations(original_cfg,
            states={str(path.parent.parent): current['state']}) if kind == 'reroute' else None)
        with ownership._capture_reads() as reads:
            reads.directory(path / 'inputs')
            registry_identities = {}
            for name in ('autonomy-reservations', 'autonomy-studies'):
                registry = Path.home() / '.config/ag' / name
                fd = disk.directory(registry)
                try:
                    info = os.fstat(fd)
                finally:
                    os.close(fd)
                registry_identities[registry] = (info.st_dev, info.st_ino)
            reads.identities.update(registry_identities)
            record, owner_hash = ownership._scientific_reservation(path)
            ownership._owned_audit(path, record, owner_hash)
            binding = evidence.bound_attempt(path)
            manifest = disk.decode(evidence.read_bytes(path / 'manifest.json'))
            submitted = disk.decode(evidence.read_bytes(path / 'submission.json'))
            proof = {}
            if kind == 'no_progress':
                proof['no_progress'] = evidence._review_no_progress_locked(path, current=current,
                    run_id=run_id, plan_sha256=plan_sha256, reviews=reviews)
                if proof['no_progress']['binding'] != binding:
                    raise ValueError('No-progress snapshots belong to a different job binding')
            if observation is not None:
                if kind == 'reroute':
                    proof['reroute_queue'] = evidence.review_reroute_queue(path,
                        ownership_sha256=owner_hash, observation=observation)
                    proof['slurm_instance'] = proof['reroute_queue']['slurm_instance']
                else:
                    proof['slurm_instance'] = evidence.verify_slurm_instance(path,
                        ownership_sha256=owner_hash, observation=observation)
        return dict(reads=reads, current=current, binding=binding, manifest=manifest, submitted=submitted,
                    reservation=dict(record=record, sha256=owner_hash), proof=proof, prepared_stops=prepared_stops)

    def verify(guard, prepared):
        fresh = fresh_configuration()
        unclaimed()
        prepared['reads'].verify()
        public = guard.current
        if any(public[key] != prepared['current'][key] for key in ('seq', 'journal_sha256')):
            raise ValueError('Autonomy journal changed during unlocked cancellation evidence review')
        current = guard.snapshot
        policy, rule_hash = submit.bound_policy(fresh, current, context)
        reservation = prepared['reservation']
        record, owner_hash = reservation['record'], reservation['sha256']
        ownership._check_consumption(record, owner_hash, current)
        binding, submitted = prepared['binding'], prepared['submitted']
        consumed = current.get('submissions', {}).get(path.name)
        if (not isinstance(consumed, dict) or consumed.get('dispatch_started') is None
                or consumed.get('aborted_before_dispatch') is not None
                or record.get('round_id') != current['current_round']
                or record.get('plan_sha256') != plan_sha256
                or record.get('rule_sha256') != rule_hash or record.get('policy_name') != policy_name
                or record.get('study_id') != context['study_id'] or record.get('attempt_id') != path.name
                or record.get('manifest_sha256') != binding['manifest_sha256']
                or consumed.get('ownership_sha256') != owner_hash
                or submitted.get('authorization') != ownership.authorization(record, owner_hash)
                or submitted.get('authorization', {}).get('method') != 'autonomy-policy'):
            raise ValueError('Cancellation requires intact dispatched ownership in the current round and effective rule')
        result = dict(binding=binding, ownership_sha256=owner_hash, rule_sha256=rule_hash,
                      round_id=current['current_round'], **prepared['proof'])
        if kind == 'reroute':
            result.update(_reroute_cancellation_selection(fresh, current, context, reservation,
                prepared['manifest'], policy, prepared['prepared_stops']))
        if 'slurm_instance' in result:
            instance = result['slurm_instance']
            expected = {key: consumed[key] for key in
                        ('ownership_sha256', 'round_id', 'run_id', 'plan_sha256', 'dispatch_started')}
            if instance['binding'] != binding or instance['origin_dispatch'] != expected:
                raise ValueError('Original scheduler instance differs from the consumed dispatch')
            if kind == 'no_progress' and instance['current_instance']['state'] not in ('RUNNING', 'SUSPENDED'):
                raise ValueError('No-progress cancellation requires a currently running or suspended instance')
        guard.recheck()
        return result

    @contextmanager
    def publication():
        # This factory is invoked only around a local publication, never IO.
        with submission_lock(selected):
            fresh_configuration()
            with autonomy.observation_publication_guard(original_cfg, context['study_id'], run_id, token,
                    action='observe', plan_sha256=plan_sha256) as current:
                if evidence.bound_attempt(path) != initial['binding']:
                    raise ValueError('Cancellation job binding changed before observation publication')
                yield current

    response = receipt = request = None
    try:
        with submission_lock(selected), ownership.machine_lock(create=False), autonomy._cancellation_guard(
                original_cfg, context['study_id'], run_id, token, plan_sha256=plan_sha256) as guard:
            fresh = fresh_configuration()
            unclaimed()
            submit.bound_policy(fresh, guard.snapshot, context)
            baseline = guard.current
        prepared = prepare(baseline)
        with submission_lock(selected), ownership.machine_lock(create=False), autonomy._cancellation_guard(
                original_cfg, context['study_id'], run_id, token, plan_sha256=plan_sha256) as guard:
            initial = verify(guard, prepared)
        transport = bound_transport(transport, selected)
        if hasattr(transport, 'record_to'):
            transport.record_to([])  # Late SSH diagnostics must not mutate ordinary Attempt status.
        observation = status.capture_slurm_evidence(selected, path, transport,
            include_cancel_version=True, publication=publication)
        with submission_lock(selected), ownership.machine_lock(create=False), autonomy._cancellation_guard(
                original_cfg, context['study_id'], run_id, token, plan_sha256=plan_sha256) as guard:
            fresh_configuration()
            unclaimed()
            baseline = guard.current
        prepared = prepare(baseline, observation)
        dispatched, failure = False, None
        started = autonomy.now()
        try:
            with submission_lock(selected), ownership.machine_lock(create=False), autonomy._cancellation_guard(
                    original_cfg, context['study_id'], run_id, token, plan_sha256=plan_sha256) as guard:
                checked = verify(guard, prepared)
                if any(checked[key] != initial[key] for key in ('binding', 'ownership_sha256', 'rule_sha256', 'round_id')):
                    raise ValueError('Cancellation ownership changed during scheduler observation')
                job = checked['slurm_instance']['current_instance']
                target = dict(scheduler_cluster=job['cluster'], uid=job['uid'], job_name=job['name'],
                              sluid=job['sluid'], purpose=kind)
                command = remote.slurm_cancel_instance(**target)
                request = dict(schema='ag-autonomy-cancel-request/1', **checked, target=target,
                               run_id=run_id, plan_sha256=plan_sha256, policy_name=policy_name,
                               kind=kind, reason=reason, command=command.text, operation=command.operation,
                               timeout=command.timeout, recorded_at=autonomy.now())
                request_bytes = disk.encode(request)
                request_hash = sha256(request_bytes).hexdigest()
                store.exclusive(request_name, request_bytes)
                # Large evidence reads may outlast the rule even while the
                # plan and wake remain valid. Re-read it at the consume edge.
                fresh = fresh_configuration()
                _, final_rule_hash = submit.bound_policy(fresh, guard.snapshot, context)
                if final_rule_hash != checked['rule_sha256']:
                    raise ValueError('Autonomous cancellation rule changed before consumption')
                receipt = guard.consume(binding=checked['binding'], ownership_sha256=checked['ownership_sha256'],
                                        kind=kind, reason=reason, evidence_sha256=request_hash,
                                        **({'lineage_sha256': checked['lineage_sha256']} if kind == 'reroute' else {}))
                # consume creates a pending action: never re-enter an action
                # guard or recheck cancel eligibility before this one claim.
                started = autonomy.now()
                store.exclusive('.cancel-claim', b'Claimed permanently; never retry this exact cancellation.\n')
                claim_bytes = store.read('.cancel-claim')
        except BaseException as exc:
            if receipt is None:
                raise  # No known durable receipt: preserve evidence, never dispatch.
            # A lock's final verification can fail after consumption and claim.
            # Record that consequence outside all locks before returning.
            failure = exc
        result = None
        if failure is None:
            dispatched = True
            try:
                result = transport.run(command)
                if (type(result.returncode) is not int or not isinstance(result.stdout, str)
                        or not isinstance(result.stderr, str)):
                    raise ValueError('Invalid cancellation response')
                require_ok(result, 'scancel')
                if result.stderr.strip():
                    raise ValueError('Cancellation returned diagnostics; result is uncertain')
            except BaseException as exc:
                failure = exc
        finished = autonomy.now()
        if finished < started and failure is None:
            failure = ValueError('Clock moved backwards during cancellation')
        response = dict(schema='ag-autonomy-cancel-response/1', request_sha256=request_hash,
                        consumption_sha256=receipt['record']['consumption_sha256'],
                        started_at=started, finished_at=finished, dispatched=dispatched,
                        returncode=getattr(result, 'returncode', None),
                        stdout=getattr(result, 'stdout', ''), stderr=getattr(result, 'stderr', ''),
                        exception=dict(type=type(failure).__name__, message=str(failure)) if failure else None,
                        outcome='unknown' if failure else 'accepted', stopped=False)
        for stream in ('stdout', 'stderr'):
            if not isinstance(response[stream], str):
                response[stream] = repr(response[stream])
            response[stream + '_sha256'] = sha256(response[stream].encode()).hexdigest()
        if type(response['returncode']) is not int:
            response['returncode'] = None
        response_bytes = disk.encode(response)
        response_hash = sha256(response_bytes).hexdigest()
        answer = dict(schema='ag-autonomous-cancel/1', outcome=response['outcome'], stopped=False,
                      binding=request['binding'], request=request_name, request_sha256=request_hash,
                      response=response_name, response_sha256=response_hash,
                      consumption_sha256=response['consumption_sha256'], status_published=False)
        try:
            same_directory()
            if store.read(request_name) != request_bytes or (dispatched and store.read('.cancel-claim') != claim_bytes):
                raise ValueError('Original cancellation request or claim changed before its response')
            store.exclusive(response_name, response_bytes)
        except BaseException as exc:
            failure = exc
            answer.update(outcome='unknown', response_saved=False)
        try:
            autonomy._record_cancellation_result(original_cfg, context['study_id'], run_id, token,
                attempt_id=path.name, consumption_sha256=response['consumption_sha256'],
                outcome=answer['outcome'], reason='scancel accepted; termination not verified' if failure is None
                else 'Cancellation outcome or response preservation uncertain; never retry', evidence_sha256=response_hash)
        except BaseException as exc:
            failure = exc
            answer['outcome'] = 'unknown'
        if failure is not None:
            error = AutonomousCancellationUnknown('Cancellation consumed; outcome is uncertain. Preserve evidence; never retry.')
            error.evidence = dict(answer, response_record=response)
            raise error from failure
        try:
            with publication():
                # Ordinary lifecycle publication needs a current owner. A late
                # result can only retain the immutable response and ledger event.
                if state.read(path)['state'] not in ('submitted', 'running', 'stalled'):
                    raise ValueError('Attempt lifecycle changed before cancellation acknowledgement')
                journal.append(path.parent.parent, 'cancel', path.name, 'succeeded',
                               dict(job_id=submission.qualified(attempt.read_manifest(path), request['binding']['job_id']),
                                    request_sha256=request_hash, response_sha256=response_hash))
                state.write(path, 'cancelled', note='Autonomous exact-instance scancel accepted; termination not verified')
                answer['status_published'] = True
        except (ValueError, OSError):
            # This is not a second action and never reopens a closed run.
            pass
        return answer
    finally:
        os.close(directory)

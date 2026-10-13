"""Single-use submission. Ambiguous qsub outcomes stop the entire batch."""
from hashlib import sha256
from pathlib import Path
import tempfile
from ag import attempt, confirm, journal, remote, state, status
from ag.locks import claim, submission_lock
from ag.transport import require_ok, TransportError


class UnknownSubmission(RuntimeError):
    pass


class UserCancelled(ValueError):
    pass


def metadata(transport, cfg, manifest, name):
    text = require_ok(transport.run(remote.metadata(cfg, manifest, name)), 'remote file verification')
    lines = text.splitlines()
    if len(lines) != 2 or not lines[0].isdigit():
        raise ValueError('Invalid remote file metadata')
    digest, _, reported_name = lines[1].partition('  ')
    expected_name = remote.attempt_dir(cfg, manifest) + '/' + remote.filename(name)
    if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest) or reported_name != expected_name:
        raise ValueError('Invalid remote hash response')
    return int(lines[0]), digest


def submit(cfg, ids, transport):
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('Expected unique Attempt IDs')
    with submission_lock(cfg):
        prepared = []
        for id_ in ids:
            path = attempt.find(cfg, id_)
            m = attempt.read_manifest(path)
            if state.read(path)['state'] != 'prepared' or (path / '.submit-claim').exists():
                raise ValueError('Attempt already consumed or not prepared; submission refused locally')
            files = attempt.verified_files(cfg, path, m)
            prepared.append((path, m, files))
        # Batch confirmation is for a single template and scientific method/card.
        if len({(m['template'], m['science']['route'], m['science']['method_basis']) for _, m, _ in prepared}) != 1:
            raise ValueError('Batch requires the same template, route and method basis')
        _, _, used = status.inventory(transport)
        requested = sum(m['cores'] for _, m, _ in prepared)
        if used + requested > cfg['resources']['max_cores']:
            raise ValueError(f'Core limit exceeded: {used} occupied + {requested} requested')
        text = '\n'.join(f"{m['attempt_id']} | {m['template']} | {m['tier']} {m['cores']} cores | "
                         f"{m['walltime']} | SHA256 {m['bundle_sha256'][:12]}" for _, m, _ in prepared)
        text += f'\n提交后总核数：{used + requested} / {cfg["resources"]["max_cores"]}'
        if not confirm.confirm(text):
            for path, m, _ in prepared:
                journal.append(path.parent.parent, 'submit', path.name, 'user_cancelled')
            raise UserCancelled('Submission cancelled; Attempts remain prepared')
        results = []
        for path, m, files in prepared:
            # Detect changes while the human was reading the dialog. Upload a private
            # snapshot of the exact bytes already hashed, never mutable source paths.
            if attempt.read_manifest(path) != m or attempt.verified_files(cfg, path, m) != files:
                raise ValueError('Inputs changed during confirmation')
            claim(path / '.submit-claim')
            state.write(path, 'submitting')
            qsub_started = False
            try:
                # Other scheduler clients can submit during the confirmation window.
                _, _, fresh_used = status.inventory(transport)
                if fresh_used + m['cores'] > cfg['resources']['max_cores']:
                    raise ValueError('Core limit changed during confirmation; stop')
                require_ok(transport.run(remote.create_attempt(cfg, m)), 'new remote Attempt directory')
                with tempfile.TemporaryDirectory(prefix='ag-submit-') as temp:
                    for name, data in files.items():
                        local = Path(temp) / name
                        local.write_bytes(data)
                        transport.upload(local, m, name)
                        size, digest = metadata(transport, cfg, m, name)
                        if (size, digest) != (len(data), sha256(data).hexdigest()):
                            raise ValueError('Uploaded file hash mismatch; stop')
                qsub_started = True
                result = transport.run(remote.submit(cfg, m))
                if result.returncode:
                    if result.returncode != 255 and result.stderr.lstrip().startswith('qsub:'):
                        qsub_started = False  # scheduler explicitly rejected the request
                        raise ValueError('qsub explicitly rejected submission; do not resubmit this Attempt')
                    raise UnknownSubmission('qsub outcome unknown; stop and use read-only status')
                try:
                    job = remote.job_id(result.stdout.strip())
                except ValueError as exc:
                    raise UnknownSubmission('Unparseable qsub response; stop and use read-only status') from exc
                results.append(dict(attempt_id=path.name, **state.write(path, 'submitted', job_id=job)))
            except BaseException as exc:
                target = 'unknown' if qsub_started else 'failed_presubmit'
                state.write(path, target, note=str(exc) if isinstance(exc, (ValueError, TransportError, UnknownSubmission)) else 'Submission interrupted')
                if qsub_started:
                    raise UnknownSubmission('qsub outcome unknown; no further remote writes') from exc
                raise
        return results

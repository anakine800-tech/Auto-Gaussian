"""Read-only acceptance baseline for an explicit existing Attempt.

Use an installed candidate environment. Evidence contains private IDs and must
stay outside version control. This does not parse logs or accept science.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote

from auto_g16.core import SQLiteRuntimeStore
from auto_g16.query import QueryService
from auto_g16.result import GaussianResultQuery, ResultProvenanceService


def fingerprint(database):
    fd = os.open(database, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        digest = hashlib.sha256()
        while chunk := os.read(fd, 1024 * 1024):
            digest.update(chunk)
        return {'sha256': digest.hexdigest(), 'size': str(info.st_size), 'inode': str(info.st_ino),
                'mtime_ns': str(info.st_mtime_ns), 'ctime_ns': str(info.st_ctime_ns),
                'directory_entries': sorted(p.name for p in database.parent.iterdir())}
    finally:
        os.close(fd)


def require_equal(left, right):
    if left != right:
        raise ValueError("stored facts differ from Result DTO")


def export(database, attempt_id, destination):
    before = fingerprint(database)
    with SQLiteRuntimeStore.read_snapshot(database) as store:
        attempt = store.load_attempt(attempt_id)
        task = store.load_task(attempt.task_id)
        run = store.load_workflow_run(task.workflow_run_id)
        view = ResultProvenanceService(store).current_view(attempt_id)
        dto = GaussianResultQuery(store).get_summary(attempt_id)
        if dto['availability'] != 'available' or not view.selected_results:
            raise ValueError('explicit source has no qualified Gaussian summary')
        record = view.selected_results[-1]
        facts = record.facts
        require_equal(dto['source']['result_id'], record.result_id)
        require_equal(dto['source']['envelope_id'], view.selected_envelope_id)
        require_equal(dto['source']['input']['sha256'], view.input_binding.sha256)
        summary = dto['summary']
        require_equal(summary['final_energy_hartree'], facts['final_energy_hartree'])
        require_equal(summary['termination'], {'status': facts['program_status'], 'normal_count': facts['normal_termination_count'], 'error_count': facts['error_termination_count']})
        require_equal(summary['optimization'], {'completed_marker': facts['optimization_completed_marker'], 'stationary_point_marker': facts['stationary_point_marker']})
        require_equal(summary['frequency'], {'availability': 'available' if facts['frequency_count'] else 'missing',
            'count': facts['frequency_count'] or None, 'imaginary_count': facts['imaginary_frequency_count'] if facts['frequency_count'] else None})
        source_fact_checks = {'result_identity': True, 'selected_envelope': True, 'input_digest': True,
                              'energy': True, 'termination': True, 'optimization': True, 'frequency': True}
    q = QueryService(database)
    project_path = '/api/projects/' + quote(run.project_id, safe='')
    attempt_path = '/api/attempts/' + quote(attempt_id, safe='')
    expected = {'/api/projects': q.list_projects(), project_path: q.get_project(run.project_id),
                project_path + '/tasks': q.list_tasks(run.project_id),
                project_path + '/attempts': q.list_attempts(project_id=run.project_id),
                attempt_path: q.get_attempt(attempt_id), attempt_path + '/result': dto}
    after = fingerprint(database)
    if before != after:
        raise ValueError('source changed during acceptance baseline')
    destination.mkdir(parents=True, exist_ok=False)
    evidence = {'schema': 'autog-real-source-expectations/1', 'database': str(database),
                'attempt_id': attempt_id, 'project_id': run.project_id, 'before': before,
                'source_fact_checks': source_fact_checks, 'expected': expected}
    (destination / 'expectations.json').write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'source_unchanged': True, 'routes': len(expected), 'source_fact_checks': source_fact_checks}))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database', type=Path, required=True)
    p.add_argument('--attempt', required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    args = p.parse_args()
    export(args.database, args.attempt, args.output_dir)

"""T50: complete rendered-script baselines from main 36b645e (v4.1.0)."""
from hashlib import sha256
import subprocess

import pytest
from ag import render


def rendered_script(program, scheduler, environment=None):
    # Synthetic fixed paths make the complete script bytes reproducible.
    cfg = {
        'remote': {'ag_root': '/fixture/ag'},
        'scheduler': {'queue': 'batch'} if scheduler == 'pbs' else 'slurm',
        'programs': {'gaussian': {'g16root': '/fixture/g16'},
                     'xtb': {'root': '/fixture/xtb'}},
    }
    if environment:
        cfg['programs']['gaussian']['environment'] = environment
    manifest = {
        'study_id': 'water', 'attempt_id': 'water-001-smoke',
        'remote_dir': 'water/water-001-smoke', 'pbs_job_name': 'water-001-smoke',
        'template': program, 'scheduler': scheduler,
        'template_params': {} if program == 'gaussian' else {
            '--chrg': '1', '--alpb': 'ch2cl2'},
        'cores': 8, 'mem_gb': 12, 'walltime': '01:00:00',
    }
    return render.render(cfg, manifest, 'water.gjf' if program == 'gaussian' else 'water.xyz')


@pytest.mark.parametrize('program,scheduler,environment,baseline_sha256', [
    ('xtb', 'pbs', None, '978711c4063244f10bfa0fe69e527a57bbfddc1875201346a85649c78b81e4cd'),
    ('xtb', 'slurm', None, 'a332b66521e01bb34968c2b503f5ffbaad05d93bc0dfaa042ca57fcf3c849a18'),
    ('crest', 'pbs', None, '74f2bd7f2d4b0ff1ea930841b544fe5c47fa2a04e7ebd5705ca71faf9dc74635'),
    ('crest', 'slurm', None, 'ea8ade105d4cde7e0be9c8a31c12764bf2c77e0726a1e5a980cd1f2d239cb5b9'),
    ('gaussian', 'pbs', None, 'ecb7802a4e5995e21d393cd19da6a255c264bf4cf52d9a7311709f178558d362'),
    ('gaussian', 'slurm', None, '66351a9d94c6d73a2e7f2c6f10bf4ed84a0396cc56152956dded3aeb02e6f037'),
    ('gaussian', 'slurm', 'scnet-a03', 'd4700b33391ee4434a2514db507c78d352652d24549c669a20c72dc3b58a5739'),
])
def test_thread_environment_preserves_rendered_script(program, scheduler, environment, baseline_sha256):
    script = rendered_script(program, scheduler, environment)
    additions = 'export OPENBLAS_NUM_THREADS=1\nexport OMP_MAX_ACTIVE_LEVELS=1\n'
    if program in ('xtb', 'crest'):
        assert script.count(additions) == 1
        assert 'export OMP_NUM_THREADS=8\n' + additions + 'ag_run ' + program in script
        assert 'MKL_NUM_THREADS' not in script
        baseline = script.replace(additions, '')
    else:
        assert 'OPENBLAS_NUM_THREADS' not in script
        assert 'OMP_MAX_ACTIVE_LEVELS' not in script
        baseline = script
    # A digest covers every byte, including the guard, receipts and headers.
    assert sha256(baseline.encode()).hexdigest() == baseline_sha256
    assert subprocess.run(['sh', '-n'], input=script, text=True, capture_output=True).returncode == 0

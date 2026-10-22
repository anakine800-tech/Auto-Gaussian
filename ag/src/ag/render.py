"""Render only repository-reviewed templates and declared parameter values."""
from pathlib import Path
from string import Template
import math
import re
import shlex
import tomllib

TEMPLATES = Path(__file__).resolve().parents[2] / 'templates'


def declaration(name):
    if name not in ('gaussian', 'gaussian-cp', 'xtb', 'crest', 'multiwfn'):
        raise ValueError('Unknown program template')
    with (TEMPLATES / f'{name}.toml').open('rb') as handle:
        return tomllib.load(handle)


def parameters(name, values):
    allowed = declaration(name)['parameters']
    result = []
    for key, value in values.items():
        if key not in allowed:
            raise ValueError(f'Unsupported template parameter: {key}')
        spec = allowed[key]
        if isinstance(spec, list):
            valid = value in spec
        elif spec == 'flag':
            valid = value == ''
        elif spec in ('integer', 'nonnegative_integer'):
            valid = bool(re.fullmatch(r'-?\d+', value))
            if valid and spec == 'nonnegative_integer':
                valid = int(value) >= 0
        else:
            try:
                valid = math.isfinite(float(value)) and float(value) > 0
            except ValueError:
                valid = False
        if not valid:
            raise ValueError(f'Unsupported value for {key}')
        result.append(key)
        if value:
            result.append(value)
    if len({'--gfn2', '--gfnff'} & values.keys()) > 1 or len({'--quick', '--squick', '--mquick'} & values.keys()) > 1:
        raise ValueError('Conflicting template parameters')
    return ' '.join(shlex.quote(value) for value in result)


def render(cfg, manifest, input_name):
    from ag.remote import path_checks, attempt_dir
    from ag.config import for_manifest
    cfg = for_manifest(cfg, manifest)
    m = manifest
    if not re.fullmatch(r'\d{2,4}:[0-5]\d:[0-5]\d', m['walltime']) or not int(m['walltime'].replace(':', '')):
        raise ValueError('walltime must be positive HH:MM:SS')
    p = parameters(m['template'], m['template_params'])
    # CREST consumes the token immediately after --mdopt as its ensemble file.
    # Keep the public parameter a flag and bind it only to the validated input.
    mdopt = m['template'] == 'crest' and '--mdopt' in m['template_params']
    if mdopt:
        p = parameters('crest', {k: v for k, v in m['template_params'].items() if k != '--mdopt'})
    if m['template'] == 'multiwfn' and (m.get('cluster') != 'default' or m.get('scheduler') != 'pbs'):
        raise ValueError('Multiwfn is supported only on default PBS')
    work = attempt_dir(cfg, m)
    values = {key: shlex.quote(str(value)) for key, value in dict(
        allowed_root=cfg['remote']['ag_root'], work_dir=work,
        g16root=cfg['programs']['gaussian']['g16root'],
        xtb_bin=cfg['programs']['xtb']['root'] + '/bin',
        xtb_share=cfg['programs']['xtb']['root'] + '/share/xtb',
        cores=m['cores'], input_name=input_name,
        log_name=Path(input_name).stem + '.log').items()}
    if mdopt:
        values['input_name'] = '--mdopt ' + shlex.quote(input_name)
    values.update(parameters=p, path_checks=path_checks(work))
    header = (f"#!/bin/sh\n#PBS -N {m['pbs_job_name']}\n#PBS -q {(cfg['scheduler']['queue'] if isinstance(cfg['scheduler'], dict) else '')}\n"
              f"#PBS -l nodes=1:ppn={m['cores']}\n#PBS -l mem={m['mem_gb']}gb\n"
              f"#PBS -l walltime={m['walltime']}\n#PBS -j oe\n#PBS -r n\n#PBS -o {work}/job.pbs.out\n")
    if m.get('scheduler') == 'slurm':
        header = (f"#!/bin/sh\n#SBATCH --job-name={m['attempt_id']}\n"
                  f"#SBATCH --nodes=1\n#SBATCH --ntasks=1\n#SBATCH --cpus-per-task={m['cores']}\n"
                  f"#SBATCH --mem={m['mem_gb']}G\n#SBATCH --time={m['walltime']}\n"
                  f"#SBATCH --output={work}/job.slurm.out\n#SBATCH --error={work}/job.slurm.err\n"
                  "#SBATCH --no-requeue\n")
        from ag.remote import slurm_token
        for key in ('partition', 'account', 'qos'):
            if key in cfg:
                header += f"#SBATCH --{key}={slurm_token(cfg[key])}\n"
    program_template = 'gaussian.pbs' if m['template'] == 'gaussian-cp' else f"{m['template']}.pbs"
    if (m.get('scheduler') == 'slurm' and m['template'] in ('gaussian', 'gaussian-cp')
            and cfg['programs']['gaussian'].get('environment') == 'scnet-a03'):
        program_template = 'gaussian-scnet-a03.sh'
        values['gaussian_parent'] = shlex.quote(str(Path(cfg['programs']['gaussian']['g16root']).parent))
    if m['template'] == 'multiwfn':
        from ag.config import multiwfn_executable
        from ag.nci_report import pipeline
        executable = multiwfn_executable(cfg['programs'])
        values['multiwfn_bin'] = ('"$HOME/' + executable[2:] + '"' if executable.startswith('~/')
                                  else '"' + executable + '"')
        values['multiwfn_pipeline'] = pipeline(m)
    body = (TEMPLATES / '_guard.sh').read_text() + (TEMPLATES / program_template).read_text()
    # Substitute only the scheduler-specific inputs; PBS scripts retain their
    # original bytes so prepared PBS bundles remain verifiable after upgrade.
    values.update(workdir_variable='PBS_O_WORKDIR', jobid_variable='PBS_JOBID', receipt_job_key='PBS_JOBID')
    if m.get('scheduler') == 'slurm':
        values.update(workdir_variable='SLURM_SUBMIT_DIR', jobid_variable='SLURM_JOB_ID', receipt_job_key='job_id')
        if m['template'] in ('gaussian', 'gaussian-cp'):
            env = cfg['programs']['gaussian']
            setup = ''
            if env.get('module_init'):
                setup += '. ' + shlex.quote(env['module_init']) + '\n'
            for module in env.get('modules', []):
                if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./+-]*', module) or '..' in module:
                    raise ValueError('Invalid module name')
                setup += 'module load ' + shlex.quote(module) + '\n'
            body = body.replace('export g16root=', setup + 'export g16root=')
    return header + Template(body).substitute(values)

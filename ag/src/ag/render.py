"""Render only repository-reviewed templates and declared parameter values."""
from pathlib import Path
from string import Template
import math
import re
import shlex
import tomllib

TEMPLATES = Path(__file__).resolve().parents[2] / 'templates'


def declaration(name):
    if name not in ('gaussian', 'xtb', 'crest'):
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
    m = manifest
    if not re.fullmatch(r'\d{2,4}:[0-5]\d:[0-5]\d', m['walltime']) or not int(m['walltime'].replace(':', '')):
        raise ValueError('walltime must be positive HH:MM:SS')
    p = parameters(m['template'], m['template_params'])
    work = attempt_dir(cfg, m)
    values = {key: shlex.quote(str(value)) for key, value in dict(
        allowed_root=cfg['remote']['ag_root'], work_dir=work,
        g16root=cfg['programs']['gaussian']['g16root'],
        xtb_bin=cfg['programs']['xtb']['root'] + '/bin',
        xtb_share=cfg['programs']['xtb']['root'] + '/share/xtb',
        cores=m['cores'], input_name=input_name,
        log_name=Path(input_name).stem + '.log').items()}
    values.update(parameters=p, path_checks=path_checks(work))
    header = (f"#!/bin/sh\n#PBS -N {m['pbs_job_name']}\n#PBS -q {cfg['scheduler']['queue']}\n"
              f"#PBS -l nodes=1:ppn={m['cores']}\n#PBS -l mem={m['mem_gb']}gb\n"
              f"#PBS -l walltime={m['walltime']}\n#PBS -j oe\n#PBS -r n\n#PBS -o {work}/job.pbs.out\n")
    body = (TEMPLATES / '_guard.sh').read_text() + (TEMPLATES / f"{m['template']}.pbs").read_text()
    return header + Template(body).substitute(values)

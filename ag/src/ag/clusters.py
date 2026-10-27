"""Local, allowlisted cluster metadata for frontend discovery."""
from pathlib import Path

from ag import budget
from ag.config import scheduler_kind, select_cluster, optional_resource_caps, RESOURCE_TIERS


def describe(cfg, *, verify_studies_root=None):
    rows = []
    for name in sorted(cfg.get('clusters', {'default': cfg})):
        selected = select_cluster(cfg, name)
        resources = selected['resources']
        programs = selected.get('programs', {})
        xtb = bool(programs.get('xtb', {}).get('root'))
        # Construct each level explicitly: config tables may contain private
        # connection details or unused metadata, including within a tier.
        row = dict(
            name=name, scheduler=scheduler_kind(selected), is_default=name == 'default',
            resources=dict(
                max_cores=resources['max_cores'],
                max_committed_cores=resources['max_committed_cores'],
                **optional_resource_caps(selected),
                tiers={tier: {key: resources['tiers'][tier][key] for key in ('cores', 'mem_gb')}
                       for tier in RESOURCE_TIERS if tier in resources['tiers']}),
            expires=selected.get('expires'),
            programs_enabled=dict(gaussian=bool(programs.get('gaussian', {}).get('g16root')),
                                  xtb=xtb, crest=bool(programs.get('crest', {}).get('executable')) or xtb))
        if 'node_targeting' in selected:
            row['node_targeting'] = dict(default_fraction='1/2', fractions=['1/2', '1/4'])
        if 'max_walltime' in resources:
            row['resources']['max_walltime'] = resources['max_walltime']
        summary = budget.public_summary(selected)
        if 'display_name' in selected:
            row['display_name'] = selected['display_name']
        if summary is not None:
            row['budget'] = summary
        rows.append(row)
    result = dict(clusters=rows)
    if verify_studies_root is not None:
        try:
            result['studies_root_matches'] = (
                Path(verify_studies_root).resolve() == Path(cfg['local']['studies_root']).resolve())
        except RuntimeError as exc:
            # Python 3.11 reports symlink loops with a path-bearing RuntimeError.
            raise ValueError('Cannot resolve studies root') from exc
    return result

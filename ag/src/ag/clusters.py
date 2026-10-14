"""Local, allowlisted cluster metadata for frontend discovery."""
from pathlib import Path

from ag import budget
from ag.config import scheduler_kind, select_cluster


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
                tiers={tier: {key: resources['tiers'][tier][key] for key in ('cores', 'mem_gb')}
                       for tier in ('mini', 'simple', 'general', 'complex')}),
            expires=selected.get('expires'),
            programs_enabled=dict(gaussian=bool(programs.get('gaussian', {}).get('g16root')),
                                  xtb=xtb, crest=xtb))
        summary = budget.public_summary(selected)
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

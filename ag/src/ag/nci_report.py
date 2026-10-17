"""Fixed Multiwfn input preparation and local, provenance-bound NCI reports.

Multiwfn 2026.10.1 manual §§2.2, 3.23.5–6, 4.20.10–11; exact atmdg
format checked against that release's visweak.f90 (IGM), not invented CSV.
"""
from collections import Counter
import csv
from hashlib import sha256
from io import StringIO
from itertools import combinations
import json
import math
from pathlib import Path
import re
from string import Template

from ag import attempt, crest_input, gaussian_input, render, study

VERSION = '2026.10.1'
NOTICE = '结果仅为相互作用的可视化与半定量分析，不是能量分解'
GRID_POINTS = dict(low=125000, medium=512000, high=1728000)
NUMBER = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdD][-+]?\d+)?'


def _json(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


def fragments_csv(raw, symbols):
    reader = csv.DictReader(StringIO(raw.decode('utf-8-sig')))
    if reader.fieldnames != ['fragment', 'atoms']:
        raise ValueError('Fragments CSV requires exactly fragment,atoms columns')
    result, used, labels = [], set(), set()
    for row in reader:
        if set(row) != {'fragment', 'atoms'} or any(v is None for v in row.values()):
            raise ValueError('Invalid fragments CSV row; quote comma-separated atom ranges')
        label = row['fragment'].strip()
        if not label or not label.isprintable() or label in labels:
            raise ValueError('Fragment names must be nonempty, printable and unique')
        atoms = []
        for token in row['atoms'].split(','):
            match = re.fullmatch(r'\s*([1-9]\d*)(?:-([1-9]\d*))?\s*', token)
            if not match:
                raise ValueError('Fragment atoms must use 1-40,52 syntax')
            start, end = int(match[1]), int(match[2] or match[1])
            if not 1 <= start <= end <= len(symbols):
                raise ValueError('Fragment atom index outside input atom count')
            atoms.extend(range(start, end + 1))
        if len(set(atoms)) != len(atoms) or used.intersection(atoms):
            raise ValueError('Fragment atoms overlap')
        used.update(atoms)
        labels.add(label)
        result.append(dict(fragment=label, atoms=sorted(atoms),
                           elements=dict(sorted(Counter(symbols[i-1] for i in atoms).items()))))
    if not 2 <= len(result) <= 4:
        raise ValueError('Expected 2–4 fragments')
    if used != set(range(1, len(symbols)+1)):
        raise ValueError('Fragments must cover all atoms')
    return result


def atom_ranges(atoms):
    ranges = []
    first = last = atoms[0]
    for atom in atoms[1:] + [None]:
        if atom == last + 1:
            last = atom
        else:
            ranges.append(str(first) if first == last else f'{first}-{last}')
            first = last = atom
    return ','.join(ranges)


def layout(m):
    """No remote enumeration or fallback frame count: the prepared manifest owns it."""
    science = m.get('science', {})
    count = science.get('n_frames')
    if type(count) is not int or not 1 <= count <= 50:
        raise ValueError('Multiwfn manifest n_frames must be an integer in 1–50')
    nci = science.get('nci', {})
    fragments = nci.get('fragments')
    if not isinstance(fragments, list) or not 2 <= len(fragments) <= 4:
        raise ValueError('Multiwfn manifest requires 2–4 fragments')
    if nci.get('analysis') not in ('igm', 'igmh') or nci.get('grid') not in GRID_POINTS:
        raise ValueError('Invalid Multiwfn analysis/grid in manifest')
    if nci['analysis'] == 'igmh' and count != 1:
        raise ValueError('IGMH requires exactly one parent checkpoint frame')
    return count, list(combinations(range(1, len(fragments)+1), 2))


def _parent_context(cfg, attachment):
    from ag.facts import parse_facts, gaussian_log
    from ag.fetch import incomplete_record
    path = attempt.find(cfg, attachment['attempt_id'])
    m = attempt.read_manifest(path)
    if incomplete_record(path) is not None:
        raise ValueError('IGMH requires a normally terminated Gaussian parent, not incomplete fetch')
    for output in (path / 'outputs').iterdir():
        if output.name != '.partial':
            study.local_path(path, output)
    log = _regular(study.local_path(path, gaussian_log(path)))
    log_hash = _digest(log)
    manifest_hash = _digest(path/'manifest.json')
    facts, geometries = parse_facts(path)
    if facts['termination'] != 'normal' or not geometries.get('final.xyz'):
        raise ValueError('IGMH requires a normally terminated Gaussian parent and final geometry; fetch first')
    symbols, rows = crest_input.xyz_ensemble(geometries['final.xyz'])[0]
    if len(symbols) != m['science']['n_atoms']:
        raise ValueError('Parent atom count differs from final geometry')
    expected = gaussian_input.cartesian(m['science']['geometry'].splitlines(), first_line=1)
    if symbols != expected:
        raise ValueError('Parent final atom order differs from its input')
    if log_hash != _digest(log) or manifest_hash != _digest(path/'manifest.json'):
        raise ValueError('Parent evidence changed while reading')
    return dict(attempt_id=path.name, manifest_sha256=manifest_hash,
                log_file=log.relative_to(path).as_posix(), log_sha256=log_hash,
                route=facts['route'], method_basis=m['science']['method_basis'],
                charge=facts['charge'], multiplicity=facts['multiplicity'],
                geometry='\n'.join(rows), symbols=symbols)


def _inputs(params, raw, fragment_data, *, cores):
    analysis, grid = params['--analysis'], params['--grid']
    files = {'fragments.csv': fragment_data, 'multiwfn-settings.ini': f'nthreads= {cores}\n'.encode()}
    parent = None
    if analysis == 'igm':
        frames = crest_input.xyz_ensemble(raw.decode())
        if len(frames) > 50:
            raise ValueError('IGM accepts at most 50 XYZ frames')
        for i, (symbols, rows) in enumerate(frames, 1):
            gaussian_input.cartesian(rows, first_line=1)
            files[f'input-{i:03d}.xyz'] = (str(len(symbols))+'\nag Multiwfn frame\n'+'\n'.join(rows)+'\n').encode()
        files['ensemble.xyz'] = raw
        symbols, rows = frames[0]
        charge = multiplicity = None  # A coordinate-only XYZ carries neither.
    else:
        parent = json.loads(raw)
        symbols, rows = parent['symbols'], parent['geometry'].splitlines()
        if gaussian_input.cartesian(rows, first_line=1) != symbols:
            raise ValueError('Invalid parent context atom order')
        frames = [(symbols, rows)]
        charge, multiplicity = parent['charge'], parent['multiplicity']
        files['parent-context.json'] = raw
    fragments = fragments_csv(fragment_data, symbols)
    ranges = [atom_ranges(f['atoms']) for f in fragments]
    # Multiwfn reads each atom selection into character*2000; avoid silent truncation.
    if any(len(value) > 2000 for value in ranges):
        raise ValueError('Fragment atom selection exceeds Multiwfn 2000-character input limit')
    for left, right in combinations(range(1, len(fragments)+1), 2):
        menu = (render.TEMPLATES/'multiwfn'/f'{analysis}-{grid}.inp').read_text()
        files[f'menu-{left:02d}-{right:02d}.inp'] = Template(menu).substitute(
            fragment_count=len(fragments), fragment_atoms='\n'.join(ranges),
            pair_selection=f'{left},{right}\n' if len(fragments)>2 else '').encode()
    nci = dict(analysis=analysis, grid=grid, fragments=fragments, symbols=symbols)
    if parent is not None:
        nci['parent'] = parent
    science = dict(n_atoms=len(symbols), n_frames=len(frames), geometry='\n'.join(rows),
                   charge=charge, multiplicity=multiplicity,
                   route=f'Multiwfn {VERSION} {analysis} grid={grid}', nci=nci,
                   stereochemistry_warning='保留输入原子顺序；需人审核各帧立体化学和片段。XYZ 不提供电荷/多重度。')
    return science, files


def prepare_inputs(cfg, params, input_path, fragments, attachment, *, cores):
    from ag.config import multiwfn_executable, scheduler_kind
    if cfg.get('_cluster') != 'default' or scheduler_kind(cfg) != 'pbs':
        raise ValueError('Multiwfn is supported only on default PBS')
    multiwfn_executable(cfg['programs'])
    if fragments is None:
        raise ValueError('--fragments is required')
    if params['--analysis'] == 'igmh':
        if attachment is None or input_path is not None:
            raise ValueError('IGMH requires --parent-chk and no --input; geometry comes from the checkpoint')
        raw = _json(_parent_context(cfg, attachment))
    else:
        if attachment is not None or input_path is None or Path(input_path).suffix.lower() != '.xyz':
            raise ValueError('IGM requires an XYZ input and no parent checkpoint')
        raw = Path(input_path).read_bytes()
    return _inputs(params, raw, Path(fragments).read_bytes(), cores=cores)


def verify_prepared(cfg, m, files):
    name = 'ensemble.xyz' if m['template_params']['--analysis'] == 'igm' else 'parent-context.json'
    science, expected = _inputs(m['template_params'], files[name], files['fragments.csv'], cores=m['cores'])
    if any(m['science'].get(k) != v for k, v in science.items()):
        raise ValueError('Multiwfn scientific summary differs from input bundle')
    if {k: v for k,v in files.items() if k != 'job.pbs'} != expected:
        raise ValueError('Multiwfn inputs differ from fixed reviewed menus/data')
    if name == 'parent-context.json' and _json(_parent_context(cfg, m['parent_chk'])) != files[name]:
        raise ValueError('IGMH parent evidence changed since prepare')
    return name


def pipeline(m):
    frames, pairs = layout(m)
    igmh = m['science']['nci']['analysis'] == 'igmh'
    lines = []
    if igmh:
        lines += ['    test ! -L parent.chk && test -s parent.chk || return 44',
                  '    test ! -e parent.fchk && test ! -L parent.fchk || return 44',
                  '    formchk parent.chk parent.fchk || return',
                  '    test ! -L parent.fchk && test -s parent.fchk || return 44',
                  '    sha256sum -- parent.chk parent.fchk || return']
    for frame in range(1, frames+1):
        source = 'parent.fchk' if igmh else f'input-{frame:03d}.xyz'
        for index,(left,right) in enumerate(pairs):
            prefix = f'frame-{frame:03d}-pair-{left:02d}-{right:02d}'
            # mkdir refuses every existing path; each native filename is created
            # once in that private directory. ln publishes without overwriting.
            lines += [f'    mkdir -- {prefix} || return',
                      f'    ( cd -- {prefix} || exit',
                      f'      ag_nci_pair "../{source}" "../menu-{left:02d}-{right:02d}.inp"',
                      f'    ) > {prefix}.out 2>&1 || return',
                      f'    cat -- {prefix}.out || return',
                      f'    ln -- {prefix}/atmdg.txt {prefix}-atmdg.txt || return',
                      f'    ln -- {prefix}/IBSIW.txt {prefix}-IBSIW.txt || return']
            if index == 0:
                for cube in ('dg_inter.cub','sl2r.cub'):
                    lines.append(f'    ln -- {prefix}/{cube} frame-{frame:03d}-{cube} || return')
    return '\n'.join(lines)


def summary(m):
    nci = m['science']['nci']
    frames,pairs = layout(m)
    # Cube format is six E14.5E3 numbers/line. Estimates are not a cap.
    per_frame = GRID_POINTS[nci['grid']] * 2 * 14
    lines = [f"Multiwfn {VERSION}: {nci['analysis']} | grid={nci['grid']} | frames={frames}",
             'Fragments (CSV row order; numbering starts at 1):']
    for i,f in enumerate(nci['fragments'],1):
        elements=' '.join(f'{s}:{n}' for s,n in f['elements'].items())
        lines.append(f"- {i} {f['fragment']}: atoms {atom_ranges(f['atoms'])}; {elements}")
    if 'parent' in nci:
        p=nci['parent']
        lines.append(f"Parent method: {p['attempt_id']} | {p['route']} | {p['method_basis']}")
        lines.append('Geometry is read from parent.chk; preview above is the normal parent log geometry. '
                     'Use the geometry-level Opt wavefunction by default; a single-point parent is an explicit optional choice.')
    lines += [f"Estimated fetched cubes: {per_frame/1e6:.1f} MB/frame, {per_frame*frames/1e6:.1f} MB total "
              '(both dg_inter and sl2r, including high; geometry-dependent estimate, not a size limit).',
              f'{len(pairs)} fragment-pair runs/frame; extra native cubes remain remote; fchk is never fetched.', NOTICE]
    return '\n'.join(lines)


def _number(text):
    if not re.fullmatch(NUMBER,text):
        raise ValueError('Invalid Multiwfn numeric value')
    result=float(text.replace('D','E').replace('d','e'))
    if not math.isfinite(result):
        raise ValueError('Nonfinite Multiwfn value')
    return result


def parse_table(text, fragments, symbols, left, right):
    """Parse complete release-native atmdg.txt, including the final sum sentinel."""
    atoms,pairs,seen,section,total = [],[],set(),None,None
    headers=[]
    for line in text.splitlines():
        line=line.strip()
        if not line:
            continue
        match=re.fullmatch(r'Atomic delta-g indices of fragment\s+(\d+) and percentage contributions',line)
        if match:
            f=int(match[1]);headers.append(f)
            if headers != [left,right][:len(headers)] or total is not None:
                raise ValueError('Unexpected or duplicate atom section')
            section=f
            continue
        if line=='Atomic pair delta-g indices and percentage contributions (zero terms are not shown)':
            if headers != [left,right] or section=='pairs' or total is not None:
                raise ValueError('Unexpected pair section')
            section='pairs';continue
        match=re.fullmatch(r'Sum of all atomic pair delta-g indices:\s*('+NUMBER+')',line)
        if match:
            if section!='pairs' or total is not None:
                raise ValueError('Unexpected table total')
            total=_number(match[1]);continue
        match=re.fullmatch(r'(Atom\s+\d+|\d+\s+\d+)\s*:\s*('+NUMBER+r')\s*\(\s*('+NUMBER+r')\s*%\s*\)',line)
        if not match or total is not None:
            raise ValueError('Malformed or truncated Multiwfn atmdg table')
        value,percent=_number(match[2]),_number(match[3])
        if value<0 or not 0<=percent<=100.01:
            raise ValueError('Invalid contribution or percentage')
        fields=match[1].split()
        indices=list(map(int,fields[1:] if fields[0]=='Atom' else fields))
        if fields[0]=='Atom':
            if section not in (left,right) or indices[0] not in fragments[section-1]['atoms']:
                raise ValueError('Atom belongs to the wrong fragment')
            key=('atom',indices[0])
            item=dict(atom=indices[0],element=symbols[indices[0]-1],fragment=fragments[section-1]['fragment'],
                      delta_g=value,percent=percent)
            atoms.append(item)
        else:
            if section!='pairs' or indices[0] not in fragments[left-1]['atoms'] or indices[1] not in fragments[right-1]['atoms']:
                raise ValueError('Atomic pair belongs to the wrong fragments')
            key=tuple(indices)
            item=dict(atoms=indices,elements=[symbols[i-1] for i in indices],
                      fragments=[fragments[i-1]['fragment'] for i in (left,right)],delta_g=value,percent=percent)
            pairs.append(item)
        if key in seen:
            raise ValueError('Duplicate contribution row')
        seen.add(key)
    expected=set(fragments[left-1]['atoms']+fragments[right-1]['atoms'])
    if total is None or total<=0 or {a['atom'] for a in atoms}!=expected:
        raise ValueError('Missing atoms or final positive total in atmdg table')
    # Native f12.6 printing rounds each value, so tolerances scale with row count.
    tolerance=(len(pairs)+len(atoms)+1)*0.00000051
    if abs(sum(p['delta_g'] for p in pairs)-total)>tolerance:
        raise ValueError('Atomic pair sum differs from reported total')
    for atom in atoms:
        subtotal=sum(p['delta_g'] for p in pairs if atom['atom'] in p['atoms'])
        if abs(atom['percent'] - 100 * atom['delta_g'] / total) > 0.011 + 100*tolerance/total:
            raise ValueError('Atom percentage differs from contribution')
        if abs(atom['delta_g']-subtotal)>tolerance:
            raise ValueError('Atom sum differs from pair contributions')
    for pair in pairs:
        if abs(pair['percent'] - 100 * pair['delta_g'] / total) > 0.011 + 100*tolerance/total:
            raise ValueError('Pair percentage differs from contribution')
    return dict(fragment_indices=[left,right],fragments=[fragments[i-1]['fragment'] for i in (left,right)],
                atoms=atoms,atom_pairs=pairs,total_delta_g=total)


def _regular(path):
    path=study.local_path(Path(path).anchor,path)
    if not path.is_file():
        raise ValueError(f'Missing regular file: {path.name}')
    return path


def _digest(path):
    with _regular(path).open('rb') as handle:
        import hashlib
        return hashlib.file_digest(handle,'sha256').hexdigest()


def _cube(path,symbols):
    with _regular(path).open() as stream:
        if not stream.readline() or not stream.readline():
            raise ValueError('Incomplete cube header')
        row=stream.readline().split()
        if len(row)!=4 or int(row[0])!=len(symbols):
            raise ValueError('Cube atom count differs from input')
        origin=[_number(x) for x in row[1:]]
        dims=[]
        axes=[]
        for _ in range(3):
            row=stream.readline().split()
            if len(row)!=4 or int(row[0])<1:
                raise ValueError('Invalid cube grid')
            dims.append(int(row[0]));axes.append([_number(x) for x in row[1:]])
        coordinates=[]
        for symbol in symbols:
            row=stream.readline().split()
            if len(row)!=5 or int(row[0])!=gaussian_input.ATOMIC_NUMBERS[symbol]:
                raise ValueError('Cube elements differ from input')
            coordinates.append([_number(x) for x in row[1:]])
        count=0
        for row in stream:
            for value in row.split():
                _number(value);count+=1
        if count!=math.prod(dims):
            raise ValueError('Incomplete or extra cube grid values')
    return dict(dimensions=dims,origin_bohr=origin,axes_bohr=axes,atoms=coordinates)


def report(path):
    path=study.local_path(Path(path).anchor,Path(path).absolute())
    manifest_hash=_digest(path/'manifest.json')
    m=attempt.read_manifest(path)
    if m['template']!='multiwfn':
        raise ValueError('nci-report requires a Multiwfn Attempt')
    from ag import remote, state
    current = state.read(path)
    if current['state']!='fetched' or current.get('exit_status') not in (None, 0) or list(path.glob('fetch-incomplete-*.json')):
        raise ValueError('nci-report requires a complete fetched Attempt')
    frame_count,fragment_pairs=layout(m)
    nci=m['science']['nci']
    files={r['name']:_regular(path/'inputs'/r['name']).read_bytes() for r in m['inputs']}
    records,digest=attempt.bundle(files)
    if records!=m['inputs'] or digest!=m['bundle_sha256']:
        raise ValueError('Input bundle hash mismatch')
    raw_name='ensemble.xyz' if nci['analysis']=='igm' else 'parent-context.json'
    science,expected=_inputs(m['template_params'],files[raw_name],files['fragments.csv'],cores=m['cores'])
    if any(m['science'].get(k)!=v for k,v in science.items()) or any(files.get(k)!=v for k,v in expected.items()):
        raise ValueError('Input metadata or fixed menu mismatch')
    names=remote.output_names(m)
    hashes={name:_digest(path/'outputs'/name) for name in names}
    log=(path/'outputs/multiwfn.out').read_text()
    if not log.rstrip().endswith('AG_NCI_COMPLETE'):
        raise ValueError('Multiwfn has no normal completion marker; refuse partial results')
    results=[]
    for frame in range(1,frame_count+1):
        tables=[]
        for left,right in fragment_pairs:
            prefix=f'frame-{frame:03d}-pair-{left:02d}-{right:02d}'
            text=(path/'outputs'/f'{prefix}.out').read_text()
            clean=re.sub(r'\x1b\[[0-9;]*m','',text)
            versions=re.findall(r'^\s*Version (\S+) \(release date is the same as version name\)\s*$',clean,re.M)
            threads=re.findall(r'Number of parallel threads:\s*(\d+)',clean)
            if versions!=[VERSION] or threads!=[str(m['cores'])] or not clean.rstrip().endswith('AG_NCI_NORMAL_EXIT'):
                raise ValueError('Multiwfn version/threads/normal exit mismatch')
            if re.search(r'(?im)^\s*(?:Error:|forrtl:|STOP\s+\d)',clean):
                raise ValueError('Multiwfn reported an error')
            table=parse_table((path/'outputs'/f'{prefix}-atmdg.txt').read_text(),nci['fragments'],nci['symbols'],left,right)
            tables.append(table)
        cubes=[_cube(path/'outputs'/f'frame-{frame:03d}-{name}',nci['symbols']) for name in ('dg_inter.cub','sl2r.cub')]
        if cubes[0]!=cubes[1]:
            raise ValueError('Cube grids or atom coordinates differ')
        if nci['analysis'] == 'igm':
            _, rows = crest_input.xyz_ensemble(files[f'input-{frame:03d}.xyz'].decode())[0]
            coordinates = [[float(v)/0.529177210903 for v in row.split()[1:]] for row in rows]
            if any(abs(a-b) > 0.00001 for actual, wanted in zip(cubes[0]['atoms'], coordinates)
                   for a,b in zip(actual[1:], wanted)):
                raise ValueError('Cube coordinates differ from this IGM input frame')
        totals=[dict(fragment=f['fragment'],delta_g=sum(t['total_delta_g'] for t in tables if f['fragment'] in t['fragments']))
                for f in nci['fragments']]
        results.append(dict(frame=frame,fragment_pairs=tables,fragment_totals=totals,cube_grid=cubes[0]))
    remote_inputs={}
    if nci['analysis']=='igmh':
        for name in ('parent.chk','parent.fchk'):
            matches=re.findall(r'^([0-9a-f]{64})  '+re.escape(name)+r'$',log,re.M)
            if len(matches)!=1:
                raise ValueError('Missing checkpoint/fchk input hash')
            remote_inputs[name]=dict(sha256=matches[0],source='multiwfn.out',fetched=False)
        journal_path = _regular(path.parent.parent/'journal.jsonl')
        copied = [json.loads(row) for row in journal_path.read_text().splitlines() if row.strip()]
        copied = [row for row in copied if row.get('action') == 'copy_parent_chk'
                  and row.get('attempt_id') == path.name and row.get('result') == 'verified']
        if len(copied) != 1 or copied[0]['detail'].get('sha256') != remote_inputs['parent.chk']['sha256']:
            raise ValueError('Checkpoint hash differs from verified parent copy')
    if manifest_hash != _digest(path/'manifest.json') or any(
            _digest(path/'inputs'/r['name']) != r['sha256'] for r in records):
        raise ValueError('Input evidence changed while creating nci-report')
    if hashes!={name:_digest(path/'outputs'/name) for name in names}:
        raise ValueError('Output changed while creating nci-report')
    return dict(schema='ag-nci/1',attempt_id=path.name,multiwfn_version=VERSION,analysis=nci['analysis'],grid=nci['grid'],
                fragments=nci['fragments'],frames=results,notice=NOTICE,units=dict(delta_g='atomic units',percent='%'),
                summary_note='Pair indices are not an additive decomposition of the multi-fragment cube integral. '
                             'Each fragment total includes its incident pairs; summing fragment totals counts pairs twice.',
                provenance=dict(manifest_sha256=manifest_hash,inputs=records,
                                outputs=[dict(name=n,sha256=h) for n,h in hashes.items()],remote_inputs=remote_inputs),
                parent=nci.get('parent'))


def run(args):
    given=Path(args.attempt).expanduser()
    if (given/'manifest.json').is_file():
        path=study.local_path(given.absolute().anchor,given.absolute())
    elif args.study:
        path=study.local_path(Path(args.study).absolute(),Path(args.study).absolute()/'attempts'/study.identifier(args.attempt))
    else:
        from ag.config import load_config
        path=attempt.find(load_config(local_only=True),args.attempt)
    root=path.parent.parent
    out=args.out.expanduser()
    if not out.is_absolute():
        out=root/out
    out=study.local_path(root/'analyses',out)
    if out.suffix.lower()!='.json':
        raise ValueError('--out must be a new .json under study analyses/')
    result=report(path)
    from ag.fragments import _write_outputs
    _write_outputs(out.parent,{out.name:_json(result)})
    print(_json(result).decode() if args.json else f'{out.name}: {len(result["frames"])} frames. {NOTICE}')
    return 0


def register(subparsers):
    parser=subparsers.add_parser('nci-report',help='Parse fetched Multiwfn atomic contributions locally')
    parser.add_argument('attempt')
    parser.add_argument('--study',help='Local study directory')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--json',action='store_true')
    parser.set_defaults(func=run)

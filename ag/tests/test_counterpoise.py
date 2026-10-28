"""Counterpoise validation: synthetic cases and sanitized real small-molecule excerpts."""
from hashlib import sha256

import pytest
from ag.gaussian_input import counterpoise_fragments
from ag.nci_report import fragments_csv

WATER = ('O 0 0 0\nH 0.9572 0 0\nH -0.239987 0.927297 0\n'
         'O 2.9 0 0\nH 3.485882 0.75695 0\nH 3.485882 -0.75695 0')
HEADER = 'fragment,atoms,charge,multiplicity\n'
CSV = HEADER + 'water-a,1-3,0,1\nwater-b,4-6,0,1\n'


def validate(csv=CSV, geometry=WATER, charge=0, multiplicity=1):
    return counterpoise_fragments(csv.encode(), geometry=geometry, charge=charge, multiplicity=multiplicity)


def test_water_fragment_definition_and_hash():
    result = validate()
    assert result['sha256'] == sha256(CSV.encode()).hexdigest()
    assert result['fragments'] == [
        dict(index=1, fragment='water-a', atoms=[1, 2, 3], n_atoms=3, formula='H2O', charge=0, multiplicity=1),
        dict(index=2, fragment='water-b', atoms=[4, 5, 6], n_atoms=3, formula='H2O', charge=0, multiplicity=1),
    ]
    assert validate(HEADER+'water-a,"3,1-2",0,1\nwater-b,4-6,0,1\n')['fragments'] == result['fragments']
    assert validate('\ufeff'+CSV)['fragments'] == result['fragments']


def test_ammonium_water_fragment_charges():
    geometry = ('N 0 0 0\nH .59 .59 .59\nH .59 -.59 -.59\n'
                'H -.59 .59 -.59\nH -.59 -.59 .59\n'
                'O 3.2 0 0\nH 3.785882 .75695 0\nH 3.785882 -.75695 0')
    result = validate(HEADER+'ammonium,1-5,1,1\nwater,6-8,0,1\n', geometry, charge=1)
    assert [f['formula'] for f in result['fragments']] == ['H4N', 'H2O']
    assert [f['charge'] for f in result['fragments']] == [1, 0]


@pytest.mark.parametrize('csv,error', [
    (HEADER+'a,1-2,0,1\nb,4-6,0,1\n', 'without a fragment: 3'),
    (HEADER+'a,1-3,0,1\nb,3-6,0,1\n', 'atom 3 already belongs to fragment 1'),
    (HEADER+'a,"1-3,2",0,1\nb,4-6,0,1\n', 'atom 2 already belongs to fragment 1'),
    (HEADER+'a,1-3,0,1\nb,4-7,0,1\n', 'Fragment 2.*4-7'),
    (HEADER+'a,3-1,0,1\nb,4-6,0,1\n', 'Fragment 1.*3-1'),
    (HEADER+'a,0-3,0,1\nb,4-6,0,1\n', 'Fragment 1.*invalid atom'),
    (HEADER+'a,1-3,1,1\nb,4-6,0,1\n', 'charges do not sum.*fragment 1'),
    (HEADER+'a,1-3,0,3\nb,4-6,0,1\n', 'Fragment 1.*multiplicity must be 1'),
    (HEADER+'a,1-3,0,1\nb,4-6,0,0\n', 'Fragment 2.*multiplicity must be 1'),
    (HEADER+'a,1-3,0.0,1\nb,4-6,0,1\n', 'Fragment 1.*charge must be an integer'),
    (HEADER+'a,1-3,0,1\na,4-6,0,1\n', 'Fragment 2.*unique'),
    (HEADER+'a,1-3,0,1\nb,4,5-6,0,1\n', 'Fragment 2.*quote'),
    (HEADER+'a,1-3,0,1\nb,4-6,0\n', 'Fragment 2.*invalid CSV'),
    ('fragment,atoms\na,1-3\nb,4-6\n', 'exactly fragment,atoms,charge,multiplicity'),
    (HEADER+'a,1-6,0,1\n', 'exactly 2 fragments; got 1'),
    (HEADER+'a,1-2,0,1\nb,3-4,0,1\nc,5-6,0,1\n', 'exactly 2 fragments; got 3'),
])
def test_fragment_errors_identify_the_atom_or_fragment(csv, error):
    with pytest.raises(ValueError, match=error):
        validate(csv)


def test_rejects_overall_open_shell_and_impossible_fragment_singlets():
    with pytest.raises(ValueError, match='overall.*multiplicity must be 1'):
        validate(multiplicity=3)
    with pytest.raises(ValueError, match='Fragment 1.*incompatible parity'):
        validate(HEADER+'a,1-3,1,1\nb,4-6,-1,1\n')


def test_rejects_covalent_ethanol_split_with_atom_pair():
    geometry = ('C -1.5 0 0\nC 0 0 0\nO 1.43 0 0\n'
                'H -1.86 1.02 0\nH -1.86 -.51 .883\nH -1.86 -.51 -.883\n'
                'H 0 .7 .84\nH 0 -.7 .84\nH 1.75 .89 0')
    # Explicit opposite charges make both test fragments even-electron singlets,
    # isolating the forbidden C-C split rather than the electron-parity check.
    csv = HEADER+'methyl,"1,4-6",1,1\nremainder,"2-3,7-9",-1,1\n'
    with pytest.raises(ValueError, match='atoms 1-2 cross fragments 1-2: bonded'):
        validate(csv, geometry)


def test_rejects_uncertain_interfragment_contact_with_atom_pair():
    geometry = WATER.replace('O 2.9', 'O 1.7').replace('H 3.485882', 'H 2.285882')
    with pytest.raises(ValueError, match='atoms 1-4 cross fragments 1-2: uncertain'):
        validate(geometry=geometry)


def test_multiwfn_two_column_csv_is_unchanged():
    records = fragments_csv(b'fragment,atoms\na,1-3\nb,4-6\n', ['O','H','H']*2)
    assert records == [dict(fragment='a',atoms=[1,2,3],elements={'H':2,'O':1}),
                       dict(fragment='b',atoms=[4,5,6],elements={'H':2,'O':1})]
    with pytest.raises(ValueError, match='exactly fragment,atoms columns'):
        fragments_csv(CSV.encode(), ['O','H','H']*2)


def test_solvent_geometry_pairing_accepts_only_rigid_matching_geometry():
    from ag.cp_report import paired_geometry
    rotated = '\n'.join(f'{parts[0]} {-float(parts[2])+2} {float(parts[1])-3} {float(parts[3])+4}'
                        for parts in (row.split() for row in WATER.splitlines()))
    assert paired_geometry(WATER, rotated)['rmsd_angstrom'] < 1e-12
    assert paired_geometry(WATER, WATER.replace('0.9572', '0.9573'))['rmsd_angstrom'] < 1e-3
    with pytest.raises(ValueError, match='RMSD.*exceeds 0.001'):
        paired_geometry(WATER, WATER.replace('0.9572', '1.1'))
    with pytest.raises(ValueError, match='element sequence differs'):
        paired_geometry(WATER, WATER.replace('O 0 0 0', 'N 0 0 0'))
    with pytest.raises(ValueError, match='element sequence differs'):
        paired_geometry(WATER, '\n'.join(WATER.splitlines()[1:]))


def test_solvent_geometry_pairing_refuses_mirror_reflection_and_same_element_swaps():
    from ag.cp_report import paired_geometry
    geometry = 'C 0 0 0\nF 1 1 1\nCl 1 -1 -1\nBr -1 1 -1\nH -1 -1 1'
    mirrored = '\n'.join(f'{parts[0]} {-float(parts[1])} {parts[2]} {parts[3]}'
                         for parts in (row.split() for row in geometry.splitlines()))
    with pytest.raises(ValueError, match='RMSD.*exceeds 0.001'):
        paired_geometry(geometry, mirrored)
    rows = WATER.splitlines()
    rows[1], rows[4] = rows[4], rows[1]
    with pytest.raises(ValueError, match='RMSD.*exceeds 0.001'):
        paired_geometry(WATER, '\n'.join(rows))


@pytest.mark.parametrize('geometry', ['', 'O nan 0 0', 'O 1e308 1e308 1e308\nH -1e308 -1e308 -1e308'])
def test_geometry_pairing_rejects_missing_or_nonnumeric_geometry(geometry):
    from ag.cp_report import paired_geometry
    with pytest.raises(ValueError):
        paired_geometry(geometry, geometry)

# T105 step 0: real water probe lines 89-90. Installation path removed entirely.
# Original log SHA-256: ff18259cdb5970fa1198aa804116be2978bbd7a4136bbfaaf39d946ecba4401d
SCRF_REFUSAL = (' No SCRF with counterpoise/fragments.\n'
                ' Error termination via Lnk1e in [redacted] at Thu Oct 22 02:35:24 2026.\n')

import json
from pathlib import Path
from ag import attempt, cli, config, facts, remote, render, study, submit
from ag import cp_report
from test_core import cfg, Fake, allow
from test_slurm import multi

ROUTE = '# M062X/6-31+G(d,p) SP Counterpoise=2'
NH4_WATER = ('N 0 0 0\nH .59 .59 .59\nH .59 -.59 -.59\n'
             'H -.59 .59 -.59\nH -.59 -.59 .59\n'
             'O 3.2 0 0\nH 3.785882 .75695 0\nH 3.785882 -.75695 0')
NH4_CSV = HEADER + 'ammonium,1-5,1,1\nwater,6-8,0,1\n'


def prepare_cp(cfg, tmp_path, route=ROUTE, geometry=WATER, charge=0, csv=CSV,
               resource_lines='%nprocshared=4\n%mem=8GB\n', **options):
    root = Path(cfg['local']['studies_root']) / 'cp-test'
    if not root.exists():
        study.init(cfg, root.name)
    source = tmp_path / 'water.gjf'
    source.write_text(f'{resource_lines}{route}\n\nSynthetic test\n\n{charge} 1\n{geometry}\n\n')
    fragments = tmp_path / 'fragments.csv'
    fragments.write_text(csv)
    args = dict(study_name=root.name, template='gaussian-cp', input_path=source, fragments=fragments,
                tier='mini', walltime='00:30:00', label='cp', method_basis='兜底方法：合成测试')
    m = attempt.prepare(cfg, **{**args, **options})
    return attempt.find(cfg, m['attempt_id']), m


@pytest.mark.parametrize('cluster', ['default', 'batch'])
@pytest.mark.parametrize('resource_lines', ['', '%mem=8GB\n'])
def test_cp_auto_cores_precede_existing_fragment_conversion(multi, tmp_path, cluster, resource_lines):
    p, m = prepare_cp(multi, tmp_path, resource_lines=resource_lines, cluster=cluster)
    original = (f'{resource_lines}{ROUTE}\n\nSynthetic test\n\n0 1\n{WATER}\n\n').encode()
    source = tmp_path / 'water.gjf'
    assert source.read_bytes() == original
    assert m['auto_nprocshared'] == 4
    assert ('auto_mem_gb' in m) is (not resource_lines)
    files = attempt.verified_files(multi, p, m)
    assert files['water.gjf'].startswith(b'%nprocshared=4\n%mem=8GB\n')
    assert files['water.gjf'].count(b'(Fragment=1)') == 3
    assert files['water.gjf'].count(b'(Fragment=2)') == 3
    assert b'\n0 1 0 1 0 1\n' in files['water.gjf']
    record = next(r for r in m['inputs'] if r['name'] == 'water.gjf')
    assert record == dict(name='water.gjf', size=len(files['water.gjf']),
                          sha256=sha256(files['water.gjf']).hexdigest())
    assert attempt.bundle(files)[1] == m['bundle_sha256']
    assert record['sha256'] in attempt.summary(multi, m)
    assert '%nprocshared 由 ag 自动填写：4' in attempt.summary(multi, m)


@pytest.mark.parametrize('geometry,charge,csv,state', [(WATER,0,CSV,'0 1 0 1 0 1'),
                                                      (NH4_WATER,1,NH4_CSV,'1 1 1 1 0 1')])
def test_prepare_labels_bundle_summary_and_original_script(cfg, tmp_path, geometry, charge, csv, state):
    p, m = prepare_cp(cfg, tmp_path, geometry=geometry, charge=charge, csv=csv)
    files = attempt.verified_files(cfg, p, m)
    text = files['water.gjf'].decode()
    assert '\n'+state+'\n' in text
    assert text.count('(Fragment=1)') == (3 if charge == 0 else 5)
    assert text.count('(Fragment=2)') == 3
    assert files['water.gjf.fragments.csv'] == csv.encode()
    assert attempt.bundle(files)[1] == m['bundle_sha256']
    assert remote.output_names(m) == ['water.log', 'job.pbs.out']
    assert files['job.pbs'] == render.render(cfg, {**m, 'template':'gaussian'}, 'water.gjf').encode()
    summary = attempt.summary(cfg, m)
    assert sha256(csv.encode()).hexdigest() in summary
    assert 'Fragment 2 (water' in summary and '3 atoms; H2O; charge / multiplicity: 0 / 1' in summary
    if charge:
        assert '5 atoms; H4N; charge / multiplicity: 1 / 1' in summary
    (p/'inputs/water.gjf.fragments.csv').write_bytes(csv.encode()+b'\n')
    with pytest.raises(ValueError, match='bundle differs'):
        attempt.verified_files(cfg,p,m)


@pytest.mark.parametrize('tail', ['SCRF=(SMD,Solvent=DiChloroEthane)', 'scrf=pcm', 'ScRf = Check', 'SCRF'])
def test_real_probe_refusal_is_fixed_at_prepare(cfg, tmp_path, tail):
    assert 'No SCRF with counterpoise/fragments.' in SCRF_REFUSAL
    assert ' in [redacted] at ' in SCRF_REFUSAL and 'Error termination' in SCRF_REFUSAL
    with pytest.raises(ValueError, match='G16 A.03 不支持 Counterpoise 与 SCRF 同用.*--solvent-sp'):
        prepare_cp(cfg, tmp_path, route=ROUTE+' '+tail)
    assert not list((Path(cfg['local']['studies_root'])/'cp-test/attempts').iterdir())
    log=tmp_path/'probe.log';log.write_text(SCRF_REFUSAL)
    parsed, geom, inp = facts.parse_counterpoise(log)
    assert parsed['termination']=='error' and parsed['counterpoise'] is None
    assert parsed['counterpoise_error_sources'][0]['line']==1 and geom is inp is None


@pytest.mark.parametrize('route', [ROUTE+' '+kw for kw in
    ('Opt','Freq','IRC','Scan','Guess=Read','Guess=(Read,Mix)','Force','Polar','Stable',
     'Geom=Check','Units=Bohr','Counterpoise=3','IOp(1/2=3)','ExtraBasis')] +
    [ROUTE.replace('6-31+G(d,p)', 'Gen'), ROUTE.replace('6-31+G(d,p)', 'GenECP'),
     ROUTE.replace('M062X', 'MP2'), ROUTE.replace('Counterpoise=2','Counterpoise=(2,OldGhost)'),
     ROUTE.replace('Counterpoise=2','')])
def test_cp_rejects_unsupported_tasks_and_protocol_before_attempt(cfg,tmp_path,route):
    with pytest.raises(ValueError):prepare_cp(cfg,tmp_path,route=route)
    assert not list((Path(cfg['local']['studies_root'])/'cp-test/attempts').iterdir())


def test_cp_default_sp_and_explicit_numerical_options(cfg,tmp_path):
    prepare_cp(cfg,tmp_path,route=ROUTE.replace(' SP','')+' SCF=(Tight,XQC) Int=UltraFine NoSymm')


def test_cp_missing_fragments_and_labels_input_rejected(cfg,tmp_path):
    with pytest.raises(ValueError,match='--fragments'):prepare_cp(cfg,tmp_path,fragments=None)
    with pytest.raises(ValueError,match='real element'):prepare_cp(cfg,tmp_path,geometry=WATER.replace('O 0','O(Fragment=1) 0'))


def test_cp_template_scnet_bytes_and_template_restrictions(multi,tmp_path):
    entry=multi['clusters']['batch']
    entry['programs']['gaussian']['environment']='scnet-a03'
    p,m=prepare_cp(multi,tmp_path,cluster='batch')
    files=attempt.verified_files(multi,p,m)
    assert files['job.slurm']==render.render(multi,{**m,'template':'gaussian'},'water.gjf').encode()
    assert remote.output_names(m)==['water.log','job.slurm.out','job.slurm.err']
    entry['allowed_templates']=['crest','xtb']
    with pytest.raises(ValueError,match='not allowed'):prepare_cp(multi,tmp_path,cluster='batch')
    entry['allowed_templates']=['gaussian-cp']
    prepare_cp(multi,tmp_path,cluster='batch')


def test_cp_fake_submission_uploads_bound_files_once(cfg,tmp_path,monkeypatch):
    p,m=prepare_cp(cfg,tmp_path)
    fake=Fake(config.select_cluster(cfg,'default'))
    allow(monkeypatch)
    submit.submit(cfg,[p.name],fake)
    assert set(fake.files)=={'water.gjf','water.gjf.fragments.csv','job.pbs'}
    assert len([x for x in fake.calls if x.operation=='submit'])==1
    with pytest.raises(ValueError):submit.submit(cfg,[p.name],fake)
    assert len([x for x in fake.calls if x.operation=='submit'])==1


def orientation(geometry):
    from ag.gaussian_input import ATOMIC_NUMBERS
    return (' Input orientation:\n' + ' -----\n Center Atomic Atomic Coordinates (Angstroms)\n'
            ' Number Number Type X Y Z\n -----\n' + '\n'.join(
                f' {i} {ATOMIC_NUMBERS[s]} 0 {x} {y} {z}' for i,(s,x,y,z) in enumerate(
                    [row.split() for row in geometry.splitlines()],1)) + '\n -----\n')


def synthetic_log(geometry=WATER,charge=0,route=ROUTE,solvent=False):
    """Synthetic values in documented layouts; NOT a G16 A.03 live fixture."""
    header = (' Entering Gaussian System\n Gaussian, Inc.\n Gaussian 16: ES64L-G16RevA.03 25-Dec-2016\n'
              ' -------------------\n '+route+'\n -------------------\n'
              f' Charge = {charge} Multiplicity = 1'+('' if solvent else ' in supermolecule')+'\n')
    if not solvent:
        header+=f' Charge = {charge} Multiplicity = 1 in fragment  1.\n Charge = 0 Multiplicity = 1 in fragment  2.\n'
    header+=orientation(geometry)
    if solvent:
        return header+(' Polarizable Continuum Model (PCM)\n =================================\n'
                       ' Model                : PCM.\n Atomic radii         : SMD-Coulomb.\n'
                       ' Solvent              : DiChloroEthane, Eps = 10.125000 Eps(inf) = 2.085000\n'
                       ' ----------------------------------\n'
                       ' SCF Done:  E(RM062X) =  -152.010000000000 A.U. after 10 cycles\n'
                       ' Normal termination of Gaussian 16\n')
    # E_AB=-152; monomers=-75.99 each; ghost monomers=-75.991 each.
    # BSSE=0.002 Hartree, raw interaction=-0.02, corrected=-0.018 Hartree.
    body=(' Counterpoise: doing full-system calculation.\n'
          ' SCF Done:  E(RM062X) =  -152.000000000000 A.U. after 10 cycles\n')
    for basis in ('DCBS','MCBS'):
        for i in (1,2):
            body+=f' Counterpoise: doing calculation for fragment   {i} using the basis set of the '+('full-system, NewBq=T' if basis=='DCBS' else 'fragment.')+'\n'
            body+=f' SCF Done:  E(RM062X) =  {(-75.991 if basis=="DCBS" else -75.99):.12f} A.U. after 9 cycles\n'
    body+=(' Counterpoise corrected energy = -151.998000000000\n'
           ' BSSE energy = 0.002000000000\n sum of fragments = -151.980000000000\n'
           ' complexation energy = -12.55 kcal/mole (raw)\n'
           ' complexation energy = -11.30 kcal/mole (corrected)\n'
           ' Normal termination of Gaussian 16\n')
    return header+body


def test_cp_facts_source_lines_whole_geometry_and_energies(cfg,tmp_path):
    p,m=prepare_cp(cfg,tmp_path)
    log=p/'outputs/water.log';text=synthetic_log();log.write_text(text)
    result=facts.build_facts(p)
    cp=result['counterpoise']
    assert result['program']=='gaussian-cp' and result['charge']==0 and result['n_atoms']==6
    assert result['energies']['scf']==-152 and cp['uncorrected_energy']['value']==-152
    assert cp['bsse']['value']==.002 and cp['fragments'][1]['mcbs']['value']==-75.99
    assert result['final_geometry']=='final.xyz' and int((p/'final.xyz').read_text().splitlines()[0])==6
    for value in (cp['bsse'],cp['corrected_energy'],cp['fragments'][0]['dcbs']):
        assert value['source']['sha256']==sha256(text.encode()).hexdigest()
        assert str(value['value'])[:6] in text.splitlines()[value['source']['line']-1]
    first=(p/'facts.json').read_bytes();facts.build_facts(p);assert first==(p/'facts.json').read_bytes()


@pytest.mark.parametrize('mutation', [
    lambda s:s.replace(' BSSE energy = 0.002000000000\n',''),
    lambda s:s.replace('BSSE energy = 0.002','BSSE energy = 0.003'),
    lambda s:s.replace('sum of fragments','sum of unknowns'),
    lambda s:s.replace('the fragment.','the UNKNOWN.'),
    lambda s:s.replace('calculation for fragment   2','calculation for fragment   1'),
    lambda s:s.replace('Normal termination of Gaussian 16','Normal termination of Gaussian 16\ntrailing unrecognized job'),
    lambda s:s.replace('Counterpoise corrected energy','Counterpoise: corrected energy'),
    lambda s:s.replace('RM062X','RB3LYP'),
    lambda s:s.replace('doing full-system calculation.', 'doing DCBS calculation for fragment   1 NewBq=T'),
    lambda s:s.replace(' Counterpoise: doing full-system calculation.\n', ''),
    lambda s:s.replace(' Counterpoise: doing full-system calculation.',
                       ' Counterpoise: doing full-system calculation.\n Counterpoise: doing full-system calculation.'),
    lambda s:s.replace('-11.30 kcal/mole','-22.30 kcal/mole'),
])
def test_unrecognized_or_inconsistent_cp_output_fails(tmp_path,mutation):
    path=tmp_path/'cp.log';path.write_text(mutation(synthetic_log()))
    with pytest.raises(ValueError):facts.parse_counterpoise(path)


def test_cp_report_arithmetic_provenance_and_immutable_output(cfg,tmp_path,monkeypatch,capsys):
    p,m=prepare_cp(cfg,tmp_path);(p/'outputs/water.log').write_text(synthetic_log())
    facts.build_facts(p)
    root=p.parent.parent
    monkeypatch.setattr(cli,'load_config',lambda:pytest.fail('no config'))
    monkeypatch.setattr('ag.transport.SSHTransport',lambda *a,**k:pytest.fail('no SSH'))
    result=cp_report.report(str(p))
    assert result['schema']=='ag-cp/1' and result['notice']==cp_report.NOTICE
    assert result['gas']['bsse']['kcal_mol']==pytest.approx(1.255019082)
    assert result['gas']['interaction_raw']['hartree']==pytest.approx(-.02)
    assert result['gas']['interaction_corrected']['hartree']==pytest.approx(-.018)
    assert result['solvent'] is None
    for item in result['sources']:
        assert sha256((root/item['path']).read_bytes()).hexdigest()==item['sha256']
    assert cli.main(['cp-report',str(p),'--out','analyses/cp.json','--json'])==0
    saved=(root/'analyses/cp.json').read_bytes()
    assert json.loads(saved)['gas']==result['gas']
    assert '未进入 thermo/profile' in (root/'analyses/cp.md').read_text()
    assert cli.main(['cp-report',str(p),'--out','analyses/cp.json'])==1
    assert (root/'analyses/cp.json').read_bytes()==saved


def solvent_attempt(cfg,tmp_path,geometry=WATER,route=None,charge=0):
    route=route or ROUTE.replace(' Counterpoise=2',' SCRF=(SMD,Solvent=DiChloroEthane)')
    p,m=prepare_cp(cfg,tmp_path,template='gaussian',fragments=None,route=route,geometry=geometry,charge=charge)
    (p/'outputs/water.log').write_text(synthetic_log(geometry,charge,route,solvent=True))
    return p,m


def test_solvent_missing_fragment_energies_never_substituted(cfg,tmp_path):
    p,m=prepare_cp(cfg,tmp_path);(p/'outputs/water.log').write_text(synthetic_log())
    s,_=solvent_attempt(cfg,tmp_path)
    result=cp_report.report(str(p),solvent_sp=str(s))['solvent']
    assert result['complex_energy_plus_gas_bsse']['hartree']==pytest.approx(-152.008)
    assert result['interaction_raw'] is result['interaction_corrected'] is None
    assert len(result['missing'])==2 and all(v['energy'] is None for v in result['fragment_energies'])
    assert result['note']==cp_report.SOLVENT_NOTE


def smd_set(cfg, tmp_path, *, geometry=WATER, charge=0, csv=CSV):
    """Independent synthetic operands: -152.01 - (-76.001) - (-75.998)."""
    p, _ = prepare_cp(cfg, tmp_path, geometry=geometry, charge=charge, csv=csv)
    (p / 'outputs/water.log').write_text(synthetic_log(geometry, charge))
    s, _ = solvent_attempt(cfg, tmp_path, geometry=geometry, charge=charge)
    definitions = validate(csv, geometry, charge)['fragments']
    fragments = []
    for definition, energy in zip(definitions, ('-76.001000000000', '-75.998000000000')):
        subset = '\n'.join(geometry.splitlines()[i - 1] for i in definition['atoms'])
        f, _ = solvent_attempt(cfg, tmp_path, geometry=subset, charge=definition['charge'])
        log = f / 'outputs/water.log'
        # CDS is already included in SCF Done. Its printed value is not added.
        log.write_text(log.read_text().replace('-152.010000000000', energy).replace(
            ' Normal termination', ' SMD-CDS (non-electrostatic) energy (kcal/mol) = 1.23\n'
            ' (included in total energy above)\n Normal termination'))
        fragments.append(f)
    return p, s, fragments


def fragment_options(fragments):
    return [f'{i}:{f.name}' for i, f in enumerate(fragments, 1)]


def test_smd_fragment_arithmetic_sources_mapping_and_cli(cfg, tmp_path, monkeypatch, capsys):
    p, s, fs = smd_set(cfg, tmp_path)
    root = p.parent.parent
    for f in [p, s, *fs]:
        facts.build_facts(f)
    before = {f: f.read_bytes() for directory in [p, s, *fs] for f in directory.rglob('*') if f.is_file()}
    monkeypatch.setattr(cli, 'load_config', lambda: pytest.fail('no config'))
    monkeypatch.setattr('ag.transport.SSHTransport', lambda *a, **k: pytest.fail('no SSH'))
    args = ['cp-report', str(p), '--solvent-sp', s.name, '--out', 'analyses/complete.json', '--json']
    for option in reversed(fragment_options(fs)):
        args += ['--solvent-fragment-sp', option]
    assert cli.main(args) == 0
    result = json.loads((root / 'analyses/complete.json').read_text())
    solvent = result['solvent']
    # Decimal hand calculation, independent of report implementation/constants.
    from decimal import Decimal
    raw = Decimal('-152.010') - Decimal('-76.001') - Decimal('-75.998')
    corrected = raw + Decimal('0.002')
    assert raw == Decimal('-0.011') and corrected == Decimal('-0.009')
    for key, expected in [('interaction_raw', raw), ('interaction_corrected', corrected)]:
        quantity = solvent[key]
        assert quantity['hartree'] == pytest.approx(float(expected), abs=1e-12)
        assert quantity['kcal_mol'] == pytest.approx(float(expected * Decimal('627.509541')), abs=1e-8)
        assert len(quantity['operand_pointers']) == (3 if key == 'interaction_raw' else 4)
        assert len(quantity['sources']) == len(quantity['operand_pointers'])
        for source in quantity['sources']:
            log = root / source['path']
            assert source['sha256'] == sha256(log.read_bytes()).hexdigest()
            assert 'SCF Done:' in log.read_text().splitlines()[source['line'] - 1] or key == 'interaction_corrected'
    assert solvent['missing'] == []
    assert solvent['complex_energy_plus_gas_bsse']['hartree'] == pytest.approx(-152.008)
    for i, fragment in enumerate(solvent['fragment_energies']):
        assert fragment['index'] == i + 1 and fragment['attempt'] == fs[i].name
        assert fragment['binding']['atom_mapping'] == [
            dict(complex_atom=i * 3 + n, fragment_atom=n) for n in (1, 2, 3)]
        assert fragment['binding']['fragments_source'] == result['fragments']['source']
        assert fragment['pairing']['rmsd_angstrom'] < 1e-12
        assert fragment['output_pairing']['rmsd_angstrom'] < 1e-12
        assert fragment['section_source']['printed_conditions']['solvent']['values']['model'] == 'smd'
    md = (root / 'analyses/complete.md').read_text()
    assert 'SMD 相互作用能 + 气相 BSSE（近似）' in md and '-6.90260495' in md and '-5.64758587' in md
    assert '未知' not in md and '不是计算出的结合自由能' in md
    assert 'E_AB(SMD) - E_A(SMD) - E_B(SMD)' in md
    assert before == {f: f.read_bytes() for f in before}
    saved = (root / 'analyses/complete.json').read_bytes()
    assert cli.main(args) == 1
    assert (root / 'analyses/complete.json').read_bytes() == saved


@pytest.mark.parametrize('index', [1, 2])
def test_one_smd_fragment_preserves_known_value_and_exact_missing_item(cfg, tmp_path, index):
    p, s, fs = smd_set(cfg, tmp_path)
    result = cp_report.report(str(p), solvent_sp=s.name,
                             solvent_fragment_sp=[fragment_options(fs)[index - 1]])
    solvent = result['solvent']
    assert solvent['interaction_raw'] is solvent['interaction_corrected'] is None
    assert solvent['fragment_energies'][index - 1]['energy'] is not None
    assert solvent['fragment_energies'][2 - index]['energy'] is None
    assert len(solvent['missing']) == 1 and f'片段 {3 - index}' in solvent['missing'][0]
    assert '未知' in cp_report.markdown(result)


@pytest.mark.parametrize('options,solvent,error', [
    (['1:a', '1:b'], 's', 'Duplicate'), (['0:a'], 's', 'requires 1:'),
    (['3:a'], 's', 'requires 1:'), (['water-a:a'], 's', 'requires 1:'),
    (['1:a', '2:a'], 's', 'Same Attempt'), (['1:a'], None, 'requires --solvent-sp'),
    (['1:../a'], 's', 'IDs must'), (['1:'], 's', 'requires 1:'),
])
def test_fragment_arguments_refuse_ambiguous_or_unsafe_assignment(options, solvent, error):
    with pytest.raises(ValueError, match=error):
        cp_report.report('never-read', solvent_sp=solvent, solvent_fragment_sp=options)


def test_fragment_state_uses_each_cp_declaration(cfg, tmp_path):
    p, s, fs = smd_set(cfg, tmp_path, geometry=NH4_WATER, charge=1, csv=NH4_CSV)
    result = cp_report.report(str(p), solvent_sp=s.name, solvent_fragment_sp=fragment_options(fs))
    assert [f['binding']['charge'] for f in result['solvent']['fragment_energies']] == [1, 0]
    bad, _ = solvent_attempt(cfg, tmp_path, geometry='\n'.join(NH4_WATER.splitlines()[:5]), charge=-1)
    with pytest.raises(ValueError, match='declared state differs'):
        cp_report.report(str(p), solvent_sp=s.name, solvent_fragment_sp=[f'1:{bad.name}'])


@pytest.mark.parametrize('change,error', [
    ('geometry', 'RMSD'), ('extra_atom', 'element sequence'), ('swapped', 'RMSD'),
    ('method', 'method/basis/dispersion'), ('basis_type', 'method/basis/dispersion'),
    ('dispersion', 'method/basis/dispersion'), ('solvent', 'printed solvent parameters'),
    ('epsilon', 'printed solvent parameters'), ('radii', 'disagrees'),
    ('model', 'requires SMD'), ('missing_pcm', 'printed solvent'),
    ('opt', 'single point'), ('freq', 'single point'), ('mixed', 'single point|protocol|sections'),
    ('error', 'normally terminated'), ('cp_output', 'own-basis'), ('ghost_output', 'own-basis'),
    ('gen', 'Custom basis'), ('extra_basis', 'Custom basis'), ('units', 'only supports'),
    ('output_geometry', 'RMSD'), ('output_state', 'state differs'), ('scf_method', 'SCF method differs'),
])
def test_fragment_sources_fail_closed(cfg, tmp_path, change, error):
    # A symmetric water's exchanged H rows can be rigidly indistinguishable.
    reference = WATER.replace('0.9572', '1.05') if change == 'swapped' else WATER
    p, s, fs = smd_set(cfg, tmp_path, geometry=reference)
    geometry = '\n'.join(reference.splitlines()[:3])
    route = ROUTE.replace(' Counterpoise=2', ' SCRF=(SMD,Solvent=DiChloroEthane)')
    if change == 'geometry': geometry = geometry.replace('0.9572', '1.1')
    if change == 'extra_atom': geometry += '\nHe 8 0 0'
    if change == 'swapped': geometry = '\n'.join([*geometry.splitlines()[:1], *geometry.splitlines()[1:][::-1]])
    if change == 'method': route = route.replace('6-31+G(d,p)', 'def2TZVP')
    if change == 'basis_type': route += ' 5D'
    if change == 'dispersion': route += ' EmpiricalDispersion=GD3'
    if change == 'solvent': route = route.replace('DiChloroEthane', 'Water')
    if change == 'model': route = route.replace('SMD', 'PCM')
    if change in ('opt', 'freq'): route = route.replace(' SP', ' ' + change)
    if change == 'gen': route = route.replace('6-31+G(d,p)', 'Gen')
    if change == 'extra_basis': route += ' ExtraBasis'
    if change == 'units': route += ' Units=Bohr'
    f, _ = solvent_attempt(cfg, tmp_path, geometry=geometry, route=route)
    log = f / 'outputs/water.log'
    text = log.read_text()
    if change == 'solvent': text = text.replace('DiChloroEthane', 'Water')
    if change == 'epsilon': text = text.replace('10.125000', '10.225000')
    if change in ('radii', 'model'): text = text.replace('SMD-Coulomb', 'UA0')
    if change == 'missing_pcm': text = text[:text.index(' Polarizable Continuum')] + text[text.index(' SCF Done:'):]
    if change == 'mixed': text += synthetic_log(geometry, route=route.replace(' SP', ' Freq'), solvent=True)
    if change == 'error': text = text.replace('Normal termination', 'Error termination')
    if change == 'cp_output': text = text.replace(' SCF Done:', ' Counterpoise: doing calculation for fragment 1\n SCF Done:')
    if change == 'ghost_output': text = text.replace(' SCF Done:', ' NewBq=T\n SCF Done:')
    if change == 'output_geometry': text = text.replace('0.9572', '1.1')
    if change == 'output_state': text = text.replace('Multiplicity = 1', 'Multiplicity = 3')
    if change == 'scf_method': text = text.replace('E(RM062X)', 'E(RB3LYP)')
    log.write_text(text)
    with pytest.raises(ValueError, match=error):
        cp_report.report(str(p), solvent_sp=s.name, solvent_fragment_sp=[f'1:{f.name}'])


@pytest.mark.parametrize('change', ['input', 'log', 'facts', 'symlink', 'read_change'])
def test_fragment_evidence_failure_does_not_publish_or_refresh(cfg, tmp_path, monkeypatch, change):
    from ag.ensemble import _Evidence
    p, s, fs = smd_set(cfg, tmp_path)
    f = fs[0]
    facts.build_facts(f)
    cache = f / 'facts.json'
    if change == 'input':
        path = f / 'inputs/water.gjf'
        path.write_text(path.read_text() + '\n')
    if change == 'log':
        path = f / 'outputs/water.log'
        path.write_text(path.read_text().replace('-76.001', '-76.002'))
    if change == 'facts': cache.write_text(cache.read_text().replace('-76.001', '-76.002'))
    if change == 'symlink':
        log = f / 'outputs/water.log'
        backup = tmp_path / 'outside.log'
        backup.write_bytes(log.read_bytes())
        log.unlink()
        log.symlink_to(backup)
    if change == 'read_change':
        verify = _Evidence.verify
        def changed(evidence):
            log = f / 'outputs/water.log'
            log.write_text(log.read_text() + '\n')
            verify(evidence)
        monkeypatch.setattr(_Evidence, 'verify', changed)
    saved = cache.read_bytes()
    assert cli.main(['cp-report', str(p), '--solvent-sp', s.name,
                     '--solvent-fragment-sp', f'1:{f.name}', '--out', 'analyses/refused.json']) == 1
    assert cache.read_bytes() == saved
    assert not (p.parent.parent / 'analyses/refused.json').exists()
    assert not (p.parent.parent / 'analyses/refused.md').exists()


@pytest.mark.parametrize('change', ['ghost', 'fragment_label', 'external_basis'])
def test_fragment_input_cannot_hide_ghost_or_external_basis_in_valid_bundle(cfg, tmp_path, change):
    p, s, fs = smd_set(cfg, tmp_path)
    f = fs[0]
    source = f / 'inputs/water.gjf'
    text = source.read_text()
    if change == 'ghost': text = text.replace('O 0 0 0', 'Bq 0 0 0')
    if change == 'fragment_label': text = text.replace('O 0 0 0', 'O(Fragment=1) 0 0 0')
    if change == 'external_basis': text += '@custom.gbs\n'
    source.write_text(text)
    path = f / 'manifest.json'
    manifest = json.loads(path.read_text())
    manifest['inputs'], manifest['bundle_sha256'] = attempt.bundle({
        item['name']: (f / 'inputs' / item['name']).read_bytes() for item in manifest['inputs']})
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='real element|includes'):
        cp_report.report(str(p), solvent_sp=s.name, solvent_fragment_sp=[f'1:{f.name}'])


def test_fragment_mode_requires_smd_complex_and_ordinary_fragment_template(cfg, tmp_path):
    p, s, fs = smd_set(cfg, tmp_path)
    route = ROUTE.replace(' Counterpoise=2', ' SCRF=(PCM,Solvent=DiChloroEthane)')
    pcm, _ = solvent_attempt(cfg, tmp_path, route=route)
    log = pcm / 'outputs/water.log'
    log.write_text(log.read_text().replace('SMD-Coulomb', 'UA0'))
    # The legacy overlay still supports its old solvent models.
    assert cp_report.report(str(p), solvent_sp=pcm.name)['solvent']['interaction_raw'] is None
    with pytest.raises(ValueError, match='requires SMD'):
        cp_report.report(str(p), solvent_sp=pcm.name, solvent_fragment_sp=fragment_options(fs))
    with pytest.raises(ValueError, match='expected gaussian Attempt'):
        cp_report.report(str(p), solvent_sp=s.name, solvent_fragment_sp=[f'1:{p.name}'])


def test_fragment_mirror_and_rigid_motion_with_noncontiguous_atom_mapping(cfg, tmp_path):
    # Two separated synthetic CHBrClF molecules; fragment 1 is chiral and its
    # atom numbers interleave with fragment 2. No identity/permutation search.
    a = ['C 0 0 0', 'F .8 .8 .8', 'Cl 1 -1 -1', 'Br -1 1 -1', 'H -.6 -.6 .6']
    b = [f'{s} {float(x)+10} {y} {z}' for s, x, y, z in (row.split() for row in a)]
    geometry = '\n'.join(row for pair in zip(a, b) for row in pair)
    csv = HEADER + 'a,"1,3,5,7,9",0,1\nb,"2,4,6,8,10",0,1\n'
    p, s, fs = smd_set(cfg, tmp_path, geometry=geometry, csv=csv)
    rotated = '\n'.join(f'{symbol} {-float(y)+2} {float(x)-3} {float(z)+4}'
                        for symbol, x, y, z in (row.split() for row in a))
    f, _ = solvent_attempt(cfg, tmp_path, geometry=rotated)
    result = cp_report.report(str(p), solvent_sp=s.name, solvent_fragment_sp=[f'1:{f.name}'])
    fragment = result['solvent']['fragment_energies'][0]
    assert fragment['binding']['atom_mapping'] == [dict(complex_atom=i*2-1, fragment_atom=i) for i in range(1, 6)]
    assert fragment['pairing']['rmsd_angstrom'] < 1e-12
    mirrored = '\n'.join(f'{symbol} {-float(x)} {y} {z}' for symbol, x, y, z in (row.split() for row in a))
    f, _ = solvent_attempt(cfg, tmp_path, geometry=mirrored)
    with pytest.raises(ValueError, match='RMSD'):
        cp_report.report(str(p), solvent_sp=s.name, solvent_fragment_sp=[f'1:{f.name}'])


def test_fragment_grid_difference_is_warning_not_new_threshold(cfg, tmp_path):
    p, s, fs = smd_set(cfg, tmp_path)
    route = ROUTE.replace(' Counterpoise=2', ' SCRF=(SMD,Solvent=DiChloroEthane) Int=UltraFine')
    f, _ = solvent_attempt(cfg, tmp_path, route=route, geometry='\n'.join(WATER.splitlines()[:3]))
    result = cp_report.report(str(p), solvent_sp=s.name, solvent_fragment_sp=[f'1:{f.name}'])
    assert result['solvent']['warnings']


def test_fragment_report_paths_and_cross_study_sources_are_rejected(cfg, tmp_path, capsys):
    p, s, fs = smd_set(cfg, tmp_path)
    root = p.parent.parent
    args = ['cp-report', str(p), '--solvent-sp', s.name, '--solvent-fragment-sp', f'1:{fs[0].name}']
    assert cli.main([*args, '--out', '../outside.json']) == 1
    link = root / 'analyses/link.json'
    link.symlink_to(tmp_path / 'unused.json')
    assert cli.main([*args, '--out', 'analyses/link.json']) == 1
    with pytest.raises(ValueError, match='IDs must'):
        cp_report.report(str(p), solvent_sp=s.name, solvent_fragment_sp=[f'1:{fs[0]}'])


@pytest.mark.parametrize('change,error', [('geometry','RMSD'),('method','protocol|method'),('gas','solvent model'),
                                         ('missing_pcm','printed solvent'),('opt','single point')])
def test_solvent_pairing_and_execution_evidence(cfg,tmp_path,change,error):
    p,m=prepare_cp(cfg,tmp_path);(p/'outputs/water.log').write_text(synthetic_log())
    geometry=WATER.replace('0.9572','1.1') if change=='geometry' else WATER
    route=ROUTE.replace(' Counterpoise=2',' SCRF=(SMD,Solvent=DiChloroEthane)')
    if change=='method':route=route.replace('6-31+G(d,p)','def2TZVP')
    if change=='gas':route=route.split(' SCRF')[0]
    if change=='opt':route=route.replace(' SP',' Opt')
    s,_=solvent_attempt(cfg,tmp_path,geometry=geometry,route=route)
    if change=='missing_pcm':
        log=s/'outputs/water.log';text=log.read_text();start=text.index(' Polarizable Continuum');end=text.index(' SCF Done:');log.write_text(text[:start]+text[end:])
    with pytest.raises(ValueError,match=error):cp_report.report(str(p),solvent_sp=str(s))


def test_stale_facts_and_report_symlinks_rejected(cfg,tmp_path):
    p,m=prepare_cp(cfg,tmp_path);(p/'outputs/water.log').write_text(synthetic_log())
    facts.build_facts(p)
    cache=p/'facts.json';saved=cache.read_bytes();cache.write_text(saved.decode().replace('0.002','0.003'))
    with pytest.raises(ValueError,match='Saved facts differ'):cp_report.report(str(p))
    cache.write_bytes(saved)
    log=p/'outputs/water.log';backup=tmp_path/'outside.log';backup.write_bytes(log.read_bytes());log.unlink();log.symlink_to(backup)
    with pytest.raises(ValueError,match='[Ss]ymlink|[Ss]ymbolic'):cp_report.report(str(p))


def test_thermo_spc_profile_direct_cached_and_asm_refuse_cp(cfg,tmp_path):
    from ag import thermo, profile, asm
    from ag.ensemble import _Evidence
    from test_profile import definition, dump
    p,m=prepare_cp(cfg,tmp_path)
    with pytest.raises(ValueError,match='CP 单点仅用于 cp-report'):thermo.calculate_thermo([str(p)])
    s,_=solvent_attempt(cfg,tmp_path)
    with pytest.raises(ValueError,match='CP 单点仅用于 cp-report'):
        thermo.calculate_thermo([str(s)],spc={str(s):str(p)})
    with pytest.raises(ValueError,match='CP 单点仅用于 cp-report'):
        asm._load_energy(_Evidence(p.parent.parent),p.name,'input','test')
    path,data=definition(tmp_path/'profile-test')
    for mode in ('direct','cached','spc'):
        if mode=='direct':data['species']['R']={'attempts':[{'attempt_id':'cp'}]}
        else:
            data['species']['R']={'thermo':'R.json'}
            table=json.loads((path.parent/'R.json').read_text())
            if mode=='cached':table['rows'][0]['attempt_id']='cp'
            else:table['rows'][0]['attempt_id']='R-0';table['rows'][0]['spc_attempt_id']='cp'
            dump(path.parent/'R.json',table)
        dump(path.parent.parent/'attempts/cp/manifest.json',{'template':'gaussian-cp'})
        dump(path,data)
        with pytest.raises(ValueError,match='CP 单点仅用于 cp-report'):profile.calculate_profile(path)


def test_printed_fragment_charge_cannot_silently_change_assignment(cfg,tmp_path):
    p,m=prepare_cp(cfg,tmp_path,geometry=NH4_WATER,charge=1,csv=NH4_CSV)
    text=synthetic_log(NH4_WATER,1)
    log=p/'outputs/water.log';log.write_text(text)
    assert cp_report.report(str(p))['fragments']['fragments'][0]['charge']==1
    log.write_text(text.replace('Charge = 1 Multiplicity = 1 in fragment  1.',
                                'Charge = 0 Multiplicity = 1 in fragment  1.'))
    with pytest.raises(ValueError,match='fragment state differs'):cp_report.report(str(p))


def test_asm_deformation_stays_beside_cp_and_checks_sources(cfg,tmp_path):
    p,m=prepare_cp(cfg,tmp_path);(p/'outputs/water.log').write_text(synthetic_log())
    root=p.parent.parent
    provenance=root/'analyses/asm-source.json';provenance.write_text('{"synthetic": true}')
    asm=root/'analyses/asm.json'
    asm.write_text(json.dumps(dict(schema='ag-asm/1',units={'energy':'Hartree'},
        sources=[{'path':'analyses/asm-source.json','sha256':sha256(provenance.read_bytes()).hexdigest()}],
        systems=[dict(label='separate diagnostic',complex={'attempt':'ordinary-sp'},
                      E_dist_total={'hartree':.03,'kcal_mol':18.82528623})])))
    base=cp_report.report(str(p));combined=cp_report.report(str(p),asm=str(asm))
    assert base['gas']==combined['gas'] and combined['asm']['systems'][0]['deformation']['hartree']==.03
    assert combined['asm']['systems'][0]['source']['json_pointer']=='/systems/0/E_dist_total'
    assert '不与 CP 组合' in cp_report.markdown(combined)
    provenance.write_text('{"synthetic": false}')
    with pytest.raises(ValueError,match='ASM source hash mismatch'):cp_report.report(str(p),asm=str(asm))


def test_manifest_tampering_is_caught_after_bundle_recomputed(cfg,tmp_path):
    p,m=prepare_cp(cfg,tmp_path)
    text=(p/'inputs/water.gjf').read_text().replace('H(Fragment=1)','H(Fragment=2)',1)
    (p/'inputs/water.gjf').write_text(text)
    files={path.name:path.read_bytes() for path in (p/'inputs').iterdir()}
    m['inputs'],m['bundle_sha256']=attempt.bundle(files)
    with pytest.raises(ValueError,match='labels/states differ'):attempt.verified_files(cfg,p,m)


# Real G16 A.03 water-dimer CP, 2026-10-22. Selected original lines only;
# machine/archive/title sections omitted, scientific numbers and label bytes retained.
# Original SHA-256: 6bea540a4fb31615d2910b63aba963f03127e51d6cdd0a50176b3eee9a6d4db9
LIVE_WATER_SOURCE_LINES = [79, 85, 86, 87, 105, 106, 107, 108, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125, 126, 127, 144, 145, 146, 147, 148, 149, 150, 151, 152, 153, 154, 155, 157, 158, 197, 274, 315, 392, 433, 510, 548, 613, 651, 717, 718, 719, 720, 721, 734, 735, 737]
LIVE_WATER_CP = """ Gaussian 16:  ES64L-G16RevA.03 25-Dec-2016
 -------------------------------------
 # M062X/6-31+G(d,p) SP Counterpoise=2
 -------------------------------------
 Symbolic Z-matrix:
 Charge =  0 Multiplicity = 1 in supermolecule
 Charge =  0 Multiplicity = 1 in fragment      1.
 Charge =  0 Multiplicity = 1 in fragment      2.
                          Input orientation:
 ---------------------------------------------------------------------
 Center     Atomic      Atomic             Coordinates (Angstroms)
 Number     Number       Type             X           Y           Z
 ---------------------------------------------------------------------
      1          8           0        0.000000    0.000000    0.000000
      2          1           0        0.957200    0.000000    0.000000
      3          1           0       -0.239987    0.927297    0.000000
      4          8           0        2.900000    0.000000    0.000000
      5          1           0        3.485882    0.756950    0.000000
      6          1           0        3.485882   -0.756950    0.000000
 ---------------------------------------------------------------------
                         Standard orientation:
 ---------------------------------------------------------------------
 Center     Atomic      Atomic             Coordinates (Angstroms)
 Number     Number       Type             X           Y           Z
 ---------------------------------------------------------------------
      1          8           0        0.046365    1.544449    0.000000
      2          1           0        0.046365    0.587249    0.000000
      3          1           0       -0.880932    1.784436    0.000000
      4          8           0        0.046365   -1.355551   -0.000000
      5          1           0       -0.710585   -1.941433   -0.000000
      6          1           0        0.803315   -1.941433   -0.000000
 ---------------------------------------------------------------------
 Counterpoise: doing full-system calculation.
 Standard basis: 6-31+G(d,p) (6D, 7F)
 SCF Done:  E(RM062X) =  -152.798813368     A.U. after   12 cycles
 Counterpoise: doing calculation for fragment   1 using the basis set of the full-system, NewBq=T
 SCF Done:  E(RM062X) =  -76.3951659986     A.U. after   10 cycles
 Counterpoise: doing calculation for fragment   2 using the basis set of the full-system, NewBq=T
 SCF Done:  E(RM062X) =  -76.3958363253     A.U. after   11 cycles
 Counterpoise: doing calculation for fragment   1 using the basis set of the fragment.
 SCF Done:  E(RM062X) =  -76.3948728126     A.U. after   12 cycles
 Counterpoise: doing calculation for fragment   2 using the basis set of the fragment.
 SCF Done:  E(RM062X) =  -76.3948695133     A.U. after   12 cycles
 Counterpoise corrected energy =    -152.797553369586
                   BSSE energy =       0.001259998062
              sum of fragments =    -152.789742325839
           complexation energy =      -5.69 kcal/mole (raw)
           complexation energy =      -4.90 kcal/mole (corrected)
 Job cpu time:       0 days  0 hours  0 minutes 29.5 seconds.
 Elapsed time:       0 days  0 hours  0 minutes  8.0 seconds.
 Normal termination of Gaussian 16 at Thu Oct 22 08:34:46 2026.
"""


def test_live_a03_water_cp_report_and_original_source_lines(cfg, tmp_path):
    p, m = prepare_cp(cfg, tmp_path)
    log = p / 'outputs/water.log'
    log.write_text(LIVE_WATER_CP)
    parsed = facts.build_facts(p)
    cp = parsed['counterpoise']
    assert parsed['termination'] == 'normal'
    assert cp['uncorrected_energy']['value'] == -152.798813368
    assert cp['corrected_energy']['value'] == -152.797553369586
    assert cp['bsse']['value'] == .001259998062
    assert cp['sum_fragments']['value'] == -152.789742325839
    assert [(f['dcbs']['value'], f['mcbs']['value']) for f in cp['fragments']] == [
        (-76.3951659986, -76.3948728126), (-76.3958363253, -76.3948695133)]
    for key, original in [('uncorrected_energy',197), ('corrected_energy',717), ('bsse',718)]:
        source = cp[key]['source']
        assert LIVE_WATER_SOURCE_LINES[source['line']-1] == original
        assert source['sha256'] == sha256(LIVE_WATER_CP.encode()).hexdigest()
    result = cp_report.report(str(p))
    assert result['gas']['bsse']['kcal_mol'] == pytest.approx(.790660805547, rel=0, abs=1e-9)
    assert result['gas']['interaction_raw']['kcal_mol'] == pytest.approx(-5.69216550284, rel=0, abs=1e-8)
    assert result['gas']['interaction_corrected']['kcal_mol'] == pytest.approx(-4.90150447642, rel=0, abs=1e-8)


# Real G16 A.03 NH4+...H2O CP, 2026-10-22; same omission policy as water.
# Original SHA-256: 3b034d49ebab671a54bfc36e65093d2ebc6305908edb3755da5290171a5f615e
LIVE_AMMONIUM_SOURCE_LINES = [79, 85, 86, 87, 105, 106, 107, 108, 118, 119, 120, 121, 122, 123, 124, 125, 126, 127, 128, 129, 130, 131, 152, 153, 154, 155, 156, 157, 158, 159, 160, 161, 162, 163, 164, 165, 167, 168, 207, 299, 340, 432, 473, 565, 603, 674, 711, 778, 779, 780, 781, 782, 796, 797, 799]
LIVE_AMMONIUM_CP = """ Gaussian 16:  ES64L-G16RevA.03 25-Dec-2016
 -------------------------------------
 # M062X/6-31+G(d,p) SP Counterpoise=2
 -------------------------------------
 Symbolic Z-matrix:
 Charge =  1 Multiplicity = 1 in supermolecule
 Charge =  1 Multiplicity = 1 in fragment      1.
 Charge =  0 Multiplicity = 1 in fragment      2.
                          Input orientation:
 ---------------------------------------------------------------------
 Center     Atomic      Atomic             Coordinates (Angstroms)
 Number     Number       Type             X           Y           Z
 ---------------------------------------------------------------------
      1          7           0        0.000000    0.000000    0.000000
      2          1           0        0.590000    0.590000    0.590000
      3          1           0        0.590000   -0.590000   -0.590000
      4          1           0       -0.590000    0.590000   -0.590000
      5          1           0       -0.590000   -0.590000    0.590000
      6          8           0        3.200000    0.000000    0.000000
      7          1           0        3.785882    0.756950    0.000000
      8          1           0        3.785882   -0.756950    0.000000
 ---------------------------------------------------------------------
                         Standard orientation:
 ---------------------------------------------------------------------
 Center     Atomic      Atomic             Coordinates (Angstroms)
 Number     Number       Type             X           Y           Z
 ---------------------------------------------------------------------
      1          7           0       -0.000000    0.000000   -1.579608
      2          1           0        0.590000    0.590000   -0.989608
      3          1           0       -0.590000   -0.590000   -0.989608
      4          1           0        0.590000   -0.590000   -2.169608
      5          1           0       -0.590000    0.590000   -2.169608
      6          8           0        0.000000    0.000000    1.620392
      7          1           0        0.756950    0.000000    2.206274
      8          1           0       -0.756950    0.000000    2.206274
 ---------------------------------------------------------------------
 Counterpoise: doing full-system calculation.
 Standard basis: 6-31+G(d,p) (6D, 7F)
 SCF Done:  E(RM062X) =  -133.285756136     A.U. after   11 cycles
 Counterpoise: doing calculation for fragment   1 using the basis set of the full-system, NewBq=T
 SCF Done:  E(RM062X) =  -56.8668077824     A.U. after    9 cycles
 Counterpoise: doing calculation for fragment   2 using the basis set of the full-system, NewBq=T
 SCF Done:  E(RM062X) =  -76.3950969136     A.U. after   10 cycles
 Counterpoise: doing calculation for fragment   1 using the basis set of the fragment.
 SCF Done:  E(RM062X) =  -56.8667839440     A.U. after    9 cycles
 Counterpoise: doing calculation for fragment   2 using the basis set of the fragment.
 SCF Done:  E(RM062X) =  -76.3948695133     A.U. after   12 cycles
 Counterpoise corrected energy =    -133.285504897089
                   BSSE energy =       0.000251238732
              sum of fragments =    -133.261653457267
           complexation energy =     -15.12 kcal/mole (raw)
           complexation energy =     -14.97 kcal/mole (corrected)
 Job cpu time:       0 days  0 hours  0 minutes 34.2 seconds.
 Elapsed time:       0 days  0 hours  0 minutes  9.1 seconds.
 Normal termination of Gaussian 16 at Thu Oct 22 08:41:00 2026.
"""


def test_live_a03_ammonium_cp_report_and_original_source_lines(cfg, tmp_path):
    p, m = prepare_cp(cfg, tmp_path, geometry=NH4_WATER, charge=1, csv=NH4_CSV)
    (p / 'outputs/water.log').write_text(LIVE_AMMONIUM_CP)
    parsed = facts.build_facts(p)
    cp = parsed['counterpoise']
    assert parsed['termination'] == 'normal' and parsed['charge'] == 1
    assert [(f['charge'], f['multiplicity']) for f in cp['fragments']] == [(1,1), (0,1)]
    assert cp['uncorrected_energy']['value'] == -133.285756136
    assert cp['corrected_energy']['value'] == -133.285504897089
    assert cp['bsse']['value'] == .000251238732
    assert cp['sum_fragments']['value'] == -133.261653457267
    assert [(f['dcbs']['value'], f['mcbs']['value']) for f in cp['fragments']] == [
        (-56.8668077824, -56.8667839440), (-76.3950969136, -76.3948695133)]
    for key, original in [('uncorrected_energy',207), ('corrected_energy',778), ('bsse',779)]:
        source = cp[key]['source']
        assert LIVE_AMMONIUM_SOURCE_LINES[source['line']-1] == original
        assert source['sha256'] == sha256(LIVE_AMMONIUM_CP.encode()).hexdigest()
    result = cp_report.report(str(p))
    assert result['gas']['bsse']['kcal_mol'] == pytest.approx(.157654701399, rel=0, abs=1e-9)
    assert result['gas']['interaction_raw']['kcal_mol'] == pytest.approx(-15.12466086863, rel=0, abs=1e-8)
    assert result['gas']['interaction_corrected']['kcal_mol'] == pytest.approx(-14.96700605490, rel=0, abs=1e-8)


@pytest.mark.parametrize('text', [LIVE_WATER_CP, LIVE_AMMONIUM_CP])
@pytest.mark.parametrize('old,new', [
    ('full-system, NewBq=T', 'full-system, NewBq=F'),
    ('using the basis set of the fragment.', 'using an unknown basis.'),
    ('Counterpoise: doing calculation for fragment', 'Counterpoise: doing DCBS calculation for fragment'),
    ('sum of fragments', 'sum of unknowns'),
])
def test_live_a03_unknown_labels_still_refused(tmp_path, text, old, new):
    log = tmp_path / 'changed.log'
    assert old in text
    log.write_text(text.replace(old, new))
    with pytest.raises(ValueError, match='Unknown'):
        facts.parse_counterpoise(log)

"""T92 uses temporary synthetic systems and fake programs only; never SSH."""
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from ag import attempt, cli, config, nci_report, remote, render, state, study, submission, submit, fetch, status
from ag.transport import Result
from test_core import cfg, Fake, INPUT

XYZ = '6\nSynthetic water dimer\nO 0 0 0\nH 0 0 1\nH 0 1 0\nO 0 0 3\nH 0 0 4\nH 0 1 3\n'
FRAGMENTS = 'fragment,atoms\ndonor,1-3\nacceptor,4-6\n'


@pytest.fixture
def nci_cfg(cfg, tmp_path):
    study.init(cfg, 'smoke')
    cfg['programs']['multiwfn'] = str(tmp_path/'program/Multiwfn')
    return cfg


def prepare_nci(cfg, tmp_path, *, frames=1, csv_text=FRAGMENTS, **changes):
    xyz = tmp_path/'frames.xyz'
    xyz.write_text(XYZ*frames)
    fragments = tmp_path/'fragments.csv'
    fragments.write_text(csv_text)
    options=dict(study_name='smoke',template='multiwfn',input_path=xyz,tier='mini',
                 walltime='00:05:00',label='nci',analysis='igm',grid='medium',fragments=fragments,
                 method_basis='兜底方法：合成水二聚体验证')
    options.update(changes)
    m=attempt.prepare(cfg,**options)
    return attempt.find(cfg,m['attempt_id']),m


@pytest.mark.parametrize('frames',[1,3,50])
def test_prepare_outputs_and_hashes(nci_cfg,tmp_path,frames):
    path,m=prepare_nci(nci_cfg,tmp_path,frames=frames,grid='high')
    assert m['science']['n_frames']==frames
    files=attempt.verified_files(nci_cfg,path,m)
    assert files['ensemble.xyz']==(XYZ*frames).encode()
    outputs=remote.output_names(m)
    assert len(outputs)==2+frames*5
    assert f'frame-{frames:03d}-pair-01-02-atmdg.txt' in outputs
    assert f'frame-{frames:03d}-dg_inter.cub' in outputs
    assert not any(n.endswith(('.chk','.fchk')) for n in outputs)
    summary=attempt.summary(nci_cfg,m)
    assert '48.4 MB/frame' in summary and nci_report.NOTICE in summary
    assert 'O:1' in summary and '1-3' in summary
    assert subprocess.run(['sh','-n'],input=files['job.pbs'],capture_output=True).returncode==0


@pytest.mark.parametrize('count',[None,0,51,-1,True,'3',1.5])
def test_bad_manifest_frame_count(nci_cfg,tmp_path,count):
    _,m=prepare_nci(nci_cfg,tmp_path)
    if count is None:
        del m['science']['n_frames']
    else:
        m['science']['n_frames']=count
    with pytest.raises(ValueError,match='n_frames'):
        remote.output_names(m)


@pytest.mark.parametrize('csv_text',[
    'fragment,atoms\na,1-4\nb,4-6\n',
    'fragment,atoms\na,1-2\nb,4-6\n',
    'fragment,atoms\na,1\nb,2\nc,3\nd,4\ne,5-6\n',
    'fragment,atoms\na,1-3\nb,4-7\n',
    'fragment,atoms\na,"1,1,2,3"\nb,4-6\n',
    'fragment,atoms\na,"1-3; q"\nb,4-6\n',
    'fragment,atoms\na,1,2,3\nb,4-6\n',
])
def test_fragments_reject_overlap_coverage_count_injection(nci_cfg,tmp_path,csv_text):
    with pytest.raises(ValueError):
        prepare_nci(nci_cfg,tmp_path,csv_text=csv_text)
    assert not list((Path(nci_cfg['local']['studies_root'])/'smoke/attempts').glob('smoke-*'))


def test_ensemble_limits_and_identity(nci_cfg,tmp_path):
    with pytest.raises(ValueError,match='50'):
        prepare_nci(nci_cfg,tmp_path,frames=51)
    xyz=tmp_path/'bad.xyz'
    xyz.write_text(XYZ+XYZ.replace('O 0 0 3','N 0 0 3'))
    with pytest.raises(ValueError,match='identical'):
        prepare_nci(nci_cfg,tmp_path,input_path=xyz)
    xyz.write_text(XYZ.replace('H 0 0 4','H NaN 0 4'))
    with pytest.raises(ValueError):
        prepare_nci(nci_cfg,tmp_path,input_path=xyz)


@pytest.mark.parametrize('option,value',[('analysis','nci'),('grid','ultrafine'),('analysis',None),('grid',None)])
def test_parameter_allowlist(nci_cfg,tmp_path,option,value):
    with pytest.raises(ValueError):
        prepare_nci(nci_cfg,tmp_path,**{option:value})


def test_missing_parent_or_config_and_custom_script(nci_cfg,tmp_path):
    with pytest.raises(ValueError,match='parent-chk'):
        prepare_nci(nci_cfg,tmp_path,analysis='igmh',input_path=None)
    with pytest.raises(ValueError,match='custom'):
        prepare_nci(nci_cfg,tmp_path,params={'--menu':'evil'})
    del nci_cfg['programs']['multiwfn']
    with pytest.raises(ValueError,match='programs.multiwfn'):
        prepare_nci(nci_cfg,tmp_path)


def test_fragments_four_and_fixed_menus(nci_cfg,tmp_path):
    path,m=prepare_nci(nci_cfg,tmp_path,csv_text='fragment,atoms\na,1-2\nb,3\nc,4-5\nd,6\n')
    assert len(remote.output_names(m))==22
    menu=(path/'inputs/menu-02-04.inp').read_text()
    assert menu=='20\n10\n4\n1-2\n3\n4-5\n6\n2\n3\n6\n2,4\n2\nn\n0\n0\nq\n'
    (path/'inputs/menu-02-04.inp').write_text(menu+'20\n')
    with pytest.raises(ValueError,match='bundle'):
        attempt.verified_files(nci_cfg,path,m)


def test_old_output_names_unchanged():
    # Frozen pre-T92 results, including both optional modes and both schedulers.
    for scheduler in ('pbs','slurm'):
        for name,params,science,expected in [
            ('gaussian',{}, {},['molecule.log','job.pbs.out']),
            ('xtb',{}, {},['xtb.out','xtbopt.xyz','xtbopt.log','job.pbs.out']),
            ('xtb',{}, {'scan':{'steps':3}},['xtb.out','xtbscan.log','job.pbs.out']),
            ('crest',{}, {},['crest.out','crest_conformers.xyz','crest.energies','crest_best.xyz']),
            ('crest',{'--mdopt':''},{},['crest.out','crest_ensemble.xyz','ensemble_energies.log']),
        ]:
            m=dict(template=name,template_params=params,science=science,scheduler=scheduler,
                   inputs=[dict(name='molecule.gjf' if name=='gaussian' else 'molecule.xyz')])
            if scheduler=='slurm':
                expected=[n.replace('job.pbs.out','job.slurm.out') for n in expected]+['job.slurm.err']
            assert remote.output_names(m)==expected


@pytest.mark.parametrize('path',['relative/Multiwfn','~/a;touch x','/a/../Multiwfn','/a/$HOME','/a/$(id)','/a/`id`','~/a\nb','/a/"b'])
def test_program_path_rejects_shell(path):
    with pytest.raises(config.ConfigError):
        config.multiwfn_executable({'multiwfn':path})


def test_home_and_spaces_quoted(nci_cfg,tmp_path):
    nci_cfg['programs']['multiwfn']='~/tools with spaces/Multiwfn'
    path,m=prepare_nci(nci_cfg,tmp_path)
    assert 'multiwfn="$HOME/tools with spaces/Multiwfn"' in (path/'inputs/job.pbs').read_text()
    assert config.multiwfn_executable({'multiwfn':{'root':'~/tools'}})=='~/tools/Multiwfn'


def synthetic_parent(nci_cfg,tmp_path,monkeypatch):
    from ag import facts
    xyz=XYZ.splitlines()[2:]
    source=tmp_path/'parent.gjf'
    source.write_text('%nprocshared=4\n%mem=2GB\n%chk=dimer.chk\n# HF/STO-3G Opt Freq\n\nSynthetic\n\n0 1\n'+'\n'.join(xyz)+'\n\n')
    m=attempt.prepare(nci_cfg,study_name='smoke',template='gaussian',input_path=source,tier='mini',
                      walltime='00:05:00',label='parent',method_basis='兜底方法：合成测试')
    path=attempt.find(nci_cfg,m['attempt_id'])
    state.write(path,'submitting');submission.record(path,m,'42.fixture')
    state.write(path,'submitted',job_id=submission.qualified(m,'42.fixture'));state.write(path,'finished')
    (path/'outputs/parent.log').write_text('Synthetic normally terminated parent fixture')
    monkeypatch.setattr(facts,'parse_facts',lambda p: (dict(termination='normal',route='# HF/STO-3G Opt Freq',charge=0,multiplicity=1),{'final.xyz':XYZ}))
    return path,m


def test_igmh_parent_and_revalidation(nci_cfg,tmp_path,monkeypatch):
    parent,pm=synthetic_parent(nci_cfg,tmp_path,monkeypatch)
    path,m=prepare_nci(nci_cfg,tmp_path,analysis='igmh',input_path=None,
                       parents=[dict(attempt_id=parent.name,relation='nci_from')],parent_chk=parent.name+':dimer.chk')
    assert m['science']['n_frames']==1 and m['science']['nci']['parent']['route']=='# HF/STO-3G Opt Freq'
    files=attempt.verified_files(nci_cfg,path,m)
    assert b'formchk parent.chk parent.fchk' in files['job.pbs']
    assert b'cp ' not in files['job.pbs'] and b'rm ' not in files['job.pbs']
    assert files['menu-01-02.inp'].endswith(b'6\n3\nn\n0\n0\nq\n')
    (parent/'outputs/parent.log').write_text('Changed after prepare')
    with pytest.raises(ValueError,match='evidence changed'):
        attempt.verified_files(nci_cfg,path,m)


def test_igmh_requires_normal_parent_and_atom_count(nci_cfg,tmp_path,monkeypatch):
    parent,_=synthetic_parent(nci_cfg,tmp_path,monkeypatch)
    options=dict(analysis='igmh',input_path=None,parents=[dict(attempt_id=parent.name,relation='nci_from')],parent_chk=parent.name+':dimer.chk')
    from ag import facts
    monkeypatch.setattr(facts,'parse_facts',lambda p: (dict(termination='error'),{}))
    with pytest.raises(ValueError,match='normally terminated'):
        prepare_nci(nci_cfg,tmp_path,**options)
    monkeypatch.setattr(facts,'parse_facts',lambda p: (dict(termination='normal'),{'final.xyz':'1\nwrong\nO 0 0 0\n'}))
    with pytest.raises(ValueError,match='atom count'):
        prepare_nci(nci_cfg,tmp_path,**options)


@pytest.mark.parametrize('code,missing',[(0,False),(7,False),(0,True)])
def test_job_fake_program_receipts_no_overwrite(nci_cfg,tmp_path,code,missing):
    program=tmp_path/'program/Multiwfn'
    program.parent.mkdir()
    program.write_text('#!'+sys.executable+'\n'+
        'import pathlib,sys\nassert sys.argv[2:]==["-nt","4","-set","../multiwfn-settings.ini","-silent"]\n'+
        'assert sys.stdin.read().endswith("0\\n0\\nq\\n")\n'+
        f'for n in {[] if missing else ["atmdg.txt","IBSIW.txt","dg_inter.cub","sl2r.cub"]!r}:\n pathlib.Path(n).open("x").write("synthetic")\n'+
        f'print("Version 2026.10.1 (release date is the same as version name)")\nsys.exit({code})\n')
    program.chmod(0o700)
    path,m=prepare_nci(nci_cfg,tmp_path,frames=3)
    work=Path(remote.attempt_dir(nci_cfg,m))
    work.mkdir(parents=True)
    for p in (path/'inputs').iterdir():
        (work/p.name).write_bytes(p.read_bytes())
    # macOS realpath lacks GNU -e; match the existing Slurm template harness.
    if sys.platform == 'darwin':
        realpath = program.parent/'realpath'
        realpath.write_text('#!'+sys.executable+'\nimport pathlib,sys\nprint(pathlib.Path(sys.argv[-1]).resolve(strict=True))\n')
        realpath.chmod(0o700)
    env={**os.environ,'PATH':str(program.parent)+os.pathsep+os.environ['PATH'],
         'PBS_O_WORKDIR':str(work),'PBS_JOBID':'42.fixture'}
    result=subprocess.run(['sh',str(work/'job.pbs')],env=env,capture_output=True)
    expected=code or (43 if missing else 0)
    assert result.returncode==expected,result.stderr
    assert json.loads((work/'ag-exit.json').read_text())['returncode']==expected
    if expected==0:
        assert (work/'multiwfn.out').read_text().rstrip().endswith('AG_NCI_COMPLETE')
        assert all((work/n).is_file() for n in remote.output_names(m) if n!='job.pbs.out')
    else:
        assert 'AG_NCI_COMPLETE' not in (work/'multiwfn.out').read_text()
    before={p.relative_to(work):sha256(p.read_bytes()).hexdigest() for p in work.rglob('*') if p.is_file()}
    assert subprocess.run(['sh',str(work/'job.pbs')],env=env,capture_output=True).returncode!=0
    assert before=={p.relative_to(work):sha256(p.read_bytes()).hexdigest() for p in work.rglob('*') if p.is_file()}


def test_status_and_fetch_three_frames(nci_cfg,tmp_path):
    path,m=prepare_nci(nci_cfg,tmp_path,frames=3)
    names=remote.output_names(m)
    class NCIFake(Fake):
        def run(self,cmd):
            if cmd.operation=='output_observation':
                self.calls.append(cmd)
                return Result(stdout=''.join(f'{name} {len(self.files[name])} 2026-10-17 00:00:00 +0000\n' for name in names))
            if cmd.operation=='receipt':
                self.calls.append(cmd)
                return Result(stdout=json.dumps({'PBS_JOBID':'123.fixture','returncode':0,'finished_at':'2026-10-17T00:00:00Z'})+'\n' if 'ag-exit.json' in cmd.text else 'absent\n')
            return super().run(cmd)
    fake=NCIFake(nci_cfg)
    state.write(path,'submitting');submission.record(path,m,'123.fixture')
    state.write(path,'submitted',job_id=submission.qualified(m,'123.fixture'))
    for name in names: fake.files[name]=b'synthetic output'
    assert status.check(nci_cfg,path,fake)['state']=='finished'
    assert fetch.fetch(nci_cfg,path,fake)['files']==names
    assert {c.text for c in fake.calls if c.operation=='download'}==set(names)
    assert 'parent.fchk' not in {p.name for p in (path/'outputs').iterdir()}


def test_prepare_cli_and_old_inputs_still_required(nci_cfg,tmp_path,monkeypatch,capsys):
    prepare_nci(nci_cfg,tmp_path)
    monkeypatch.setattr(cli,'load_config',lambda:nci_cfg)
    assert cli.main(['prepare','--study','smoke','--template','multiwfn','--input',str(tmp_path/'frames.xyz'),
                     '--fragments',str(tmp_path/'fragments.csv'),'--analysis','igm','--grid','low',
                     '--tier','mini','--walltime','00:05:00','--label','cli','--method-basis','兜底方法：测试','--json'])==0
    assert json.loads(capsys.readouterr().out)['template']=='multiwfn'
    assert cli.main(['prepare','--study','smoke','--template','gaussian','--tier','mini',
                     '--walltime','00:05:00','--label','cli','--method-basis','兜底方法：测试'])==1
    assert '--input is required' in capsys.readouterr().err

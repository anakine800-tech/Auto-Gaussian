"""Synthetic release-format atmdg tables; no real research data."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from ag import cli,nci_report,state,submission
from test_multiwfn_template import cfg,nci_cfg,prepare_nci,XYZ

TABLE=''' Atomic delta-g indices of fragment  1 and percentage contributions
 Atom    1 :    0.600000  (  60.00 % )
 Atom    2 :    0.300000  (  30.00 % )
 Atom    3 :    0.100000  (  10.00 % )

 Atomic delta-g indices of fragment  2 and percentage contributions
 Atom    4 :    0.600000  (  60.00 % )
 Atom    5 :    0.300000  (  30.00 % )
 Atom    6 :    0.100000  (  10.00 % )

 Atomic pair delta-g indices and percentage contributions (zero terms are not shown)
    1    4 :    0.600000  (  60.00 % )
    2    5 :    0.300000  (  30.00 % )
    3    6 :    0.100000  (  10.00 % )

 Sum of all atomic pair delta-g indices:    1.000000
'''
LOG='''Multiwfn -- A Multifunctional Wavefunction Analyzer
Version 2026.10.1 (release date is the same as version name)
( Number of parallel threads:   4  Current date: 2026-10-17  Time: 00:00:00 )
AG_NCI_NORMAL_EXIT
'''
CUBE='''Synthetic cube\nNo research data\n6 0 0 0\n1 1 0 0\n1 0 1 0\n1 0 0 1\n8 8 0 0 0\n1 1 0 0 1.889726\n1 1 0 1.889726 0\n8 8 0 0 5.669178\n1 1 0 0 7.558904\n1 1 0 1.889726 5.669178\n1.0E-03\n'''


def fetched(nci_cfg,tmp_path,frames=1):
    path,m=prepare_nci(nci_cfg,tmp_path,frames=frames)
    state.write(path,'submitting');submission.record(path,m,'123.fixture')
    state.write(path,'submitted',job_id=submission.qualified(m,'123.fixture'))
    state.write(path,'finished',exit_status=0);state.write(path,'fetched')
    from ag.remote import output_names
    for name in output_names(m):
        data=TABLE if name.endswith('-atmdg.txt') else CUBE if name.endswith('.cub') else LOG if name.startswith('frame-') else 'AG_NCI_COMPLETE\n' if name=='multiwfn.out' else ''
        (path/'outputs'/name).write_text(data)
    return path,m


@pytest.mark.parametrize('frames',[1,3])
def test_report_hashes_atoms_totals_frames(nci_cfg,tmp_path,frames):
    path,m=fetched(nci_cfg,tmp_path,frames)
    result=nci_report.report(path)
    assert result['schema']=='ag-nci/1' and result['multiwfn_version']=='2026.10.1'
    assert len(result['frames'])==frames
    pair=result['frames'][0]['fragment_pairs'][0]
    assert pair['atom_pairs'][0]['elements']==['O','O']
    assert pair['total_delta_g']==1
    assert [v['delta_g'] for v in result['frames'][0]['fragment_totals']]==[1,1]
    assert all(len(r['sha256'])==64 for r in result['provenance']['outputs'])
    assert len(result['provenance']['inputs'])==len(m['inputs'])


@pytest.mark.parametrize('change',[
    lambda t:t.replace(' Sum of all atomic pair delta-g indices:    1.000000',''),
    lambda t:t.replace('0.600000','NaN',1),
    lambda t:t.replace('0.600000','0.800000',1),
    lambda t:t.replace('    1    4 :','    1    2 :'),
    lambda t:t.replace('    1.000000','    2.000000'),
    lambda t:t+'unexpected data\n',
    lambda t:t.replace(' Atom    1 :',' Atom    2 :'),
])
def test_table_rejects_malformed(nci_cfg,tmp_path,change):
    _,m=prepare_nci(nci_cfg,tmp_path)
    nci=m['science']['nci']
    with pytest.raises(ValueError):
        nci_report.parse_table(change(TABLE),nci['fragments'],nci['symbols'],1,2)


@pytest.mark.parametrize('name,content',[
    ('frame-001-pair-01-02-atmdg.txt',None),
    ('frame-001-pair-01-02.out',LOG.replace('AG_NCI_NORMAL_EXIT','')),
    ('frame-001-pair-01-02.out',LOG.replace('2026.10.1','2025.10.1')),
    ('frame-001-pair-01-02.out',LOG.replace('threads:   4','threads:   1')),
    ('multiwfn.out','partial'),
    ('frame-001-dg_inter.cub',CUBE.replace('1.0E-03','')),
    ('frame-001-sl2r.cub',CUBE.replace('6 0 0 0','6 1 0 0')),
])
def test_missing_or_bad_outputs(nci_cfg,tmp_path,name,content):
    path,_=fetched(nci_cfg,tmp_path)
    target=path/'outputs'/name
    if content is None: target.unlink()
    else: target.write_text(content)
    with pytest.raises(ValueError): nci_report.report(path)


def test_cli_local_only_exclusive_analyses(nci_cfg,tmp_path,monkeypatch,capsys):
    path,_=fetched(nci_cfg,tmp_path)
    out=path.parent.parent/'analyses/nci.json'
    monkeypatch.setattr(cli,'load_config',lambda *a,**kw:pytest.fail('No remote config for local Attempt'))
    monkeypatch.setattr('ag.transport.SSHTransport',lambda *a,**kw:pytest.fail('No remote transport'))
    args=['nci-report',str(path),'--out',str(out),'--json']
    assert cli.main(args)==0
    data=out.read_bytes()
    assert json.loads(capsys.readouterr().out)['schema']=='ag-nci/1'
    assert cli.main(args)==1
    assert out.read_bytes()==data
    assert cli.main(['nci-report',str(path),'--out',str(tmp_path/'escaped.json')])==1
    assert not (tmp_path/'escaped.json').exists()


def test_input_and_symlink_rejected(nci_cfg,tmp_path):
    path,_=fetched(nci_cfg,tmp_path)
    f=path/'inputs/fragments.csv'
    f.write_bytes(f.read_bytes()+b'\n')
    with pytest.raises(ValueError,match='hash'): nci_report.report(path)
    f.write_bytes(f.read_bytes()[:-1])
    output=path/'outputs/frame-001-pair-01-02-atmdg.txt'
    target=tmp_path/'outside.txt';target.write_text(TABLE)
    output.unlink();output.symlink_to(target)
    with pytest.raises(ValueError,match='Symbolic'): nci_report.report(path)



def test_wrong_igm_frame_rejected(nci_cfg, tmp_path):
    path, _ = fetched(nci_cfg, tmp_path)
    for name in ('dg_inter.cub', 'sl2r.cub'):
        (path/'outputs'/f'frame-001-{name}').write_text(CUBE.replace('7.558904', '8.558904'))
    with pytest.raises(ValueError, match='coordinates differ'):
        nci_report.report(path)


@pytest.mark.parametrize('count', [3, 4])
def test_all_fragment_pairs_aggregate(nci_cfg, tmp_path, count):
    csv_text = ('fragment,atoms\na,1-2\nb,3-4\nc,5-6\n' if count == 3 else
                'fragment,atoms\na,1-2\nb,3\nc,4-5\nd,6\n')
    path,m=prepare_nci(nci_cfg,tmp_path,csv_text=csv_text)
    state.write(path,'submitting');submission.record(path,m,'123.fixture')
    state.write(path,'submitted',job_id=submission.qualified(m,'123.fixture'))
    state.write(path,'finished',exit_status=0);state.write(path,'fetched')
    (path/'outputs/multiwfn.out').write_text('AG_NCI_COMPLETE\n')
    (path/'outputs/job.pbs.out').write_text('')
    for name in ('dg_inter.cub','sl2r.cub'):
        (path/'outputs'/f'frame-001-{name}').write_text(CUBE)
    fragments=m['science']['nci']['fragments']
    _,pairs=nci_report.layout(m)
    for left,right in pairs:
        a,b=fragments[left-1]['atoms'],fragments[right-1]['atoms']
        total=len(a)*len(b)
        lines=[]
        for index,atoms,other in ((left,a,b),(right,b,a)):
            lines.append(f' Atomic delta-g indices of fragment {index} and percentage contributions')
            lines.extend(f' Atom {i} : {len(other):.6f} ( {100/len(atoms):.2f} % )' for i in atoms)
        lines.append(' Atomic pair delta-g indices and percentage contributions (zero terms are not shown)')
        lines.extend(f' {i} {j} : 1.000000 ( {100/total:.2f} % )' for i in a for j in b)
        lines.append(f' Sum of all atomic pair delta-g indices: {total:.6f}')
        prefix=f'frame-001-pair-{left:02d}-{right:02d}'
        (path/'outputs'/f'{prefix}-atmdg.txt').write_text('\n'.join(lines)+'\n')
        (path/'outputs'/f'{prefix}-IBSIW.txt').write_text('Synthetic unused IBSIW')
        (path/'outputs'/f'{prefix}.out').write_text(LOG)
    result=nci_report.report(path)
    assert len(result['frames'][0]['fragment_pairs'])==len(pairs)
    assert [v['delta_g'] for v in result['frames'][0]['fragment_totals']]==[
        len(f['atoms'])*(6-len(f['atoms'])) for f in fragments]


def test_igmh_remote_hashes_bound_to_copy_journal(nci_cfg, tmp_path, monkeypatch):
    from ag import journal, remote
    from test_multiwfn_template import synthetic_parent
    parent, _ = synthetic_parent(nci_cfg, tmp_path, monkeypatch)
    path,m=prepare_nci(nci_cfg,tmp_path,analysis='igmh',input_path=None,
                       parents=[dict(attempt_id=parent.name,relation='nci_from')],parent_chk=parent.name+':dimer.chk')
    state.write(path,'submitting');submission.record(path,m,'123.fixture')
    state.write(path,'submitted',job_id=submission.qualified(m,'123.fixture'))
    state.write(path,'finished',exit_status=0);state.write(path,'fetched')
    for name in remote.output_names(m):
        data=(TABLE if name.endswith('-atmdg.txt') else CUBE if name.endswith('.cub') else
              LOG if name.startswith('frame-') else '')
        (path/'outputs'/name).write_text(data)
    log=path/'outputs/multiwfn.out'
    log.write_text('a'*64+'  parent.chk\n'+'b'*64+'  parent.fchk\nAG_NCI_COMPLETE\n')
    journal.append(path.parent.parent,'copy_parent_chk',path.name,'verified',{'sha256':'a'*64})
    result=nci_report.report(path)
    assert result['parent']['attempt_id']==parent.name
    assert result['provenance']['remote_inputs']['parent.fchk']==dict(sha256='b'*64,source='multiwfn.out',fetched=False)
    log.write_text(log.read_text().replace('a'*64,'c'*64))
    with pytest.raises(ValueError,match='verified parent copy'):
        nci_report.report(path)

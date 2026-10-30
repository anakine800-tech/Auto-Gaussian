"""T188 synthetic acceptance and containment cases; never execute Gaussian."""
import pytest

from ag import gaussian_input, gaussian_relaxed as relaxed

WATER = 'O 0 0 0\nH 0 0 1\nH 0 1 0'


def job(route='# HF/STO-3G SP', tail='', *, chk='water.chk', state='0 1', geometry=WATER):
    return (f'%nprocshared=8\n%mem=10GB\n%chk={chk}\n{route}\n\nWater\n\n{state}\n{geometry}\n\n' + tail).encode()


def check(data, **kwargs):
    return relaxed.validate(data, cores=8, mem_gb=12, **kwargs)


def chain(*parts):
    return b'\n--Link1--\n'.join(parts)


def allcheck(chk='water.chk', route='# HF/STO-3G Geom=AllCheck SP'):
    return f'%nprocshared=8\n%mem=10GB\n%chk={chk}\n{route}\n\n'.encode()


@pytest.mark.parametrize('route,tail,feature', [
    ('# HF/Gen SP', 'O H 0\nSTO-3G\n****\n', 'general_basis_semantics'),
    ('# HF/STO-3G SCRF=(PCM,Read)', 'eps=20.5\nepsinf=2.0\n', 'scrf_read_semantics'),
    ('# HF/STO-3G Pop=NBORead', '$NBO NPA BNDIDX $END\n', 'nbo_section_semantics'),
    ('# HF/STO-3G Opt=(TS,CalcFC,ModRedundant)', 'B 1 2 F\n', 'modredundant_semantics'),
    ('# HF/STO-3G Opt=ModRedundant', 'B 1 2 S 200 0.01\nB 1 3 S 200 0.01\nA 2 1 3 S 200 1.0\n', 'modredundant_semantics'),
    ('# HF/STO-3G Opt=ModRedundant', 'B * * F\nX 1 F\n', 'modredundant_semantics'),
    ('# HF/Gen Opt=ModRedundant Units=Bohr SCRF=(PCM,Read) Pop=NBORead',
     'B 1 2 S 200 0.01\n\nO H 0\nSTO-3G\n****\n\neps=20.5\n\n$NBO NPA $END\n', 'coordinate_unit_semantics'),
])
def test_all_w7_additional_classes_accept_real_data(route, tail, feature):
    data = job(route, tail)
    science, marker = check(data)
    assert science['geometry'] == WATER and science['charge'] == 0
    assert marker['mode'] == 'relaxed' and marker['method_verified'] is False
    assert feature in marker['skipped_checks']
    assert science['sections'][0]['resources'] == dict(cores=8, mem_gb=10, source='explicit')
    assert data == job(route, tail)  # no correction or resource insertion


def test_link1_check_and_allcheck_sources_and_unknown_fields():
    second = job('# HF/STO-3G Geom=Check SP', geometry='').replace(b'0 1\n\n\n', b'0 1\n\n')
    science, marker = check(chain(job(), second, allcheck()))
    assert len(science['sections']) == 3
    a, b, c = science['sections']
    assert b['geometry'] is None and b['n_atoms'] is None
    assert b['charge'] == 0 and b['multiplicity'] == 1
    assert b['geometry_source'] == dict(kind='earlier_section', section=1, filename='water.chk')
    assert c['charge'] is c['multiplicity'] is c['geometry'] is None
    assert c['geometry_source']['section'] == 2
    assert marker['skipped_checks'] == ['checkpoint_geometry_science', 'link1_scientific_consistency', 'scientific_method']
    assert science['route'].count('--Link1--') == 2


def test_parent_checkpoint_allcheck_never_invents_science():
    data = b'%oldchk=parent.chk\n' + allcheck('child.chk')
    science, marker = check(data, parent_chk=dict(target_name='parent.chk', attempt_id='sample-001'))
    assert science['geometry'] is science['charge'] is science['multiplicity'] is science['n_atoms'] is None
    assert science['geometry_source'] == dict(kind='parent_chk', attempt_id='sample-001', filename='parent.chk')
    assert 'checkpoint_geometry_science' in marker['skipped_checks']


def test_safe_recursive_explicit_includes_are_bound_and_checked():
    data = job('# HF/Gen SP', '@basis.inc\n')
    attachments = {'basis.inc': b'O H 0\n@sto.inc\n****\n', 'sto.inc': b'STO-3G\n'}  # scan-public: allow synthetic Gaussian include, not an email
    science, marker = check(data, attachments=attachments)
    assert science['n_atoms'] == 3 and 'general_basis_semantics' in marker['skipped_checks']
    assert data.endswith(b'@basis.inc\n') and attachments['sto.inc'] == b'STO-3G\n'


@pytest.mark.parametrize('memory', ['10GB', '10000MB', '1250MW', '1GW'])
def test_existing_memory_units_and_85_percent_rule(memory):
    science, _ = check(job().replace(b'10GB', memory.encode()))
    assert 0 < science['sections'][0]['resources']['mem_gb'] <= 10.2


@pytest.mark.parametrize('section', [0, 1, 2])
@pytest.mark.parametrize('bad', [
    b'%nprocshared=9', b'%nprocshared=8\n%nprocshared=8', b'%nprocshared=',
    b'%nprocshared=8\n%mem=11GB', b'%nprocshared=8\n%rwf=job.pbs',
    b'%nprocshared=8\n%subst=l1.exe=bad', b'%nprocshared=8\n%oldchk=foreign.chk',
])
def test_resources_and_link0_checked_in_every_segment(section, bad):
    parts = [job(), job(), job()]
    parts[section] = parts[section].replace(b'%nprocshared=8', bad)
    with pytest.raises(ValueError):
        check(chain(*parts))


@pytest.mark.parametrize('section', [0, 1, 2])
@pytest.mark.parametrize('removed', [b'%nprocshared=8\n', b'%mem=10GB\n'])
def test_implicit_resource_inheritance_is_not_guessed(section, removed):
    parts = [job(), job(), job()]
    parts[section] = parts[section].replace(removed, b'')
    with pytest.raises(ValueError, match='explicit'):
        check(chain(*parts))


@pytest.mark.parametrize('route', [
    '# HF/STO-3G External=command', '# HF/STO-3G ExTeRnAl(command)',
    '# HF/STO-3G Exter\nnal=(command)', '# HF/STO-3G External\n=(command)',
    '# HF/STO-3G Output=WFN', '# HF/STO-3G Density=Read',
    '# HF/STO-3G Pop=NBO7Read', '# HF/STO-3G IOp(1/8=1)',
    '# HF/STO-3G Opt=Restart', '# HF/STO-3G IRC=RCFC',
    '# HF/STO-3G Freq=ReadFC', '# HF/STO-3G IRC=ReadCartesianFC',
    '# HF/STO-3G ExtraOverlay', '# HF/STO-3G ExtraBasis',
    '# HF/STO-3G Guess=Read', '# HF/STO-3G Guess=(Read,Only)',
])
def test_command_and_unknown_reader_routes_refused(route):
    with pytest.raises(ValueError):
        check(chain(job(), job(), job(route, chk='fresh.chk')))


@pytest.mark.parametrize('name', ['../water.chk', '/water.chk', r'folder\water.chk',
                                 '$HOME.chk', 'job.pbs', 'parent.chk'])
def test_unsafe_or_protected_checkpoint_names(name):
    with pytest.raises(ValueError):
        check(job(chk=name))


def test_plain_double_dot_names_are_not_parent_path_components():
    data = job('# HF/Gen SP', '@a..basis.inc\n', chk='water..chk')
    science, marker = check(data, input_name='water..gjf',
                            attachments={'a..basis.inc': b'O H 0\nSTO-3G\n****\n'})
    assert science['geometry'] == WATER and marker['method_verified'] is False


@pytest.mark.parametrize('option', ['Units=UnverifiedUnit', 'EmpiricalDispersion=UnverifiedModel',
                                  'EM=UnverifiedModel'])
def test_scientific_option_values_remain_unverified_not_selected(option):
    # Parser acceptance deliberately does not certify these synthetic choices.
    science, marker = check(job('# HF/STO-3G SP ' + option))
    assert option in science['route'] and marker['method_verified'] is False
    assert 'scientific_method' in marker['skipped_checks']
    if option.startswith('Units='):
        assert 'coordinate_unit_semantics' in marker['skipped_checks']


def test_newton_is_not_a_file_or_execution_directive():
    # Synthetic basis label: data acceptance does not endorse a basis definition.
    science, marker = check(job('# HF/Gen SP', 'O H 0\nNewton\n****\n'))
    assert science['geometry'] == WATER and marker['method_verified'] is False


@pytest.mark.parametrize('option', [
    'Stable=(RepOpt,Int)', 'Stable=(AO,NoOpt)',
    'Symmetry=(PG=C2v,Follow,Int,NoSCF)',
    'Symmetry=(PrintOrientation,SaveOrientation)',
    'Polar=(Cubic,EnOnly,FourPoint,Step=10)', 'Polar=OptRot',
    'Polar=(Susceptibility,NoWorkerPerturbations)', 'Freq=Raman',
])
def test_scientific_stable_polar_symmetry_choices_do_not_require_value_allowlist(option):
    science, marker = check(job('# HF/STO-3G ' + option))
    assert option in science['route'] and marker['method_verified'] is False


@pytest.mark.parametrize('option', [
    'Stable=Restart', 'Stable=Rest', 'Polar=Restart', 'Polar=Rest',
    'Polar=Raman', 'Polar=Ram', 'Polar=ROA', 'Polar=RO',
    'Polar=DCSHG', 'Polar=DCS', 'Polar=Gamma', 'Polar=Gam',
    'Polar=WorkerPerturbations', 'Polar=Worker',
    'Stable=(Opt Rest)', 'Polar(Numer\tRama)', 'Polar=(Cubic,\nGamm)',
])
def test_implicit_checkpoint_frequency_and_worker_options_remain_refused(option):
    # Even a known earlier geometry checkpoint does not prove Hessian/frequency
    # provenance or authorize a different parallel worker model.
    with pytest.raises(ValueError):
        check(chain(job(), job(), job('# HF/STO-3G ' + option)))


@pytest.mark.parametrize('tail', ['FILE=job.pbs', 'Output=job.pbs', 'job.pbs',
                                  '$NBO FILE=foo $END', '$NBO ARCHIVE $END',
                                  '$NBO EXTERNAL=foo $END', '$NBO NPA $END\n%chk=foo.chk',
                                  '@../basis.inc', '@basis.inc/1', r'@folder\basis.inc'])
def test_additional_sections_cannot_select_files_or_commands(tail):
    with pytest.raises(ValueError):
        check(job('# HF/Gen Pop=NBORead SCRF=Read', tail))


@pytest.mark.parametrize('attachments', [
    {}, {'basis.inc': b'@missing.inc\n'}, {'basis.inc': b'@basis.inc\n'},
    {'basis.inc': b'@nested.inc\n', 'nested.inc': b'@basis.inc\n'},
    {'basis.inc': b'STO-3G\n', 'unused.inc': b'STO-3G\n'},
    {'basis.inc': b'STO-3G\n', 'BASIS.INC': b'STO-3G\n'},
    {'basis.inc': b'%nprocshared=99\n'}, {'basis.inc': b'# HF/STO-3G\n'},
    {'basis.inc': b'--Link1--\n'}, {'basis.inc': b'$NBO FILE=job.pbs $END\n'},
    {'basis.inc': b'Exter\nnal=foo\n'}, {'basis.inc': b'@../bad.inc\n'},
])
def test_missing_recursive_alias_and_embedded_dangerous_includes(attachments):
    with pytest.raises(ValueError):
        check(job('# HF/Gen SP', '@basis.inc\n'), attachments=attachments)


def test_include_depth_and_expansion_are_bounded():
    attachments = {f'b{i}.inc': f'@b{i + 1}.inc\n'.encode() for i in range(relaxed.MAX_INCLUDE_DEPTH + 1)}
    attachments[f'b{relaxed.MAX_INCLUDE_DEPTH + 1}.inc'] = b'STO-3G\n'
    with pytest.raises(ValueError, match='depth'):
        check(job('# HF/Gen SP', '@b0.inc\n'), attachments=attachments)
    with pytest.raises(ValueError, match='byte bound'):
        check(job('# HF/Gen SP', '@basis.inc\n' * 100), attachments={'basis.inc': b'O H 0\n' * 20000})


@pytest.mark.parametrize('data', [b'', b'\x00', chain(job(), b''), chain(b'', job()), chain(job(), b'', job())])
def test_empty_and_malformed_sections_rejected(data):
    with pytest.raises(ValueError):
        check(data)


def test_checkpoint_source_must_be_proven_before_read():
    with pytest.raises(ValueError, match='proven'):
        check(allcheck())
    with pytest.raises(ValueError, match='proven'):
        check(b'%oldchk=foreign.chk\n' + allcheck('child.chk'))
    with pytest.raises(ValueError, match='distinct'):
        check(chain(job(), b'%oldchk=water.chk\n' + allcheck()))
    with pytest.raises(ValueError, match='consumed'):
        check(job(), parent_chk=dict(attempt_id='sample-001', target_name='parent.chk'))


def test_old_strict_parser_unchanged_and_relaxed_always_unverified():
    data = job()
    strict = gaussian_input.validate(data.decode(), 8, 12)
    science, marker = check(data)
    assert strict['geometry'] == science['geometry'] and strict['route'] == science['route']
    assert marker == dict(mode='relaxed', skipped_checks=['scientific_method'], method_verified=False)
    with pytest.raises(ValueError):
        gaussian_input.validate(job('# HF/Gen SP', 'O H 0\nSTO-3G\n****\n').decode(), 8, 12)


def test_combined_checkpoint_readers_require_proven_source():
    for route in ('# HF/STO-3G Guess=(Read,Mix)', '# HF/STO-3G Density=(Checkpoint,SCF)'):
        with pytest.raises(ValueError, match='proven'):
            check(job(route))
        science, _ = check(chain(job(), job(route)))
        assert len(science['sections']) == 2


@pytest.mark.parametrize('name', ['job.pbs.out', 'job.slurm.out', 'job.slurm.err', 'scratch', 'input-validation.json'])
def test_reserved_attachment_output_and_scratch_names(name):
    with pytest.raises(ValueError, match='reserved'):
        check(job('# HF/Gen', '@' + name + '\n'), attachments={name: b'STO-3G\n'})


def test_explicit_basis_shells_and_ecp_data_acceptance():
    text = job('# HF/GenECP SP',
               'H 0\nSTO-3G\n****\nCl 0\nLANL2DZ\n****\n\nCl 0\nLANL2DZ\n',
               geometry='Cl 0 0 0\nH 0 0 1.2')
    science, marker = check(text)
    assert science['n_atoms'] == 2 and science['multiplicity'] == 1
    assert 'general_basis_semantics' in marker['skipped_checks'] and 'ecp_semantics' in marker['skipped_checks']


@pytest.mark.parametrize('bad', [[], {'target_name': 'parent.chk'}, {'attempt_id': '', 'target_name': 'parent.chk'}])
def test_invalid_parent_records_reject_without_fabricated_source(bad):
    with pytest.raises(ValueError, match='parent checkpoint'):
        check(b'%oldchk=parent.chk\n' + allcheck('child.chk'), parent_chk=bad)


@pytest.mark.parametrize('value', [[], (), 'basis.inc'])
def test_attachment_container_must_be_explicit_dictionary(value):
    with pytest.raises(ValueError, match='attachments'):
        check(job(), attachments=value)


def test_limits_and_nontext_attachments():
    with pytest.raises(ValueError, match='bound'):
        check(job() + b' ' * relaxed.MAX_BYTES)
    with pytest.raises(ValueError, match='too many'):
        check(chain(*[job() for _ in range(relaxed.MAX_SECTIONS + 1)]))
    with pytest.raises(ValueError, match='UTF-8'):
        check(job('# HF/Gen', '@basis.inc\n'), attachments={'basis.inc': b'\xff'})
    with pytest.raises(ValueError, match='Too many'):
        check(job(), attachments={f'b{i}.inc': b'STO-3G\n' for i in range(relaxed.MAX_ATTACHMENTS + 1)})


@pytest.mark.parametrize('route', ['# ../Gen SP', '# HF/STO-3G SCRF=(PCM,File=foo)',
                                  '# HF/STO-3G SCRF=(PCM,UnknownReader)',
                                  '# HF/STO-3G Opt=(TS,ReadFC)', '# HF/STO-3G Freq=ReadFCHT'])
def test_unreviewed_file_and_method_path_options_rejected(route):
    with pytest.raises(ValueError):
        check(job(route))


def test_explicit_general_basis_shell_data_acceptance():
    text = job('# HF/Gen SP', 'H 0\nS 1 1.00\n1.0 1.0\n****\n',
               geometry='H 0 0 0\nH 0 0 0.7')
    science, marker = check(text)
    assert science['n_atoms'] == 2 and 'general_basis_semantics' in marker['skipped_checks']


@pytest.mark.parametrize('route,tail,skipped', [
    ('# HF/STO-3G Pop=NBO', '', False),
    ('# HF/STO-3G Pop=(NBORead,Full)', '$NBO NPA $END\n', True),
])
def test_nbo_skip_describes_only_the_additional_section_reader(route, tail, skipped):
    _, marker = check(job(route, tail))
    assert ('nbo_section_semantics' in marker['skipped_checks']) is skipped

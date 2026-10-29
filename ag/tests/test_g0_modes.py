"""Synthetic geometry, derivative checks and real cclib parsing; no research."""
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pytest

from ag import g0_mapping, _parse_outputs, g0, g0_modes as gm


XYZ = np.array([[0., 0., 0.], [1., 0., 0.], [2.6, 0., 0.]])
ELEMENTS = ['O', 'H', 'O']
TRANSFER = np.array([[0., 0., 0.], [1., 0., 0.], [0., 0., 0.]])
SPECS = [dict(kind='distance', atoms=[1, 2], role='breaking', label='O1-H'),
         dict(kind='distance', atoms=[2, 3], role='forming', label='H-O2')]
FIXTURE = Path(__file__).parent / 'fixtures/g0_modes_synthetic.log'


def analyze(vectors=None, frequencies=None, specs=None, xyz=XYZ):
    return gm.analyze_modes(ELEMENTS, xyz, [-100] if frequencies is None else frequencies,
                            [TRANSFER] if vectors is None else vectors,
                            SPECS if specs is None else specs)


def test_shared_hydrogen_projections_do_not_cancel():
    report = analyze()
    mode = report['modes'][0]
    assert [d['value'] for d in mode['delta']] == [1, -1]
    assert [d['matches'] for d in mode['delta']] == [True, True]
    assert mode['consistent_count'] == mode['signed_count'] == 2
    assert mode['overlap'] == pytest.approx(2 / np.sqrt(6))
    assert report['best_mode'] == 1 and report['flags'] == []
    # The discarded unsigned per-atom sum cancels the shared H contribution.
    naive_sum = sum(gm.wilson_row(XYZ, spec) for spec in SPECS)
    assert np.array_equal(naive_sum[1], [0, 0, 0])
    assert np.sum(naive_sum * TRANSFER) == 0


@pytest.mark.parametrize('scale', [-1, -7, -1e-200, 1e200])
def test_global_sign_and_scale_are_arbitrary(scale):
    original, changed = analyze()['modes'][0], analyze([scale * TRANSFER])['modes'][0]
    assert changed['sigma'] == (1 if scale > 0 else -1)
    assert changed['consistent_count'] == original['consistent_count']
    assert changed['overlap'] == original['overlap']
    assert [d['corrected_value'] for d in changed['delta']] == [1, -1]


def test_all_imaginary_modes_and_lowest_three_reference_modes():
    transverse = np.roll(TRANSFER, 1, axis=1)
    report = analyze([TRANSFER, TRANSFER, transverse, TRANSFER, TRANSFER, TRANSFER],
                     [50, -100, -300, 20, 100, 80])
    assert [m['index'] for m in report['modes']] == [3, 2, 4, 1, 6]
    assert report['best_mode'] == 2
    assert set(report['flags']) == {'multiple_imaginary_modes', 'most_negative_not_best'}
    # Real modes cannot rescue an inconsistent imaginary mode.
    report = analyze([transverse, TRANSFER], [-300, 20])
    assert report['best_mode'] == 1
    assert report['flags'] == ['sign_inconsistent']


def test_no_imaginary_modes_reports_references_only():
    report = analyze([TRANSFER] * 5, [90, 30, 60, 0, 80])
    assert report['best_mode'] is None and report['flags'] == ['no_imaginary_mode']
    assert [m['frequency_cm1'] for m in report['modes']] == [0, 30, 60]


def test_zero_tolerance_is_not_a_match_or_mismatch():
    q = TRANSFER.copy()
    q[1] = [0.0009, np.sqrt(1 - 0.0009**2), 0]
    mode = analyze([q])['modes'][0]
    assert mode['consistent_count'] == 0 and mode['signed_count'] == 2
    for delta in mode['delta']:
        assert delta['near_zero'] and delta['matches'] is None and delta['corrected_sign'] is None
        assert delta['zero_tolerance'] == 1e-3
    q[1] = [0.0011, np.sqrt(1 - 0.0011**2), 0]
    assert analyze([q])['modes'][0]['consistent_count'] == 2


def test_sigma_tiebreak_uses_signed_sum_then_positive_sign():
    # Both coordinates declared breaking: one match per sign; first stretches more.
    specs = [SPECS[0], dict(SPECS[1], role='breaking')]
    q = TRANSFER.copy()
    q[2, 0] = 0.5
    positive = analyze([q], specs=specs)['modes'][0]
    negative = analyze([-q], specs=specs)['modes'][0]
    assert positive['sigma'] == 1 and negative['sigma'] == -1
    assert positive['consistent_count'] == negative['consistent_count'] == 1
    exact = analyze(specs=specs)['modes'][0]
    assert exact['sigma'] == 1  # sum is exactly zero


def test_best_mode_breaks_count_tie_by_overlap():
    q = TRANSFER.copy()
    q[1] = [0.5, np.sqrt(0.75), 0]
    report = analyze([q, TRANSFER], [-200, -100])
    assert report['best_mode'] == 2


def test_sigma_prefers_count_over_magnitude():
    # Two small extensions versus one large shortening: count takes priority.
    xyz = [[0, 0, 0], [2, 0, 0], [5, 0, 0], [9, 0, 0]]
    vectors = [[[0, 0, 0], [0.1, 0, 0], [0.2, 0, 0], [-1, 0, 0]]]
    specs = [dict(kind='distance', atoms=[i, i + 1], role='breaking') for i in (1, 2, 3)]
    mode = gm.analyze_modes(['H'] * 4, xyz, [-100], vectors, specs)['modes'][0]
    assert mode['sigma'] == 1 and mode['consistent_count'] == 2
    assert sum(d['value'] for d in mode['delta']) < 0


@pytest.mark.parametrize('role,expected,sigma,count', [
    ('increasing', 1, 1, 1), ('decreasing', -1, -1, 1), ('report', None, 1, 0)])
def test_angle_roles_and_degrees(role, expected, sigma, count):
    xyz = [[1, 0, 0], [0, 0, 0], [0, 1, 0]]
    q = [[0, -1, 0], [0, 0, 0], [0, 0, 0]]
    spec = dict(kind='angle', atoms=[1, 2, 3], role=role)
    report = analyze([q], specs=[spec], xyz=xyz)
    mode = report['modes'][0]
    delta = mode['delta'][0]
    assert mode['sigma'] == sigma and mode['consistent_count'] == count
    assert mode['signed_count'] == count
    assert delta['value'] == pytest.approx(1)
    assert delta['degrees'] == pytest.approx(180 / np.pi)
    assert delta['expected_sign'] == expected and delta['unit'] == 'radian'
    assert delta['matches'] is (True if expected else None)
    assert delta['zero_tolerance'] == 1e-3
    if role == 'report':
        assert mode['overlap'] == 0 and report['flags'] == []


@pytest.mark.parametrize('spec', [SPECS[0], dict(kind='angle', atoms=[1, 2, 3], role='report')])
def test_wilson_derivative_by_finite_differences(spec):
    xyz = np.array([[0.4, 1.1, -0.2], [0.1, -0.3, 0.2], [1.6, 0.4, 0.8]])
    def internal(points):
        if spec['kind'] == 'distance':
            return np.linalg.norm(points[0] - points[1])
        u, v = points[0] - points[1], points[2] - points[1]
        return np.arccos(np.dot(u, v) / np.linalg.norm(u) / np.linalg.norm(v))
    numerical = np.zeros_like(xyz)
    step = 1e-6
    for i in range(3):
        for j in range(3):
            offset = np.zeros_like(xyz)
            offset[i, j] = step
            numerical[i, j] = (internal(xyz + offset) - internal(xyz - offset)) / (2 * step)
    analytic = gm.wilson_row(xyz, spec)
    assert np.allclose(analytic, numerical, atol=1e-9, rtol=0)
    assert np.allclose(analytic.sum(axis=0), 0, atol=1e-15)


@pytest.mark.parametrize('xyz', [XYZ, [[1, 0, 0], [0, 0, 0], [2, 1e-8, 0]],
                               [[1, 0, 0], [0, 0, 0], [-2, 1e-8, 0]]])
def test_degenerate_angle_errors(xyz):
    with pytest.raises(ValueError, match='角度坐标退化'):
        gm.wilson_row(xyz, dict(kind='angle', atoms=[1, 2, 3], role='report'))


@pytest.mark.parametrize('spec', [
    dict(kind='distance', atoms=[1, 4], role='breaking'),
    dict(kind='distance', atoms=[1, 1], role='breaking'),
    dict(kind='distance', atoms=[0, 2], role='breaking'),
    dict(kind='distance', atoms=[True, 2], role='breaking'),
    dict(kind='distance', atoms=[1., 2], role='breaking'),
    dict(kind='distance', atoms=[1, 2, 3], role='breaking'),
    dict(kind='angle', atoms=[1, 2], role='report'),
    dict(kind='angle', atoms=[1, 2, 3], role='forming'),
    dict(kind='distance', atoms=[1, 2], role='report'),
    dict(kind='dihedral', atoms=[1, 2, 3], role='report'),
    dict(kind=[], atoms=[1, 2], role='breaking'),
    dict(SPECS[0], label=None), dict(SPECS[0], unexpected=True), None])
def test_invalid_coordinates(spec):
    with pytest.raises(ValueError):
        analyze(specs=[spec])


@pytest.mark.parametrize('changes', [dict(frequencies=[]), dict(frequencies=[float('nan')]),
    dict(displacements=[np.zeros((3, 3))]), dict(displacements=[[[1, 0, 0]]]),
    dict(displacements=[np.full((3, 3), float('inf'))]), dict(coordinates=np.zeros((3, 3))),
    dict(coordinates_spec=[])])
def test_invalid_data(changes):
    with pytest.raises(ValueError):
        gm.analyze_modes(**(dict(elements=ELEMENTS, coordinates=XYZ, frequencies=[-100],
                                displacements=[TRANSFER], coordinates_spec=SPECS) | changes))


@pytest.fixture
def fetched(tmp_path):
    root = tmp_path / 'synthetic-study'
    path = root / 'attempts' / 'synthetic-001-freq'
    (path / 'outputs').mkdir(parents=True)
    (root / 'analyses').mkdir()
    manifest = dict(attempt_id=path.name, study_id=root.name, template='gaussian', inputs=[dict(name='job.gjf')])
    (path / 'manifest.json').write_text(json.dumps(manifest))
    (path / 'status.json').write_text(json.dumps(dict(state='fetched', job_id='1.example')))
    (path / 'outputs/job.log').write_bytes(FIXTURE.read_bytes())
    write_facts(path)
    return root, path


def write_facts(path):
    facts, _ = _parse_outputs.parse_gaussian(path / 'outputs/job.log')
    facts['schema'] = 'ag-facts/1'
    (path / 'facts.json').write_text(json.dumps(facts))
    return facts


def mapped_candidate(elements, coordinates, frequency, specs, permutation=None):
    permutation = permutation or list(range(1, len(elements) + 1))
    # Synthetic caller supplies a complete binding through the same validator.
    target = dict(kind='frequency', attempt=frequency['attempt'], source=frequency['source'])
    config = dict(sha256='a' * 64, entries=[dict(object='synthetic', candidate='guess',
        candidate_sha256='b' * 64, target=target, candidate_to_target=permutation)])
    correspondence = g0_mapping.resolve(config, 'synthetic', dict(id='guess', sha256='b' * 64),
                                        elements, {'frequency': (target, frequency['elements'])})['frequency']
    return gm.analyze_candidate(elements, coordinates, frequency, specs, correspondence=correspondence)


def test_same_element_swap_requires_declaration_and_maps_only_indices(fetched):
    root, path = fetched
    frequency = gm.read_frequency_attempt(root, path.name)
    before_xyz, before_vectors = frequency['coordinates'].copy(), frequency['displacements'].copy()
    swapped = XYZ[[2, 1, 0]]
    candidate_specs = [dict(s, atoms=[4 - i for i in s['atoms']]) for s in SPECS]
    unavailable = gm.analyze_candidate(ELEMENTS, swapped, frequency, candidate_specs)
    assert unavailable['element_sequence_equal'] and not unavailable['available']
    assert unavailable['atom_correspondence']['status'] == 'unverified'
    assert 'modes' not in unavailable and '缺少' in unavailable['reason']
    expected = mapped_candidate(ELEMENTS, XYZ, frequency, SPECS)
    actual = mapped_candidate(ELEMENTS, swapped, frequency, candidate_specs, [3, 2, 1])
    assert actual['best_mode'] == expected['best_mode']
    for mode, control in zip(actual['modes'], expected['modes']):
        assert mode['overlap'] == pytest.approx(control['overlap'])
        assert mode['consistent_count'] == control['consistent_count']
        for delta, original, spec in zip(mode['delta'], control['delta'], candidate_specs):
            assert delta['atoms'] == original['atoms']
            assert delta['candidate_atoms'] == spec['atoms']
            assert delta['value'] == pytest.approx(original['value'])
    assert actual['aligned_rmsd_angstrom'] == pytest.approx(0)
    assert np.array_equal(before_xyz, frequency['coordinates'])
    assert np.array_equal(before_vectors, frequency['displacements'])


def test_angle_indices_map_without_changing_frequency_frame():
    xyz = np.array([[0., 1., 0.], [0., 0., 0.], [1., 0., 0.]])
    frequency = dict(elements=['H', 'O', 'H'], coordinates=xyz, frequencies=[-100.],
                     displacements=[[[1., 0., 0.], [0., 0., 0.], [0., 1., 0.]]],
                     attempt='synthetic', orientation='standard', stationarity='stationary',
                     geometry_sha256='a' * 64, source={})
    spec = dict(kind='angle', atoms=[1, 2, 3], role='increasing')
    original = mapped_candidate(frequency['elements'], xyz, frequency, [spec])
    mapped = mapped_candidate(['O', 'H', 'H'], xyz[[1, 0, 2]], frequency,
                              [dict(spec, atoms=[2, 1, 3])], [2, 1, 3])
    assert mapped['modes'][0]['delta'][0]['value'] == pytest.approx(original['modes'][0]['delta'][0]['value'])
    assert mapped['modes'][0]['delta'][0]['candidate_atoms'] == [2, 1, 3]
    assert mapped['modes'][0]['delta'][0]['atoms'] == [1, 2, 3]


def test_retrieved_frequency_end_to_end_and_read_only(fetched):
    root, path = fetched
    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    frequency = gm.read_frequency_attempt(root, path.name)
    assert frequency['orientation'] == 'standard'
    assert frequency['elements'] == ELEMENTS
    assert np.array_equal(frequency['coordinates'], XYZ)
    assert frequency['stationarity'] == 'non_stationary'
    report = mapped_candidate(ELEMENTS, XYZ, frequency, SPECS)
    assert report['best_mode'] == 2
    assert set(report['flags']) == {'multiple_imaginary_modes', 'most_negative_not_best',
                                    'non_stationary_frequencies'}
    assert report['aligned_rmsd_angstrom'] == pytest.approx(0)
    assert report['source']['log_sha256'] == sha256(FIXTURE.read_bytes()).hexdigest()
    assert len(report['geometry_sha256']) == 64
    json.dumps(report, allow_nan=False)
    assert before == {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_optimized_candidate_difference_is_only_rmsd(fetched):
    root, path = fetched
    frequency = gm.read_frequency_attempt(root, path.name)
    before = frequency['displacements'].copy()
    candidate = XYZ.copy()
    candidate[1, 0] += 0.3
    changed = mapped_candidate(ELEMENTS, candidate, frequency, SPECS)
    original = mapped_candidate(ELEMENTS, XYZ, frequency, SPECS)
    assert changed['aligned_rmsd_angstrom'] > 0.1
    assert changed['modes'] == original['modes']
    assert np.array_equal(before, frequency['displacements'])
    with pytest.raises(ValueError, match='elements disagree'):
        mapped_candidate(['O', 'O', 'H'], XYZ, frequency, SPECS)


def test_rmsd_never_uses_reflection_or_remapping():
    xyz = np.array([[0, 0, 0], [1, 0, 0], [0, 2, 0], [0, 0, 3.]])
    frequency = dict(elements=['C', 'H', 'F', 'Cl'], coordinates=xyz, frequencies=[-100],
                     displacements=[np.ones((4, 3))], attempt='synthetic', orientation='standard',
                     stationarity='stationary', geometry_sha256='0' * 64, source={})
    reflected = xyz * [-1, 1, 1]
    report = mapped_candidate(frequency['elements'], reflected, frequency, [SPECS[0]])
    assert report['aligned_rmsd_angstrom'] > 0.5


@pytest.mark.parametrize('change,match', [
    ('not_fetched', 'fetched'), ('no_freq', 'frequency'), ('orientation', 'orientation'),
    ('facts', 'facts not readable'), ('manifest', 'identity|manifest'), ('non_gaussian', 'Gaussian'),
    ('traversal', 'IDs'), ('symlink', 'Symbolic')])
def test_attempt_reader_refuses_bad_inputs(fetched, change, match):
    root, path = fetched
    identity = path.name
    if change == 'not_fetched':
        (path / 'status.json').write_text('{"state":"prepared"}')
    elif change in ('no_freq', 'orientation'):
        log = path / 'outputs/job.log'
        log.write_text(log.read_text().replace('Freq\n', 'SP\n') if change == 'no_freq' else
                       log.read_text().replace('Standard orientation', 'Input orientation'))
    elif change == 'facts':
        (path / 'facts.json').write_text('[]')
    elif change in ('manifest', 'non_gaussian'):
        manifest = json.loads((path / 'manifest.json').read_text())
        manifest['study_id' if change == 'manifest' else 'template'] = 'wrong'
        (path / 'manifest.json').write_text(json.dumps(manifest))
    elif change == 'traversal':
        identity = '../' + identity
    else:
        link = root / 'attempts' / 'linked'
        link.symlink_to(path, target_is_directory=True)
        identity = link.name
    with pytest.raises(ValueError, match=match):
        gm.read_frequency_attempt(root, identity)


@pytest.mark.parametrize('optional', [False, True])
def test_frequency_ambiguity_has_parser_type_and_exact_log_source(fetched, optional):
    root, path = fetched
    log = path / 'outputs/job.log'
    raw = log.read_bytes() + b' unexplained synthetic tail\r\n'
    log.write_bytes(raw)
    with pytest.raises(gm.mode_review.FrequencySectionAmbiguity):
        gm.mode_review.frequency_section(raw)
    with pytest.raises(gm.FrequencySourceAmbiguity, match='Ambiguous') as error:
        gm.read_frequency_attempt(root, path.name, allow_unavailable=optional)
    assert error.value.attempt == path.name
    assert error.value.source == dict(log=log.relative_to(root).as_posix(),
                                      log_sha256=sha256(raw).hexdigest())


def test_frequency_reader_does_not_classify_ambiguity_by_error_text(fetched, monkeypatch):
    root, path = fetched
    def unclassified(raw):
        raise ValueError('Ambiguous Gaussian job sections: synthetic unrelated error')
    monkeypatch.setattr(gm.mode_review, 'frequency_section', unclassified)
    with pytest.raises(ValueError) as error:
        gm.read_frequency_attempt(root, path.name, allow_unavailable=True)
    assert type(error.value) is ValueError


def test_stationarity_uses_facts_opt_source_before_frequency(fetched):
    root, path = fetched
    log = path / 'outputs/job.log'
    opt = (' Entering Gaussian System\n -----\n # opt\n -----\n'
           ' Optimization completed.\n Normal termination of Gaussian\n')
    continued_freq = FIXTURE.read_bytes().replace(b' Entering Gaussian System', b' --Link1--')
    log.write_bytes(opt.encode() + continued_freq)
    facts = write_facts(path)
    frequency = gm.read_frequency_attempt(root, path.name)
    assert frequency['stationarity'] == 'stationary'
    assert 'non_stationary_frequencies' not in mapped_candidate(ELEMENTS, XYZ, frequency, SPECS)['flags']
    # An Opt following the frequency does not establish its stationarity.
    log.write_bytes(FIXTURE.read_bytes() + opt.replace(' Entering Gaussian System', ' --Link1--').encode())
    write_facts(path)
    assert gm.read_frequency_attempt(root, path.name)['stationarity'] == 'unknown'
    # Legacy/mismatched facts cannot establish the claimed source.
    log.write_bytes(opt.encode() + continued_freq)
    for bad in ({}, dict(facts, fact_sources={}), dict(facts, job_sections=[])):
        (path / 'facts.json').write_text(json.dumps(dict(bad, schema='ag-facts/1')))
        frequency = gm.read_frequency_attempt(root, path.name)
        report = mapped_candidate(ELEMENTS, XYZ, frequency, SPECS)
        assert report['stationarity'] == 'unknown'
        assert 'non_stationary_frequencies' in report['flags']


@pytest.mark.parametrize('before,expected', [(True, 'stationary'), (False, 'unknown')])
def test_combined_opt_freq_checks_order(fetched, before, expected):
    root, path = fetched
    text = FIXTURE.read_text().replace('HF/3-21G Freq', 'HF/3-21G Opt Freq')
    marker = ' Harmonic frequencies' if before else ' Normal termination'
    convergence = (' Step number 1\n' + ' Item Value Threshold'.ljust(49) + 'Converged?\n'
                   ' Maximum Force 0.000001 0.000450 YES\n'
                   ' RMS Force 0.000001 0.000300 YES\n'
                   ' Maximum Displacement 0.000001 0.001800 YES\n'
                   ' RMS Displacement 0.000001 0.001200 YES\n'
                   ' Optimization completed.\n')
    text = text.replace(marker, convergence + marker)
    (path / 'outputs/job.log').write_text(text)
    assert write_facts(path)['opt_converged'] is True
    assert gm.read_frequency_attempt(root, path.name)['stationarity'] == expected


def test_reaction_coordinate_file_cli_provenance_and_missing(fetched):
    root, path = fetched
    config = root / 'analyses/windows.json'
    config.write_text(json.dumps(dict(channels={}, all=[], reaction_coordinates={'transfer': SPECS})))
    loaded = g0._windows(root, 'analyses/windows.json', [])
    specs, sources = gm.reaction_coordinates(loaded['content'], 'transfer', loaded['source'], ['angle:1-2-3:report'])
    assert specs[:2] == SPECS and specs[-1]['kind'] == 'angle'
    assert sources[0]['sha256'] == sha256(config.read_bytes()).hexdigest()
    assert sources[1] == dict(command_line='angle:1-2-3:report')
    for channel in (None, 'absent'):
        assert gm.reaction_coordinates(loaded['content'], channel, loaded['source'])[0] == []
    frequency = gm.read_frequency_attempt(root, path.name)
    report = mapped_candidate(ELEMENTS, XYZ, frequency, [])
    assert not report['available'] and report['reason'] == '未声明反应坐标' and report['flags'] == []


@pytest.mark.parametrize('value', ['distance:0-1:breaking', 'distance:1-1:forming',
    'distance:1-2-3:breaking', 'angle:1-2:report', 'distance:1-2:report', 'distance:1-2:forming:extra'])
def test_invalid_cli_coordinate(value):
    with pytest.raises(ValueError):
        gm.coordinate_argument(value)


@pytest.mark.parametrize('kind', ['outside', 'symlink', 'bad_json', 'bad_channels', 'bad_list'])
def test_coordinate_file_validation(fetched, kind):
    root, _ = fetched
    config = root / 'analyses/windows.json'
    config.write_text('{}')
    if kind == 'outside':
        config = root / 'outside.json'
        config.write_text('{}')
    elif kind == 'symlink':
        link = root / 'analyses/link.json'
        link.symlink_to(config)
        config = link
    elif kind == 'bad_json':
        config.write_text('[]')
    elif kind == 'bad_channels':
        config.write_text('{"reaction_coordinates": []}')
    else:
        config.write_text('{"reaction_coordinates": {"transfer": {}}}')
    with pytest.raises(ValueError):
        loaded = g0._windows(root, config, [])
        gm.reaction_coordinates(loaded['content'], 'transfer', loaded['source'])


@pytest.mark.parametrize('channel', ['../escape', 'Bad-ID', '', 'x y'])
def test_coordinate_channel_ids_validated_even_when_unselected(channel):
    with pytest.raises(ValueError, match='IDs'):
        gm.reaction_coordinates({'reaction_coordinates': {channel: []}}, 'transfer')


def test_frequency_reader_resolves_configured_study_name(fetched, monkeypatch):
    root, path = fetched
    monkeypatch.setattr(gm.catalog, 'load_config', lambda **kw: {'local': {'studies_root': str(root.parent)}})
    assert gm.read_frequency_attempt(root.name, path.name)['attempt'] == path.name


def test_xtb_cartesian_modes_keep_source_frame_and_nonself_inverse_mapping():
    from ag import xtb_hessian as x
    from test_xtb_hessian import XYZ as source_xyz, MASS, synthetic_matrix
    h, _ = synthetic_matrix()
    converted = x.convert(h, source_xyz, MASS, 1)
    indices = np.array(converted['internal_indices']) - 1
    q = np.asarray(converted['full_displacements'])[indices]
    frequencies = np.asarray(converted['full_frequencies_cm1'])[indices]
    permutation = [2, 3, 1]
    mapping = dict(status='declared_verified', candidate_to_target=permutation)
    def diagnose(xyz, vectors):
        source = dict(elements=['O', 'H', 'H'], coordinates=xyz, frequencies=frequencies,
                      displacements=vectors, analysis='analyses/example/analysis.json',
                      stationarity='unknown', orientation='source frame', geometry_sha256='a'*64,
                      source=dict(sha256='b'*64), warnings=['synthetic'], convention=x.CONVENTION,
                      spectrum_indices=converted['internal_indices'])
        return gm.analyze_candidate(['H', 'H', 'O'], xyz[[1, 2, 0]], source,
                                    [dict(kind='distance', atoms=[1, 3], role='breaking')],
                                    correspondence=mapping)
    original = diagnose(source_xyz, q)
    rot, _ = np.linalg.qr(np.random.default_rng(176).normal(size=(3, 3)))
    rotated = diagnose(source_xyz @ rot + [5, -3, 7], q @ rot)
    assert original['frequency_coordinates_spec'][0]['atoms'] == [2, 1]
    for left, right in zip(original['modes'], rotated['modes']):
        assert left['delta'][0]['value'] == pytest.approx(right['delta'][0]['value'], abs=1e-12)
        assert left['overlap'] == pytest.approx(right['overlap'], abs=1e-12)
    assert original['atom_correspondence']['candidate_to_target'] == [2, 3, 1]
    assert 'attempt' not in original

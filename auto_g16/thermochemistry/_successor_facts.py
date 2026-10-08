"""Pure native input facts; physical source replay belongs to the caller."""
from math import isfinite

from auto_g16.core import Observation, Result
from auto_g16.result import ParseOutcome, ParseStatus
from auto_g16.result._successor import parse_freq_source, payload_hash
from ._gaussian_thermo_facts import (
    GaussianThermoFactsError, _require, _closed, _float, _MASS, _SYMMETRY,
    _ROTATIONAL_TEMPERATURES, _POINT_GROUP, _SOURCE_KEYS, _SPAN_KEYS,
)
from .models import _freeze_mapping

_SCHEMA = "v31-conformer-successor-two-stage-minimum-authority/2"
_METHOD = {
    "program": "gaussian16", "method": "wB97XD", "basis": "Def2SVP",
    "dispersion": "intrinsic_wB97XD", "solvent": "gas",
    "reference": "restricted_closed_shell", "charge": 0, "multiplicity": 1,
    "integration_grid": "UltraFine", "scf_policy": "Tight_MaxCycle128",
}
_MINIMUM_KEYS = {
    "authority_schema", "source", "method_binding", "method_id", "optimization",
    "frequency", "assessment", "two_stage_minimum_authority_id",
}
_FREQUENCY_KEYS = {
    "calculation_plan", "input", "result_source", "parsed_result", "selected_geometry",
    "frequency_blocks", "frequencies_cm1", "mode_count", "tail_evidence",
}


def extract_successor_thermo_facts(*, raw_gaussian_bytes, source_result,
                                 minimum_authority, native_source, native_result):
    """Rebuild exact native objects, then project section-bound input facts."""
    _require(type(raw_gaussian_bytes) is bytes, "native log must be exact bytes")
    _require(type(source_result) is ParseOutcome and type(native_source) is Observation
             and type(native_result) is Result, "native facts require exact source/result objects")
    observation, result, _envelope, parsed = parse_freq_source(native_source.data, raw_gaussian_bytes)
    _require(observation == native_source and result == native_result,
             "native source/result differs from complete reconstruction")
    _require(parsed.payload() == source_result.payload() and parsed.result_id == source_result.result_id,
             "parsed carrier differs from complete reconstruction")
    _require(parsed.parse_status is ParseStatus.PARSED, "native frequency is not parsed")
    minimum = _closed(minimum_authority, _MINIMUM_KEYS, "native minimum authority")
    payload = {k: v for k, v in minimum.items() if k != "two_stage_minimum_authority_id"}
    _require(minimum['authority_schema'] == _SCHEMA
             and minimum['two_stage_minimum_authority_id'] == payload_hash({'domain': _SCHEMA, 'payload': payload}),
             "native minimum identity/schema differs")
    _require(minimum['method_binding'] == _METHOD
             and minimum['method_id'] == payload_hash({'domain': 'v31-successor-stage-independent-method/1', 'method': _METHOD}),
             "native method differs")
    _require(minimum['assessment']['classification'] == 'VALIDATED_TWO_STAGE_MINIMUM',
             "native member is not a minimum")
    frequency = _closed(minimum['frequency'], _FREQUENCY_KEYS, "native frequency authority")
    _require(frequency['result_source'] == {'observation_id': observation.observation_id,
                 'payload_sha256': payload_hash(observation.data)}
             and frequency['parsed_result'] == {'result_id': result.result_id,
                 'payload_sha256': payload_hash(result.data)}, "native authority source/result differs")
    facts = parsed.facts
    source = _closed(facts['source_artifact'], _SOURCE_KEYS, "native artifact")
    section = _closed(facts['job_section'], _SPAN_KEYS, "native section")
    start, end = section['start'], section['end']
    _require(type(start) is int and type(end) is int and 0 <= start < end <= len(raw_gaussian_bytes)
             and all(section[k] == source[k] for k in _SOURCE_KEYS), "native section differs")

    def check_span(value):
        span = _closed(value, _SPAN_KEYS, "native fact span")
        _require(all(span[k] == source[k] for k in _SOURCE_KEYS)
                 and type(span['start']) is int and type(span['end']) is int
                 and start <= span['start'] < span['end'] <= end, "native fact span differs")

    values = tuple(facts['frequencies_cm-1'])
    _require(len(values) == 36 and all(type(v) in (int, float) and isfinite(v) and v > 0 for v in values),
             "native thermal input requires 36 positive finite modes")
    blocks = facts['frequency_blocks']
    _require(tuple(v for b in blocks for v in b['frequencies_cm-1']) == values
             and frequency['frequency_blocks'] == blocks
             and frequency['frequencies_cm1'] == values and frequency['mode_count'] == 36,
             "native frequency evidence differs")
    for block in blocks:
        check_span(block['source_span'])
    tail = frequency['tail_evidence']
    markers = facts['optimization_completed_evidence'], facts['stationary_point_evidence']
    if tail is None:
        _require(not any(markers), "native tail evidence is missing")
    else:
        _closed(tail, {'schema', 'form', 'source_artifact', 'job_section', 'route_echo_span',
                      'archive_span', 'tail_span', 'optimization_completed_span', 'stationary_point_span'}, 'native tail')
        _require(tail['schema'] == 'v31-gaussian-freq-tail-evidence/1'
                 and tail['form'] == 'g16-a03-freq-l716-l103/1'
                 and tail['source_artifact'] == source and tail['job_section'] == section
                 and tuple(markers[0]) == (tail['optimization_completed_span'],)
                 and tuple(markers[1]) == (tail['stationary_point_span'],), "native tail association differs")
        for key in ('route_echo_span', 'archive_span', 'tail_span', 'optimization_completed_span', 'stationary_point_span'):
            check_span(tail[key])
    scfs = facts['scf_calculations']
    _require(bool(scfs), "native electronic energy is missing")
    for scf in scfs:
        check_span(scf['source_span'])
    final = max(scfs, key=lambda row: row['source_span']['start'])
    energy = facts['final_energy_hartree']
    _require(type(energy) in (int, float) and isfinite(energy)
             and final == scfs[-1] and final['energy_hartree'] == energy, "native final energy differs")

    records = {'mass': [], 'symmetry': [], 'rotations': [], 'point_group': []}
    patterns = ((_MASS, b'Molecular mass:', 'mass'),
                (_SYMMETRY, b'Rotational symmetry number', 'symmetry'),
                (_ROTATIONAL_TEMPERATURES, b'Rotational temperatures', 'rotations'),
                (_POINT_GROUP, b'Full point group', 'point_group'))
    offset = start
    # Only LF divides lines; retain CRLF and original byte offsets in spans.
    for chunk in raw_gaussian_bytes[start:end].split(b'\n'):
        stop = min(offset + len(chunk) + 1, end)
        line = chunk[:-1] if chunk.endswith(b'\r') else chunk
        for pattern, marker, key in patterns:
            match = pattern.fullmatch(line)
            if match:
                if key == 'rotations':
                    value = tuple(_float(match.group(i), key) for i in (1, 2, 3))
                elif key == 'point_group':
                    value = match.group(1).decode('ascii')
                elif key == 'symmetry':
                    value = int(match.group(1))
                else:
                    value = _float(match.group(1), key)
                span = {**source, 'start': offset, 'end': stop}
                check_span(span)
                records[key].append((value, span))
                break
            if line.lstrip().startswith(marker):
                raise GaussianThermoFactsError('native ' + key + ' evidence is malformed')
        offset = stop

    def fact(key, *, single=False, optional=False):
        rows = records[key]
        if optional and not rows:
            return None
        _require(bool(rows) and (not single or len(rows) == 1), 'native ' + key + ' count differs')
        _require(all(row[0] == rows[0][0] for row in rows), 'native ' + key + ' conflicts')
        return {'value': rows[0][0], 'source_spans': tuple(row[1] for row in rows)}

    return _freeze_mapping({
        'source_artifact': source, 'job_section': section,
        'electronic_energy_hartree': {'value': energy, 'source_span': final['source_span']},
        'frequency_blocks': blocks, 'frequencies_cm1': values,
        'molecular_mass_amu': fact('mass', single=True),
        'rotational_symmetry_number': fact('symmetry'),
        'rotational_temperatures_kelvin': fact('rotations', single=True),
        'point_group_diagnostic': fact('point_group', optional=True),
        'gaussian_reported_thermochemistry': facts['thermochemistry'],
    }, 'native thermal input facts')

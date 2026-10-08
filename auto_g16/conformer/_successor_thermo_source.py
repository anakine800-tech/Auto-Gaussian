"""Complete read-only native input facts; no thermodynamic eligibility or effect."""
from . import frequency_readonly as reader
from .refinement_authority import _require
from .models import _freeze_mapping
from ._successor_freq import SCHEMA_V2
from auto_g16.result._successor import parse_freq_source, require_pair, payload_hash
from auto_g16.thermochemistry._successor_facts import extract_successor_thermo_facts


def read_native_thermo_inputs(readout):
    """Return detached full-member facts only after every source context closes."""
    _require(type(readout) is reader.FreqReadout, 'native thermal input requires exact FreqReadout')
    if not reader.opt_reader._OPT_READ_LOCK.acquire(timeout=reader.opt_reader._OPT_READ_WAIT_SECONDS):
        raise reader.opt_reader.OptReadBusy('two-stage read slot is busy')
    try:
        with reader._replayed_frequency(readout) as (profile, _prior, refined, opts, freqs):
            ids = tuple(m['member_id'] for m in refined.members)
            _require(bool(ids) and len(ids) == len(set(ids)) and set(ids) == set(opts) == set(freqs),
                     'native thermal input requires every member source')
            members = []
            for member in refined.members:
                authority = member.get('two_stage_minimum_authority')
                _require(member.get('post_dft_status') == 'validated_minimum'
                         and member.get('negative_frequency_authority') is None
                         and authority is not None and authority['authority_schema'] == SCHEMA_V2,
                         'native thermal input requires positive version-two authority')
                args = freqs[member['member_id']]
                with reader.gaussian_freq_result_source(args['source_store'], snapshot=args['snapshot'],
                        transport_store=args['transport_store']) as (_, payload, _, log):
                    source, result, _, parsed = parse_freq_source(payload, log)
                    require_pair(args['destination'], source, result)
                    facts = extract_successor_thermo_facts(raw_gaussian_bytes=log, source_result=parsed,
                        minimum_authority=authority, native_source=source, native_result=result)
                    members.append({'member_id': member['member_id'], 'minimum_authority': authority,
                        'native_source': {'observation_id': source.observation_id, 'payload_sha256': payload_hash(source.data)},
                        'native_result': {'result_id': result.result_id, 'payload_sha256': payload_hash(result.data),
                            'parser_name': parsed.parser_name, 'parser_version': parsed.parser_version, 'result_kind': parsed.result_kind},
                        'thermo_facts': facts})
            projection = _freeze_mapping({'schema': 'auto-g16-native-thermo-input-facts/1',
                'source_ensemble': {'conformer_ensemble_id': refined.conformer_ensemble_id,
                    'payload_sha256': refined.payload_sha256, 'revision': refined.revision},
                'sampling_profile': {'sampling_profile_id': profile.sampling_profile_id, 'payload_sha256': profile.payload_sha256},
                'members': tuple(members)}, 'native thermal input')
        return projection
    finally:
        reader.opt_reader._OPT_READ_LOCK.release()

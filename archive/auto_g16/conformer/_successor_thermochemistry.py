"""Bounded native thermochemistry within one complete protected source replay."""
from . import frequency_readonly as reader
from .refinement_authority import _require
from ._successor_thermo_source import _native_input_facts_from_replay
from auto_g16.thermochemistry._native_service import (
    _normalize_request, _qualify_ensemble, _build_native_thermodynamic_ensemble,
)


def build_native_thermodynamic_ensemble(readout, *, request):
    """Return detached in-memory records only after all source exit checks pass."""
    _require(type(readout) is reader.FreqReadout, 'native thermochemistry requires exact FreqReadout')
    if not reader.opt_reader._OPT_READ_LOCK.acquire(timeout=reader.opt_reader._OPT_READ_WAIT_SECONDS):
        raise reader.opt_reader.OptReadBusy('two-stage read slot is busy')
    try:
        with reader._replayed_frequency(readout) as (profile, _prior, refined, opts, freqs):
            facts = _native_input_facts_from_replay(profile, refined, opts, freqs)
            normalized = _normalize_request(request)
            qualified = _qualify_ensemble(refined, profile, facts, normalized)
            thermo = _build_native_thermodynamic_ensemble(
                source_ensemble=refined, qualified_ensemble=qualified, profile=profile,
                native_facts=facts, request=normalized,
            )
        return qualified, thermo
    finally:
        reader.opt_reader._OPT_READ_LOCK.release()

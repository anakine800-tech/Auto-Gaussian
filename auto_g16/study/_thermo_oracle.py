"""Independent, bounded raw-log partition calculation; standard library only."""
from decimal import (Context, Decimal, DivisionByZero, InvalidOperation, Overflow,
                     ROUND_HALF_EVEN, localcontext)
from hashlib import sha256
import re


class OracleError(ValueError):
    """Closed parser/numerical failure; no partial scientific result is returned."""


_NUMBER = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?'
_CONSTANTS = {
    'gas_constant_j_mol_k': '8.3144621', 'boltzmann_j_k': '1.3806488e-23',
    'planck_j_s': '6.62606957e-34', 'speed_of_light_cm_s': '29979245800',
    'avogadro_mol': '6.0221415e23', 'atomic_mass_kg': '1.66053886e-27',
    'pi': '3.1415926535897932384626433832795028841971693993751',
}


def _require(value):
    if not value:
        raise OracleError('invalid-frequency-log')


def _number(value, *, positive=False):
    _require(type(value) is str and 0 < len(value) <= 64
             and re.fullmatch(_NUMBER, value) is not None)
    result = Decimal(value.replace('D', 'E').replace('d', 'e'))
    _require(result.is_finite() and (result == 0 or -12 <= result.adjusted() <= 12)
             and (not positive or result > 0))
    return result


def _record(lines, label, pattern):
    # Count all records bearing this label, including malformed values.
    matches = [line.strip() for line in lines if line.strip().startswith(label)]
    _require(len(matches) == 1)
    match = re.fullmatch(pattern, matches[0])
    _require(match is not None)
    return match.groups()


def _parse(raw):
    _require(type(raw) is bytes and 0 < len(raw) <= 64 * 1024 * 1024)
    try:
        text = raw.decode('utf-8')
    except UnicodeError as exc:
        raise OracleError('invalid-frequency-log') from exc
    _require(text.count('Normal termination of Gaussian') == 1
             and 'Error termination' not in text)
    lines = text.splitlines()
    # The population analysis has a separate scalar electron-charge record.
    charge_lines = [line for line in lines if not re.fullmatch(
        r'\s*Charge=\s*' + _NUMBER + r'\s+electrons\s*', line)]
    charge, multiplicity = _record(charge_lines, 'Charge', r'Charge\s*=\s*(-?\d+)\s+Multiplicity\s*=\s*(\d+)')
    _require((charge, multiplicity) == ('0', '1'))
    atoms = [line.strip() for line in lines if line.strip().startswith('NAtoms')]
    _require(1 <= len(atoms) <= 8)
    for line in atoms:
        # Gaussian emits two distinct atom-count lines. Permit their closed
        # metadata forms but never a fractional/malformed count or unknown tail.
        match = re.fullmatch(r'NAtoms=\s*(14)(?:'
            r'\s+NQM=\s*\d+\s+NQMF=\s*\d+\s+NMMI=\s*\d+\s+NMMIF=\s*\d+|'
            r'\s+NActive=\s*\d+\s+NUniq=\s*\d+\s+SFac=\s*' + _NUMBER
            + r'\s+NAtFMM=\s*\d+\s+NAOKFM=[TF]\s+Big=[TF])?', line)
        _require(match is not None)
    frequencies, indices = [], []
    for i, line in enumerate(lines):
        if line.strip().startswith('Frequencies'):
            _require(i >= 2 and line.strip().startswith('Frequencies --')
                     and line.count('Frequencies --') == 1)
            block = line.split('Frequencies --')[1].split()
            ids = lines[i - 2].split()
            _require(1 <= len(block) <= 3 and len(ids) == len(block)
                     and all(re.fullmatch(r'[1-9]\d?', x) for x in ids))
            frequencies.extend(_number(x, positive=True) for x in block)
            indices.extend(int(x) for x in ids)
    _require(indices == list(range(1, 37)) and len(frequencies) == 36)
    energy, = _record(lines, 'SCF Done', r'SCF Done:\s+E\([A-Za-z0-9_-]{1,64}\)\s*=\s*('
                      + _NUMBER + r')\s+A\.U\.(?:\s+after\s+\d+\s+cycles)?')
    energy = _number(energy)
    mass, = _record(lines, 'Molecular mass', r'Molecular mass:\s*(' + _NUMBER + r')\s+amu\.')
    mass = _number(mass, positive=True)
    sigma_text, = _record(lines, 'Rotational symmetry number', r'Rotational symmetry number\s+(\d{1,3})\.')
    sigma = int(sigma_text)
    _require(1 <= sigma <= 100)
    theta = tuple(_number(x, positive=True) for x in _record(lines, 'Rotational temperatures',
        r'Rotational temperatures \(Kelvin\)\s+(' + _NUMBER + r')\s+('
        + _NUMBER + r')\s+(' + _NUMBER + r')'))
    condition = _record(lines, 'Temperature', r'Temperature\s+(' + _NUMBER + r')\s+Kelvin\.\s+Pressure\s+('
                        + _NUMBER + r')\s+Atm\.')
    _require(tuple(_number(x, positive=True) for x in condition) == (Decimal('298.15'), Decimal(1)))
    reported = {}
    for name, label in (('ZPE_Eh', 'Zero-point correction'), ('Ucorr_Eh', 'Thermal correction to Energy'),
                        ('Hcorr_Eh', 'Thermal correction to Enthalpy'),
                        ('Gcorr_Eh', 'Thermal correction to Gibbs Free Energy')):
        suffix = r'(?:\s+\(Hartree/Particle\))?' if name == 'ZPE_Eh' else ''
        value, = _record(lines, label, re.escape(label) + r'=\s*(' + _NUMBER + r')' + suffix)
        reported[name] = _number(value)
    headers = [i for i, line in enumerate(lines) if line.strip().startswith('E (Thermal)')]
    _require(len(headers) == 1 and headers[0] + 6 < len(lines))
    start = headers[0]
    _require(re.fullmatch(r'\s*E \(Thermal\)\s+CV\s+S\s*', lines[start]))
    _require(re.fullmatch(r'\s*KCal/Mol\s+Cal/Mol-Kelvin\s+Cal/Mol-Kelvin\s*', lines[start + 1]))
    for offset, name in enumerate(('Total', 'Electronic', 'Translational', 'Rotational', 'Vibrational'), 2):
        row = _record([lines[start + offset]], name, r'\s*' + name + r'\s+(' + _NUMBER + r')\s+('
                   + _NUMBER + r')\s+(' + _NUMBER + r')\s*$')
        reported[name] = dict(zip(('U_kcal_mol', 'Cv_cal_mol_K', 'S_cal_mol_K'), map(_number, row)))
    return dict(electronic_energy_hartree=energy, molecular_mass_amu=mass,
                rotational_symmetry_number=sigma, rotational_temperatures_k=theta,
                frequencies_cm1=frequencies, charge=0, multiplicity=1, atom_count=14), reported


def _serial(value):
    if isinstance(value, Decimal):
        _require(value.is_finite())
        if value == 0:
            return '0'
        text = format(value, 'f')
        return text.rstrip('0').rstrip('.') if '.' in text else text
    if type(value) is dict:
        return {k: _serial(v) for k, v in value.items()}
    if type(value) in (tuple, list):
        return [_serial(v) for v in value]
    return value


def calculate(raw_log):
    """Recompute the selected butane policy, without reading any saved totals."""
    context = Context(prec=50, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999,
                      capitals=1, clamp=0, traps=[InvalidOperation, DivisionByZero, Overflow])
    try:
        with localcontext(context):
            return _calculate(raw_log)
    except (InvalidOperation, DivisionByZero, Overflow, UnicodeError, ArithmeticError) as exc:
        raise OracleError('numerical-calculation-failed') from exc


def _calculate(raw_log):
    parsed, reported = _parse(raw_log)
    constants = {name: Decimal(value) for name, value in _CONSTANTS.items()}
    r, k, h, c, na, amu, pi = (constants[name] for name in _CONSTANTS)
    conversion = Decimal('4.184') * Decimal('627.509541') * 1000
    constants.update(hartree_j_mol=conversion, convention='goodvibes-4.3.0-frozen-comparison')
    t, p, bav = Decimal('298.15'), Decimal('101325'), Decimal('1e-44')
    step = Decimal('0.01')
    residual_u, residual_s = Decimal(0), Decimal(0)

    def stat(logq, delta):
        derivative = (logq(t - 2 * delta) - 8 * logq(t - delta)
                      + 8 * logq(t + delta) - logq(t + 2 * delta)) / (12 * delta)
        u = r * t * t * derivative
        return u, r * logq(t) + u / t

    def paired(logq):
        nonlocal residual_u, residual_s
        u, s = stat(logq, step)
        u2, s2 = stat(logq, step / 2)
        residual_u = max(residual_u, abs(u - u2))
        residual_s = max(residual_s, abs(s - s2))
        return u, s

    mass, sigma, theta = (parsed[name] for name in
                          ('molecular_mass_amu', 'rotational_symmetry_number', 'rotational_temperatures_k'))
    density = p / (r * t) * na
    ut, st = paired(lambda temp: Decimal('1.5') * (2 * pi * mass * amu * k * temp / h ** 2).ln() - density.ln())
    st += r
    ur, sr = paired(lambda temp: (pi * temp ** 3 / (theta[0] * theta[1] * theta[2])).ln() / 2 - Decimal(sigma).ln())
    modes = []
    for index, frequency in enumerate(parsed['frequencies_cm1'], 1):
        th = h * c * frequency / k
        zpe = r * th / 2
        weight = frequency ** 4 / (frequency ** 4 + Decimal(100) ** 4)
        logho = lambda temp: -th / (2 * temp) - (1 - (-th / temp).exp()).ln()
        u, s = paired(logho)
        inertia = 1 / (8 * pi * pi * c * frequency / h + 1 / bav)
        uf, sf = paired(lambda temp: (8 * pi ** 3 * inertia * k * temp / h ** 2).ln() / 2)
        delta_zpe = (na - r / k) * h * c * frequency / 2
        uhg, shg = paired(lambda temp: logho(temp) - delta_zpe / (r * temp))
        _require(abs(shg - s) < Decimal('1e-12'))
        uq, sq = weight * uhg + (1 - weight) * uf, weight * s + (1 - weight) * sf
        modes.append(dict(mode=index, frequency_cm1=frequency, weight_HO=weight, ZPE_J_mol=zpe,
            U_HO_J_mol=u, U_q_J_mol=uq, S_HO_J_mol_K=s, S_free_rotor_J_mol_K=sf, S_q_J_mol_K=sq,
            delta_H_J_mol=uq - u, delta_S_J_mol_K=sq - s, delta_G_J_mol=uq - u - t * (sq - s),
            HG_constant_residual_J_mol=uq - (weight * u + (1 - weight) * uf)))
    total = lambda key: sum((row[key] for row in modes), Decimal(0))
    energy = parsed['electronic_energy_hartree']
    comp = dict(E_electronic_Eh=energy, ZPE_J_mol=total('ZPE_J_mol'), U_trans_J_mol=ut, U_rot_J_mol=ur,
        U_vib_RRHO_J_mol=total('U_HO_J_mol'), U_vib_thermal_RRHO_J_mol=total('U_HO_J_mol') - total('ZPE_J_mol'),
        U_vib_qRRHO_J_mol=total('U_q_J_mol'), pV_J_mol=r * t, S_trans_J_mol_K=st,
        S_rot_J_mol_K=sr, S_elec_J_mol_K=Decimal(0), S_vib_RRHO_J_mol_K=total('S_HO_J_mol_K'),
        S_vib_qRRHO_J_mol_K=total('S_q_J_mol_K'))
    results = {}
    for scheme in ('RRHO', 'qRRHO'):
        hc = ut + ur + comp['U_vib_' + scheme + '_J_mol'] + r * t
        entropy = st + sr + comp['S_vib_' + scheme + '_J_mol_K']
        gc = hc - t * entropy
        comp.update({'Hcorr_' + scheme + '_J_mol': hc, 'S_' + scheme + '_J_mol_K': entropy,
                     'Gcorr_' + scheme + '_J_mol': gc})
        results[scheme] = dict(H_Eh=energy + hc / conversion, S_J_mol_K=entropy, G_Eh=energy + gc / conversion)
    comp.update(delta_H_q_minus_R_J_mol=total('delta_H_J_mol'), delta_S_q_minus_R_J_mol_K=total('delta_S_J_mol_K'),
                delta_G_q_minus_R_J_mol=total('delta_G_J_mol'))
    return _serial(dict(schema='auto-g16-independent-thermo-oracle/1', source_sha256=sha256(raw_log).hexdigest(),
        conditions=dict(temperature_k=t, pressure_atm=Decimal(1), frequency_scale=Decimal(1), zpe_scale=Decimal(1),
            entropy_model='grimme', enthalpy_model='head_gordon', cutoff_cm1=Decimal(100), alpha=Decimal(4), bav_kg_m2=bav),
        constants=constants, parsed=parsed, components=comp, modes=modes, results=results, reported=reported,
        numerical_check=dict(decimal_digits=50, derivative_step_k=step, energy_residual_J_mol=residual_u,
            entropy_residual_J_mol_K=residual_s, HG_constant_residual_J_mol=total('HG_constant_residual_J_mol'),
            qRRHO_G_coherent_constants_Eh=results['qRRHO']['G_Eh'] - total('HG_constant_residual_J_mol') / conversion)))

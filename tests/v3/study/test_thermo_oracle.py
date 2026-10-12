"""Independent numerical limits and fail-closed raw Gaussian parsing."""
import ast
from decimal import Decimal, Inexact, ROUND_DOWN, getcontext, localcontext
from hashlib import sha256
from pathlib import Path
import unittest

from auto_g16.study import _thermo_oracle as oracle


def sample():
    text = ('SYNTHETIC FREQUENCY LOG: never scientific evidence\n'
            'Charge = 0 Multiplicity = 1\nNAtoms= 14\nNAtoms= 14\n'
            'SCF Done: E(RTEST) = -157.125000 A.U.\n'
            'Molecular mass: 58.1222 amu.\nRotational symmetry number 1.\n'
            'Rotational temperatures (Kelvin) 0.50000 0.15000 0.12000\n'
            'Temperature 298.150 Kelvin. Pressure 1.00000 Atm.\n')
    for i in range(1, 37, 3):
        text += ' '.join(str(j) for j in range(i, i + 3)) + '\n A A A\n Frequencies -- '
        text += ' '.join(str(100 + 85 * j) + '.0000' for j in range(i - 1, i + 2)) + '\n'
    text += ('Zero-point correction= 0.100000\nThermal correction to Energy= 0.110000\n'
             'Thermal correction to Enthalpy= 0.111000\nThermal correction to Gibbs Free Energy= 0.080000\n')
    text += ' E (Thermal) CV S\n KCal/Mol Cal/Mol-Kelvin Cal/Mol-Kelvin\n'
    for label in ('Total', 'Electronic', 'Translational', 'Rotational', 'Vibrational'):
        text += label + ' 0.000 0.000 0.000\n'
    return (text + 'Normal termination of Gaussian\n').encode()


class IndependentThermoOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = sample()
        cls.result = oracle.calculate(cls.raw)

    def test_closed_result_and_canonical_numbers(self):
        r = self.result
        self.assertEqual(set(r), {'schema', 'source_sha256', 'conditions', 'constants',
                                 'parsed', 'components', 'modes', 'results', 'reported', 'numerical_check'})
        self.assertEqual(r['source_sha256'], sha256(self.raw).hexdigest())
        self.assertEqual(r['schema'], 'auto-g16-independent-thermo-oracle/1')
        self.assertEqual(r['parsed']['electronic_energy_hartree'], '-157.125')
        self.assertEqual(len(r['modes']), 36)
        self.assertEqual([r['mode'] for r in r['modes']], list(range(1, 37)))
        self.assertEqual(r['modes'][0]['weight_HO'], '0.5')
        self.assertEqual(set(r['numerical_check']), {'decimal_digits', 'derivative_step_k',
            'energy_residual_J_mol', 'entropy_residual_J_mol_K', 'HG_constant_residual_J_mol',
            'qRRHO_G_coherent_constants_Eh'})
        for row in r['results'].values():
            self.assertEqual(set(row), {'H_Eh', 'S_J_mol_K', 'G_Eh'})
            for value in row.values():
                self.assertIs(type(value), str)
                self.assertNotIn('E', value)
                self.assertTrue(Decimal(value).is_finite())

    def test_analytic_translation_rotation_and_thermodynamic_units(self):
        r = self.result
        with localcontext() as ctx:
            ctx.prec = 50
            gas, t = Decimal('8.3144621'), Decimal('298.15')
            expected = Decimal('1.5') * gas * t
            for key in ('U_trans_J_mol', 'U_rot_J_mol'):
                self.assertLess(abs(Decimal(r['components'][key]) - expected), Decimal('1e-9'))
            conversion = Decimal(r['constants']['hartree_j_mol'])
            for scheme, values in r['results'].items():
                h, s, g = (Decimal(values[key]) for key in ('H_Eh', 'S_J_mol_K', 'G_Eh'))
                self.assertLess(abs(h - t * s / conversion - g), Decimal('1e-40'))
                self.assertGreater(Decimal(r['components']['U_vib_' + scheme + '_J_mol']), 0)
            self.assertLess(Decimal(r['numerical_check']['energy_residual_J_mol']), Decimal('1e-7'))
            self.assertLess(Decimal(r['numerical_check']['entropy_residual_J_mol_K']), Decimal('1e-9'))

    def test_actual_sigma_changes_entropy_once(self):
        other = oracle.calculate(self.raw.replace(b'symmetry number 1.', b'symmetry number 2.'))
        with localcontext() as ctx:
            ctx.prec = 50
            expected = Decimal('8.3144621') * Decimal(2).ln()
            for scheme in ('RRHO', 'qRRHO'):
                difference = Decimal(self.result['results'][scheme]['S_J_mol_K']) - Decimal(other['results'][scheme]['S_J_mol_K'])
                self.assertLess(abs(difference - expected), Decimal('1e-35'))
                self.assertLess(abs(Decimal(other['results'][scheme]['H_Eh'])
                                    - Decimal(self.result['results'][scheme]['H_Eh'])), Decimal('1e-35'))

    def test_reported_numbers_are_not_numerical_inputs(self):
        changed = self.raw.replace(b'0.100000', b'0.999999').replace(b'0.000 0.000 0.000', b'9.000 8.000 7.000')
        other = oracle.calculate(changed)
        self.assertEqual(other['results'], self.result['results'])
        self.assertEqual(other['components'], self.result['components'])
        self.assertNotEqual(other['reported'], self.result['reported'])
        self.assertNotEqual(other['source_sha256'], self.result['source_sha256'])

    def test_frozen_constant_residual_is_explicit(self):
        r = self.result
        with localcontext() as ctx:
            ctx.prec = 50
            constants = r['constants']
            gas, k, h, c, na = (Decimal(constants[key]) for key in (
                'gas_constant_j_mol_k', 'boltzmann_j_k', 'planck_j_s', 'speed_of_light_cm_s', 'avogadro_mol'))
            expected = sum(Decimal(row['weight_HO']) * (na - gas / k) * h * c
                           * Decimal(row['frequency_cm1']) / 2 for row in r['modes'])
            actual = Decimal(r['numerical_check']['HG_constant_residual_J_mol'])
            self.assertNotEqual(actual, 0)
            self.assertLess(abs(actual - expected), Decimal('1e-12'))

    def test_caller_decimal_context_is_not_used_or_modified(self):
        with localcontext() as context:
            context.prec = 7
            context.rounding = ROUND_DOWN
            context.Emin, context.Emax = -10, 10
            context.traps[Inexact] = True
            before = str(context)
            actual = oracle.calculate(self.raw)
            self.assertEqual(str(getcontext()), before)
        self.assertEqual(actual, self.result)

    def test_invalid_logs_have_no_partial_result(self):
        mutations = (
            (b'Charge = 0', b'Charge = 1'), (b'Multiplicity = 1', b'Multiplicity = 3'),
            (b'NAtoms= 14', b'NAtoms= 13'), (b'100.0000', b'-100.0000'),
            (b'100.0000', b'0.0000'), (b'100.0000', b'NaN'),
            (b'100.0000', b'1e100000'), (b'1 2 3\n', b'1 2 4\n'),
            (b'298.150 Kelvin', b'300.000 Kelvin'), (b'1.00000 Atm', b'0.50000 Atm'),
            (b'symmetry number 1.', b'symmetry number 0.'),
            (b'58.1222 amu', b'-58.1222 amu'), (b'0.50000 0.15000 0.12000', b'0.00000 0.15000 0.12000'),
            (b'Normal termination of Gaussian', b'Error termination of Gaussian'),
            (b'Total 0.000 0.000 0.000', b''),
            (b'SCF Done:', b'no energy:'),
        )
        for old, new in mutations:
            with self.subTest(old=old, new=new), self.assertRaises(oracle.OracleError):
                oracle.calculate(self.raw.replace(old, new, 1))
        for raw in (b'', 'not bytes', self.raw + self.raw,
                    self.raw + b'Error termination\n', self.raw + b'Molecular mass: 58.1222 amu.\n',
                    self.raw + b'SCF Done: E(RTEST) = -157.125000 A.U.\n',
                    self.raw + b'E (Thermal) CV S\n', self.raw + b'\xff'):
            with self.subTest(raw_type=type(raw)), self.assertRaises(oracle.OracleError):
                oracle.calculate(raw)

    def test_malformed_records_cannot_hide_behind_valid_records_or_prefixes(self):
        replacements = (
            (b'Multiplicity = 1', b'Multiplicity = 1.5'),
            (b'Charge = 0', b'Charge = 0.5'),
            (b'symmetry number 1.', b'symmetry number 1.5'),
            (b'0.12000', b'0.12000junk'),
            (b'NAtoms= 14', b'NAtoms= 14.5'),
            (b'1.00000 Atm.', b'1.00000 Atm.junk'),
            (b'Zero-point correction= 0.100000', b'Zero-point correction= 0.100000junk'),
        )
        for old, new in replacements:
            with self.subTest(old=old, new=new), self.assertRaises(oracle.OracleError):
                oracle.calculate(self.raw.replace(old, new, 1))
        malformed = (
            b'SCF Done: E(RTEST) = NaN A.U.', b'Molecular mass: NaN amu.',
            b'Charge = 0 Multiplicity = NaN', b'NAtoms= NaN',
            b'Rotational symmetry number NaN.', b'Rotational temperatures (Kelvin) NaN',
            b'Temperature NaN Kelvin. Pressure 1.00000 Atm.',
            b'Zero-point correction= NaN', b'Thermal correction to Energy= NaN',
            b'E (Thermal) CV garbage', b'Frequencies --- NaN',
        )
        for line in malformed:
            with self.subTest(line=line), self.assertRaises(oracle.OracleError):
                oracle.calculate(self.raw + line + b'\n')

    def test_partition_function_table_is_not_the_thermal_table(self):
        extra = b' Charge= -0.0000 electrons\n Q Log10(Q) Ln(Q)\n Electronic 0.100000D+01 0.000000 0.000000\n Translational 0.173970D+08 7.240474 16.671808\n'
        result = oracle.calculate(self.raw.replace(b'Normal termination', extra + b'Normal termination'))
        self.assertEqual(result['reported'], self.result['reported'])
        self.assertEqual(result['results'], self.result['results'])

    def test_independent_module_import_inventory_and_detachment(self):
        tree = ast.parse(Path(oracle.__file__).read_text())
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module)
        self.assertEqual(set(imported), {'decimal', 'hashlib', 're'})
        value = oracle.calculate(self.raw)
        value['modes'][0]['frequency_cm1'] = '9999'
        self.assertEqual(oracle.calculate(self.raw), self.result)


if __name__ == '__main__':
    unittest.main()

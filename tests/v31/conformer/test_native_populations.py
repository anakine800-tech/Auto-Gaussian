"""Independent numerical and native pinned-persistence tests; no live effects."""
from contextlib import contextmanager
from dataclasses import asdict, replace
from decimal import Decimal, localcontext
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from auto_g16.conformer import populations_readonly as saved
from auto_g16.conformer import thermochemistry_readonly as pair_owner
from auto_g16.thermochemistry import native_populations as builder
from auto_g16.thermochemistry.models import _plain_value, _identified_payload
from tests.v31.conformer import test_successor_freq as fixture
from tests.v31.conformer import test_thermochemistry_readonly as pair_tests
from tests.v31.transport.test_publisher_pilot_orchestration import file_binding


def identified(payload):
    identity, digest = _identified_payload('native-populations', payload)
    return dict(schema=saved._SCHEMA, artifact_id=identity, payload_sha256=digest, payload=payload)


class PopulationMathTests(unittest.TestCase):
    def test_independent_decimal_absolute_partition_and_reference_shift(self):
        for energies in ((-158.0, -157.9991), (0., 0.), (-1., -.95)):
            for degeneracies in ((1, 2), (1, 1)):
                with localcontext() as ctx:
                    ctx.prec = 60
                    rt = 0.0009442
                    weights = [Decimal(g) * (-Decimal.from_float(e) / Decimal.from_float(rt)).exp()
                               for e, g in zip(energies, degeneracies)]
                    oracle = [float(w / sum(weights)) for w in weights]
                for reference in (0, 1):
                    rows, norm = builder._scheme(energies, degeneracies, reference, rt, 627.509541)
                    for row, expected in zip(rows, oracle):
                        self.assertAlmostEqual(row['normalized_population'], expected, delta=1e-12)
                    self.assertEqual(rows[reference]['delta_g_hartree'], 0)
                    self.assertLessEqual(norm['absolute_error'], 1e-12)
        base, _ = builder._scheme((0., .125), (1, 2), 0, .5, 1.)
        shifted, _ = builder._scheme((128., 128.125), (1, 2), 1, .5, 1.)
        self.assertEqual([x['normalized_population'] for x in base], [x['normalized_population'] for x in shifted])
        equal, _ = builder._scheme((0., 0.), (1, 2), 0, .5, 1.)
        self.assertAlmostEqual(equal[0]['normalized_population'], 1/3)

    def test_invalid_numerics_fail_before_weighting(self):
        for energies, gs, ref, rt, conversion in [((0., float('nan')), (1,2), 0, .1, 1.),
                ((0.,1.), (True,2), 0,.1,1.), ((0.,1.),(1,0),0,.1,1.),
                ((0.,1.),(1,2),True,.1,1.), ((0.,1.),(1,2),0,0.,1.),
                ((0.,1.),(1,2),0,.1,float('inf'))]:
            with self.subTest(energies=energies, gs=gs), self.assertRaises(ValueError):
                builder._scheme(energies, gs, ref, rt, conversion)


class NativePopulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = fixture.NativeThermochemistryTests()
        cls.addClassCleanup(cls.fixture.doCleanups)
        original_log = fixture.thermo_log
        def synthetic_log(**kwargs):
            anti = kwargs.get('coords', fixture.COORDS) == fixture.COORDS
            raw = original_log(**kwargs).replace(b'Rotational symmetry number 1.',
                b'Rotational symmetry number 2.' if anti else b'Rotational symmetry number 3.')
            return raw if anti else raw.replace(b'-158.000000 A.U.', b'-157.999000 A.U.')
        with patch.object(fixture, 'thermo_log', synthetic_log), \
                patch.object(fixture.NativeThermochemistryTests, 'freq_log_factory', staticmethod(synthetic_log)):
            cls.fixture.setUp()
        cls.fixture.request['member_policies'] = tuple({**row, 'degeneracy': g}
            for row, g in zip(cls.fixture.request['member_policies'], (1, 2)))
        cls.pair = cls.fixture.build()
        cls.pair_raw = pair_owner.encode_native_thermodynamic_pair(cls.pair)

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        pair_path = self.root / 'pair.json'
        pair_path.write_bytes(self.pair_raw)
        self.reader = pair_owner.NativeThermodynamicReadout(readout=self.fixture.readout, artifact=file_binding(pair_path))
        self.dest = self.root / 'destination'
        self.dest.mkdir()

    def build(self, reference='anti'):
        with fixture.inert_thermo_owners(), pair_tests.no_computation():
            return builder.build_native_populations(self.reader, reference_member_id=reference)

    def save(self, artifact):
        raw = saved.encode_native_populations(artifact)
        with fixture.inert_thermo_owners(), pair_tests.no_computation():
            return saved.save_native_populations(self.reader, artifact=artifact,
                expected_sha256=sha256(raw).hexdigest(), destination=pair_tests.destination(self.dest))

    def test_build_both_schemes_bind_sources_and_no_duplicate_symmetry(self):
        artifact = self.build()
        p = artifact['payload']
        self.assertEqual(p['source_pair_sha256'], self.reader.artifact.sha256)
        self.assertEqual(p['source_member_ids'], ('anti', 'gauche'))
        self.assertEqual(p['reference_member_id'], 'anti')
        for row, source in zip(p['members'], self.pair[1].member_observations):
            self.assertEqual(row['degeneracy'], source['degeneracy'])
            self.assertEqual(row['reported_rotational_symmetry_number'],
                             source['source_provenance']['thermo_facts']['rotational_symmetry_number']['value'])
            self.assertEqual(row['source_provenance'], source['source_provenance'])
            self.assertAlmostEqual(row['qrrho']['normalized_population'], source['normalized_population'], delta=1e-12)
            for scheme, key in (('rrho','raw_rrho'),('qrrho','treated_qrrho')):
                self.assertEqual(row[scheme]['gibbs_free_energy_hartree'], source[key]['gibbs_free_energy_hartree'])
        with self.assertRaises(TypeError): p['temperature_k'] = 0
        with self.assertRaises(ValueError): self.build('absent')
        second = self.build('gauche')
        for a,b in zip(p['members'], second['payload']['members']):
            for scheme in ('rrho','qrrho'):
                self.assertAlmostEqual(a[scheme]['normalized_population'],b[scheme]['normalized_population'],delta=1e-12)

    def test_exclusive_save_read_and_fresh_process_zero_compute(self):
        artifact = self.build()
        binding = self.save(artifact)
        self.assertEqual(Path(binding.path).stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError): self.save(artifact)
        reader = saved.NativePopulationReadout(thermodynamic_readout=self.reader, artifact=binding)
        with fixture.inert_thermo_owners(), pair_tests.no_computation(), \
                patch.object(builder, '_scheme', side_effect=AssertionError('read computed')):
            self.assertEqual(saved.encode_native_populations(reader.read()), Path(binding.path).read_bytes())
        helper = SimpleNamespace(root=self.root, readout=self.reader.readout)
        thermo_registration, _ = pair_tests.PairReadbackTests.registry(helper, self.reader.artifact)
        reg = pair_owner._canonical(dict(schema=saved._REGISTRATION,
            thermodynamic_registration=asdict(file_binding(thermo_registration)), artifact=asdict(binding)))
        path = self.root / 'population-registration.json'
        path.write_bytes(reg)
        script = '''
import sys
from pathlib import Path
from unittest.mock import patch
from auto_g16.conformer.populations_readonly import load_native_population_readout,encode_native_populations
from auto_g16.thermochemistry import native_populations as builder
from tests.v31.conformer.test_successor_freq import inert_thermo_owners
from tests.v31.conformer.test_thermochemistry_readonly import no_computation
with inert_thermo_owners(),no_computation(),patch.object(builder,'_scheme',side_effect=AssertionError('computed')):
    reader=load_native_population_readout(Path(sys.argv[1]).read_bytes(),sys.argv[2])
    raw=encode_native_populations(reader.read())
    assert raw==Path(reader.artifact.path).read_bytes()
    sys.stdout.buffer.write(raw)
'''
        result = subprocess.run([sys.executable,'-c',script,str(path),sha256(reg).hexdigest()],capture_output=True,timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stdout, saved.encode_native_populations(artifact))

    def test_rebound_source_member_policy_energy_and_bad_shapes_reject(self):
        artifact = self.build()
        variants = []
        for key,value in [('source_pair_sha256','0'*64),('reference_member_id','foreign'),
                          ('temperature_k',310.),('thermochemistry_policy_id','other'),('source_member_ids',['gauche','anti'])]:
            p=_plain_value(artifact['payload']);p[key]=value;variants.append(p)
        for key,value in [('degeneracy',3),('symmetry_rationale','foreign'),('reported_rotational_symmetry_number',99),
                          ('source_provenance',{})]:
            p=_plain_value(artifact['payload']);p['members'][0][key]=value;variants.append(p)
        for scheme,key,value in [('rrho','gibbs_free_energy_hartree',0.),('qrrho','normalized_population',0.),
                                 ('rrho','delta_g_hartree',True),('rrho','delta_g_hartree',float('inf'))]:
            p=_plain_value(artifact['payload']);p['members'][0][scheme][key]=value;variants.append(p)
        for p in variants:
            with self.subTest(keys=tuple(p)), self.assertRaises(ValueError):
                saved._validate_source(identified(p),self.pair,self.reader.artifact.sha256)
        for raw in [b'{"a":1,"a":2}',b'{}\n',b'{"n":NaN}']:
            with self.assertRaises(ValueError):pair_owner._decode(raw,pair_owner._CAP)

    def test_wrong_digest_symlink_and_replaced_artifact_fail_closed(self):
        artifact=self.build();raw=saved.encode_native_populations(artifact)
        with self.assertRaises(ValueError):
            saved.save_native_populations(self.reader,artifact=artifact,expected_sha256='0'*64,
                                           destination=pair_tests.destination(self.dest))
        self.assertEqual(list(self.dest.iterdir()),[])
        name='native-populations-'+sha256(raw).hexdigest()+'.json'
        (self.dest/name).symlink_to(self.root/'absent')
        with self.assertRaises(FileExistsError):self.save(artifact)
        other=self.root/'other';other.mkdir();self.dest=other
        binding=self.save(artifact);path=Path(binding.path);path.rename(path.with_suffix('.kept'))
        path.write_bytes(raw)
        with fixture.inert_thermo_owners(),self.assertRaises(Exception):
            saved.NativePopulationReadout(thermodynamic_readout=self.reader,artifact=binding).read()
        self.assertFalse(pair_owner.frequency.opt_reader._OPT_READ_LOCK.locked())

    def test_source_pin_remains_held_during_math(self):
        original=builder._scheme
        changed=False
        def swap(*args):
            nonlocal changed
            if not changed:
                path=Path(self.reader.artifact.path);path.rename(path.with_suffix('.retained'));path.write_bytes(self.pair_raw);changed=True
            return original(*args)
        with patch.object(builder,'_scheme',side_effect=swap),fixture.inert_thermo_owners(),self.assertRaises(Exception):
            builder.build_native_populations(self.reader,reference_member_id='anti')
        self.assertFalse(pair_owner.frequency.opt_reader._OPT_READ_LOCK.locked())

    def test_final_builder_every_number_against_independent_decimal(self):
        artifact = self.build()
        p = artifact['payload']
        self.assertEqual([m['degeneracy'] for m in p['members']], [1, 2])
        self.assertEqual([m['reported_rotational_symmetry_number'] for m in p['members']], [2, 3])
        t = self.pair[1]
        with localcontext() as context:
            context.prec = 60
            dec = Decimal.from_float
            rt = dec(t.gas_constant_binding['gas_constant_hartree_per_mol_k']) * dec(t.temperature_k)
            conversion = dec(t.gas_constant_binding['joule_per_hartree_mol']) / Decimal(4184)
            for scheme, key in (('rrho', 'raw_rrho'), ('qrrho', 'treated_qrrho')):
                energies = [dec(m[key]['gibbs_free_energy_hartree']) for m in t.member_observations]
                weights = [Decimal(g) * (-energy / rt).exp() for g, energy in zip((1, 2), energies)]
                self.assertNotEqual(energies[0], energies[1])
                for i, member in enumerate(p['members']):
                    delta = energies[i] - energies[0]
                    expected = dict(gibbs_free_energy_hartree=float(energies[i]), delta_g_hartree=float(delta),
                        delta_g_kcal_per_mol=float(delta * conversion),
                        log_relative_weight=float(Decimal((1, 2)[i]).ln() - delta / rt),
                        normalized_population=float(weights[i] / sum(weights)))
                    for number, value in expected.items():
                        self.assertAlmostEqual(member[scheme][number], value, delta=1e-12,
                                               msg=f'{scheme}/{i}/{number}')

    def test_caller_mutation_cannot_validate_different_publication_bytes(self):
        valid = self.build()
        payload = _plain_value(valid['payload'])
        payload['members'][0]['rrho']['gibbs_free_energy_hartree'] = 0.
        mutable = identified(payload)
        raw = saved.encode_native_populations(mutable)
        original = pair_owner._replayed_native_pair
        @contextmanager
        def changed_caller(reader):
            mutable.clear()
            mutable.update(_plain_value(valid))
            with original(reader) as pair:
                yield pair
        with fixture.inert_thermo_owners(), patch.object(pair_owner, '_replayed_native_pair', changed_caller), \
                self.assertRaisesRegex(ValueError, 'saved Gibbs energy'):
            saved.save_native_populations(self.reader, artifact=mutable, expected_sha256=sha256(raw).hexdigest(),
                                           destination=pair_tests.destination(self.dest))
        self.assertEqual(list(self.dest.iterdir()), [])
        self.assertFalse(pair_owner.frequency.opt_reader._OPT_READ_LOCK.locked())

    def test_save_source_or_directory_replacement_retains_created_file_and_closes(self):
        artifact = self.build()
        raw = saved.encode_native_populations(artifact)
        digest = sha256(raw).hexdigest()
        original = pair_owner._Directory._write_prefixed
        for mode in ('source', 'directory'):
            target = self.root / ('save-' + mode)
            target.mkdir()
            pair_path = self.root / ('pair-' + mode + '.json')
            pair_path.write_bytes(self.pair_raw)
            reader = replace(self.reader, artifact=file_binding(pair_path))
            calls = []
            def replace_after_write(directory, content, content_digest, prefix):
                result = original(directory, content, content_digest, prefix)
                calls.append(result)
                if mode == 'source':
                    pair_path.rename(pair_path.with_suffix('.retained'))
                    pair_path.write_bytes(self.pair_raw)
                else:
                    target.rename(target.with_name(target.name + '-retained'))
                    target.mkdir()
                return result
            descriptors = len(os.listdir('/dev/fd'))
            with fixture.inert_thermo_owners(), patch.object(pair_owner._Directory, '_write_prefixed', replace_after_write), \
                    self.assertRaises(Exception):
                saved.save_native_populations(reader, artifact=artifact, expected_sha256=digest,
                                               destination=pair_tests.destination(target))
            self.assertEqual(len(calls), 1)
            retained = target if mode == 'source' else target.with_name(target.name + '-retained')
            self.assertEqual((retained / ('native-populations-' + digest + '.json')).read_bytes(), raw)
            self.assertFalse(pair_owner.frequency.opt_reader._OPT_READ_LOCK.locked())
            self.assertEqual(len(os.listdir('/dev/fd')), descriptors)

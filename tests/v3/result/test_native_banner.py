"""Grammar-3 exact native banners; legacy grammar and bytes stay unchanged."""
import unittest
from dataclasses import replace

from auto_g16.result.gaussian_job import GaussianJobParser, _NativeGaussianJobParser
from auto_g16.result import ParseStatus, ResultBoundaryError
from auto_g16.result._successor import parse_source, append_pair, require_pair
from auto_g16.scientific_validation._successor_opt import assess_opt
from auto_g16.scientific_validation.service import _classify_gaussian_facts
from tests.v31.conformer.test_successor_result import opt_log, source_payload
from tests.v3.scientific_validation._fixtures import initialized_core
from tests.v3.result.test_gaussian_job import transcript


class NativeBannerTests(unittest.TestCase):
    def parse(self, raw, version='1.2.0'):
        return parse_source(source_payload(raw), raw, parser_version=version)

    def test_native_exact_bytes_and_legacy_default(self):
        for name in (b'g16', b'/g16', b'/opt/g16/g16', b'/a_1/b-2/c+3/d.4/g16'):
            for newline in (b'\n', b'\r\n'):
                raw = opt_log().replace(b'Link 0=g16', b'Link 0='+name).replace(b'\n', newline)
                source, result, envelope, parsed = self.parse(raw)
                self.assertEqual(parsed.parse_status, ParseStatus.PARSED)
                self.assertEqual(parsed.facts['grammar_id'], 'auto-g16-v3-gaussian-job-grammar/3')
                self.assertEqual(parsed.facts['job_section']['end'], len(raw))
                geometry, outcome = assess_opt(envelope, parsed)
                self.assertIsNotNone(geometry)
                self.assertEqual(outcome['classification'], 'INCOMPLETE')
                legacy = GaussianJobParser().parse(envelope, {'gaussian.log': raw})
                self.assertEqual(legacy.parser_version, '1.1.0')
                self.assertEqual(legacy.parse_status, ParseStatus.PARSED if name == b'g16' else ParseStatus.UNPARSEABLE)
                old_sv = _classify_gaussian_facts(envelope, parsed, lambda **fields: fields)
                self.assertEqual(old_sv['reason_code'], 'unsupported-result-tuple')
                for fact in parsed.facts['geometry_blocks']:
                    span = fact['source_span']
                    self.assertTrue(raw[span['start']:span['end']].startswith(b' Standard orientation:'))

    def test_bad_banners_do_not_skip_to_later_good_job(self):
        for name in (b'./g16', b'/a/../g16', b'/./g16', b'/a//g16', b'/a/g16 ',
                     b'"/a/g16"', b'/a;$x/g16', b'C:\\g16', b'g16.exe', b'/a/g16\x00'):
            bad = b' Entering Gaussian System, Link 0='+name+b'\n'
            parsed = self.parse(bad+opt_log())[3]
            self.assertNotEqual(parsed.parse_status, ParseStatus.PARSED)
        for prefix in (b'  ', b'\t'):
            parsed = self.parse(prefix+opt_log())[3]
            self.assertEqual(parsed.diagnostics, ('unsupported-valid-gaussian-grammar',))

    def test_other_program_second_job_echo_and_block_guards(self):
        for name in (b'g09', b'/opt/g09/g09', b'/g03'):
            raw = opt_log().replace(b'Link 0=g16', b'Link 0='+name)
            self.assertEqual(self.parse(raw)[3].diagnostics, ('unsupported-program',))
        native = b' Entering Gaussian System, Link 0=/opt/g16/g16\n'
        for raw in (opt_log()+native, opt_log().replace(b' Item Value', native+b' Item Value')):
            self.assertEqual(self.parse(raw)[3].diagnostics, ('unsupported-multiple-job',))
        echoed = opt_log().replace(b' Symbolic Z-matrix:', native+b' Symbolic Z-matrix:')
        self.assertEqual(self.parse(echoed)[3].parse_status, ParseStatus.PARSED)
        broken = opt_log().replace(b' Maximum Force 0.000001 0.000450 YES\n', native)
        self.assertEqual(self.parse(broken)[3].diagnostics, ('unparseable-orphan-anchor',))
        self.assertNotEqual(self.parse(opt_log()[:-50])[3].parse_status, ParseStatus.PARSED)

    def test_explicit_version_and_old_pair_conflict(self):
        raw = opt_log()
        old_source, old, _, _ = self.parse(raw, '1.1.0')
        new_source, new, _, _ = self.parse(raw)
        self.assertEqual(old_source, new_source)
        self.assertNotEqual(old.result_id, new.result_id)
        store = initialized_core()
        self.addCleanup(store.close)
        append_pair(store, old_source, old)
        with self.assertRaises(ResultBoundaryError):
            append_pair(store, new_source, new)
        require_pair(store, old_source, old)
        for bad in ('latest', '1.0.0', '1.3.0', None, True):
            with self.assertRaises(ResultBoundaryError):
                self.parse(raw, bad)
        parsed = self.parse(raw)[3]
        with self.assertRaises(ResultBoundaryError):
            replace(parsed, facts={**parsed.facts, 'grammar_id': 'auto-g16-v3-gaussian-job-grammar/2'})

    def test_malformed_banner_preserves_child_block_error_precedence(self):
        malformed = b' Entering Gaussian System, Link 0=/a/../g16'
        for index in (11, 18, 22, 24, 29, 32):
            raw = transcript(replacements={index: malformed})
            old = self.parse(raw, '1.1.0')[3]
            native = self.parse(raw)[3]
            self.assertNotEqual(native.parse_status, ParseStatus.PARSED)
            self.assertNotEqual(native.diagnostics, ('unsupported-valid-gaussian-grammar',))
            self.assertEqual(native.diagnostics, old.diagnostics)

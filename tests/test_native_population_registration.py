"""Startup descriptor wiring; real saved-artifact acceptance remains separate."""
from contextlib import contextmanager, ExitStack
import hashlib
import json
import sys
import types
import unittest
from unittest.mock import Mock, patch
from tests import test_native_sources as fixture
from autog_frontend.native_sources import load_native_sources
from autog_frontend.archive import read_pinned
from auto_g16.query import QueryError


class PopulationRegistrationTests(unittest.TestCase):
    setUp = fixture.NativeRegistrationTests.setUp
    write = fixture.NativeRegistrationTests.write

    def v5(self):
        self.data['schema']='autog-native-source-registration/5'
        entry=self.data['sources'][0]
        entry.update(opt_readout=None,freq_readout=None,thermodynamic_readout=None,population_readout=None)
        return entry

    def descriptor(self, name, raw=b'{"synthetic":"registration"}'):
        path=self.root/name
        path.write_bytes(raw)
        return dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest())

    @contextmanager
    def wired(self):
        """Isolate frontend forwarding; do not claim owning reader validation."""
        self.entry=self.v5()
        for key in ('freq_readout','thermodynamic_readout','population_readout'):
            self.entry[key]=self.descriptor(key+'.json')
        self.population=object()
        module=types.ModuleType('auto_g16.conformer.populations_readonly')
        module.load_native_population_readout=Mock(return_value=self.population)
        with ExitStack() as stack:
            stack.enter_context(patch.dict(sys.modules,{module.__name__:module}))
            stack.enter_context(patch('autog_frontend.native_sources.load_freq_readout',return_value=object()))
            stack.enter_context(patch('auto_g16.conformer.thermochemistry_readonly.load_native_thermodynamic_readout',return_value=object()))
            source=stack.enter_context(patch('autog_frontend.native_sources.NativeSource'))
            stack.enter_context(patch('autog_frontend.native_sources.NativeQueryService'))
            pinned=stack.enter_context(patch('autog_frontend.native_sources.read_pinned',wraps=read_pinned))
            yield module.load_native_population_readout,source,pinned

    def test_null_keeps_old_backend_shape_without_import_or_database(self):
        self.v5()
        with patch.dict(sys.modules,{'auto_g16.conformer.populations_readonly':None}):
            result=load_native_sources(self.path,self.write())
        self.assertIsNone(result[0].thermodynamic_readout)
        self.assertFalse(result[0].database.exists())
        with patch('autog_frontend.native_sources.NativeSource') as source, patch('autog_frontend.native_sources.NativeQueryService'):
            load_native_sources(self.path,self.write())
            self.assertNotIn('population_readout',source.call_args.kwargs)

    def test_v5_exact_keys_and_old_versions_reject_population_field(self):
        entry=self.v5()
        for key in list(entry):
            value=entry.pop(key)
            with self.subTest(missing=key),self.assertRaises(ValueError):load_native_sources(self.path,self.write())
            entry[key]=value
        entry['extra']=None
        with self.assertRaises(ValueError):load_native_sources(self.path,self.write())
        for version in range(1,5):
            entry=self.v5();entry.pop('extra',None)
            self.data['schema']=f'autog-native-source-registration/{version}'
            if version<4:entry.pop('thermodynamic_readout')
            if version<3:entry.pop('freq_readout')
            if version<2:entry.pop('opt_readout')
            with self.subTest(version=version),self.assertRaises(ValueError):load_native_sources(self.path,self.write())

    def test_exact_bytes_digest_limit_and_reader_forwarding_no_result_read(self):
        with self.wired() as (loader,source,pinned):
            load_native_sources(self.path,self.write())
            loader.assert_called_once_with(b'{"synthetic":"registration"}',self.entry['population_readout']['sha256'])
            self.assertIs(source.call_args.kwargs['population_readout'],self.population)
            self.assertEqual(pinned.call_args.kwargs,{'limit':1024*1024})
            self.assertFalse((self.root/'absent.sqlite3').exists())

    def test_requires_both_existing_registrations_before_population_loader(self):
        for key in ('freq_readout','thermodynamic_readout'):
            with self.wired() as (loader,source,_):
                self.entry[key]=None
                with self.assertRaisesRegex(ValueError,'requires thermodynamic and Freq'):
                    load_native_sources(self.path,self.write())
                loader.assert_not_called();source.assert_not_called()

    def test_bad_descriptors_hash_limit_symlink_and_relative_path(self):
        with self.wired() as (loader,source,_):
            good=self.entry['population_readout'].copy()
            link=self.root/'link.json';link.symlink_to(good['path'])
            oversized=self.descriptor('large.json',b'x'*(1024*1024+1))
            for bad in ({},[],{**good,'path':3},{**good,'sha256':False},{**good,'extra':True},
                        {**good,'sha256':'0'*64},{**good,'sha256':good['sha256'].upper()},
                        {**good,'path':str(link)},{**good,'path':'relative.json'},oversized):
                self.entry['population_readout']=bad
                with self.subTest(descriptor=bad),self.assertRaises(ValueError):load_native_sources(self.path,self.write())
            loader.assert_not_called();source.assert_not_called()

    def test_duplicate_population_and_nested_descriptor_keys(self):
        with self.wired() as (loader,source,_):
            raw=json.dumps(self.data).replace('"population_readout":', '"population_readout": null, "population_readout":').encode()
            self.path.write_bytes(raw)
            with self.assertRaises(ValueError):load_native_sources(self.path,hashlib.sha256(raw).hexdigest())
            raw=json.dumps(self.data).replace('"path":', '"path": "duplicate", "path":').encode()
            self.path.write_bytes(raw)
            with self.assertRaises(ValueError):load_native_sources(self.path,hashlib.sha256(raw).hexdigest())
            loader.assert_not_called();source.assert_not_called()

    def test_missing_loader_fails_closed_for_requested_registration(self):
        with self.wired() as (_,source,_),patch.dict(sys.modules,{'auto_g16.conformer.populations_readonly':None}):
            with self.assertRaises(ImportError):load_native_sources(self.path,self.write())
            source.assert_not_called()

    def test_owning_loader_and_binding_errors_propagate_without_downgrade(self):
        with self.wired() as (loader,source,_):
            loader.side_effect=ValueError('invalid startup binding')
            with self.assertRaises(ValueError):load_native_sources(self.path,self.write())
            source.assert_not_called()
            loader.side_effect=None
            source.side_effect=QueryError('invalid-population-registration')
            with self.assertRaises(QueryError):load_native_sources(self.path,self.write())

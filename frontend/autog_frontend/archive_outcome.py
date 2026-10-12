"""Archive-only outcomes, never persisted as Core ParseOutcome records.

Facts retain the public attributed-facts shape. Its public constructor is used
as a structural validator on a temporary shape projection, NOT as an assertion
that the upstream parser ran. Stored identity/grammar always name this adapter.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
from types import MappingProxyType
from auto_g16.result import ParseOutcome, ParseStatus
from .archive_import import plain

SCHEMA = 'autog-local-parse-outcome/1'
GRAMMAR = 'autog-local-gaussian-job-grammar/1'

@dataclass(frozen=True, kw_only=True)
class ArchiveParseOutcome:
    attempt_id: str
    envelope_observation_id: str
    parser_name: str
    parser_version: str
    result_kind: str
    parse_status: ParseStatus
    facts: object
    diagnostics: tuple

    def __post_init__(self):
        if (self.parser_name,self.parser_version,self.result_kind) != ('autog-local-gaussian-job','1.0.0','gaussian-job-facts'):
            raise ValueError('unsupported archive parser')
        facts = plain(self.facts)
        if facts:
            if facts.get('grammar_id') != GRAMMAR: raise ValueError('wrong archive grammar')
            facts['grammar_id'] = 'auto-g16-v3-gaussian-job-grammar/2'
        shape = ParseOutcome(attempt_id=self.attempt_id,envelope_observation_id=self.envelope_observation_id,
            parser_name='auto-g16-v3-gaussian-job',parser_version='1.1.0',result_kind=self.result_kind,
            parse_status=self.parse_status,facts=facts,diagnostics=self.diagnostics)
        object.__setattr__(self,'parse_status',shape.parse_status)
        object.__setattr__(self,'diagnostics',shape.diagnostics)
        object.__setattr__(self,'facts',MappingProxyType({**shape.facts,'grammar_id':GRAMMAR}) if shape.facts else MappingProxyType({}))

    def payload(self):
        return {'schema':SCHEMA,**{k:(getattr(self,k).value if k=='parse_status' else plain(getattr(self,k))) for k in self.__dataclass_fields__}}

    @property
    def result_id(self):
        return 'archive-result-' + sha256(json.dumps(self.payload(),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

    @classmethod
    def from_payload(cls,value):
        if not isinstance(value,dict) or set(value) != {'schema',*cls.__dataclass_fields__} or value['schema'] != SCHEMA:
            raise ValueError('invalid archive outcome')
        return cls(**{k:value[k] for k in cls.__dataclass_fields__})

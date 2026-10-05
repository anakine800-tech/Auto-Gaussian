"""Pinned, detached two-stage readout. Only trusted local startup registers paths."""
from contextlib import ExitStack
from dataclasses import dataclass
from hashlib import sha256
from inspect import signature
import json

from auto_g16.core import SQLiteRuntimeStore
from auto_g16.execution._receipt_source import _gaussian_receipt_sources
from auto_g16.execution.program import _decode_program_review_semantics
from auto_g16.execution._gaussian_result_source import gaussian_freq_result_source
from auto_g16.transport._program_rtwin import _PublisherFileBinding, _PinnedPublisherFile
from auto_g16.transport.program import _ProgramTransportStore
from auto_g16.result._successor import parse_freq_source, require_pair, _plain, payload_hash
from . import readonly as opt_reader
from .models import SamplingProfile, ConformerEnsemble
from .refinement_authority import _require
from ._successor_freq import refine_freq_ensemble


def _frequency_counts(parsed):
    if parsed.parse_status.value != "parsed" or not parsed.facts:
        return {"frequency_count":None,"imaginary_frequency_count":None,"zero_frequency_count":None,
                "frequency_count_availability":"unavailable","frequency_count_reason":"frequency-facts-not-parsed"}
    values=parsed.facts["frequencies_cm-1"]
    return {"frequency_count":len(values),"imaginary_frequency_count":sum(v<0 for v in values),
            "zero_frequency_count":sum(v==0 for v in values),"frequency_count_availability":"available","frequency_count_reason":None}


def load_freq_readout(content: bytes, digest: str):
    _require(type(content) is bytes and len(content)<=2*1024*1024
             and sha256(content).hexdigest()==digest,"invalid Freq registry digest")
    def pairs(items):
        result={}
        for k,v in items:
            _require(k not in result,"duplicate Freq registry key")
            result[k]=v
        return result
    data=json.loads(content,object_pairs_hook=pairs)
    _require(type(data) is dict and set(data)=={"schema","material","optimization_sources","frequency_sources"}
             and data["schema"] in {"auto-g16-freq-readout-registration/1", "auto-g16-freq-readout-registration/2"},"Freq registry fields differ")
    # Decode the unchanged closed physical bindings with the owning startup decoder.
    def decode(rows, associated=False):
        raw=json.dumps({"schema":"auto-g16-opt-readout-registration/1","material":data["material"],"sources":rows}).encode()
        return opt_reader._load_readout(raw,sha256(raw).hexdigest(), associated=associated)
    optimization,frequency=decode(data["optimization_sources"]),decode(data["frequency_sources"], associated=data["schema"].endswith("/2"))
    return FreqReadout(material=optimization.material,optimization_sources=optimization.sources,
                       frequency_sources=frequency.sources)


@dataclass(frozen=True,kw_only=True)
class FreqReadout:
    material: _PublisherFileBinding
    optimization_sources: tuple[opt_reader.OptMemberSource,...]
    frequency_sources: tuple[opt_reader.OptMemberSource,...]

    def __post_init__(self):
        for sources in (self.optimization_sources,self.frequency_sources):
            opt_reader.OptReadout(material=self.material,sources=sources)
        combined=(*self.optimization_sources,*self.frequency_sources)
        _require(len({s.snapshot.attempt_id for s in combined})==len(combined),"duplicate stage Attempt")
        _require({s.member_id for s in self.frequency_sources}<={s.member_id for s in self.optimization_sources},
                 "Freq member has no Opt registration")
        for item in self.frequency_sources:
            snapshot=_decode_program_review_semantics(json.loads(item.snapshot.content))
            _require(snapshot.program_execution_spec.adapter_contract_version==7 and item.parser_version=="1.2.0",
                     "Freq registration tuple differs")

    def source_for(self,attempt_id):
        selected=[s for s in self.frequency_sources if s.snapshot.attempt_id==attempt_id]
        _require(len(selected)==1,"Freq readout Attempt not registered")
        return selected[0]

    def read(self,store,attempt_id):
        # The same process-wide slot owns both stages; do not nest OptReadout.read.
        if not opt_reader._OPT_READ_LOCK.acquire(timeout=opt_reader._OPT_READ_WAIT_SECONDS):
            raise opt_reader.OptReadBusy("two-stage read slot is busy")
        try:
            return self._read_serial(store,attempt_id)
        finally:
            opt_reader._OPT_READ_LOCK.release()

    def _read_serial(self,store,attempt_id):
        selected=self.source_for(attempt_id)
        with ExitStack() as stack:
            pins=[]
            def pin(binding):
                value=_PinnedPublisherFile(binding,64*1024*1024);stack.callback(value.close);pins.append(value)
                return value.raw
            def pairs(items):
                d={}
                for k,v in items:
                    _require(k not in d,"duplicate Freq material key");d[k]=v
                return d
            material=json.loads(pin(self.material),object_pairs_hook=pairs)
            _require(set(material)=={"profile","original","opt_refined","history","prior","refined"},"Freq material fields differ")
            def restore(factory,payload,**extra):
                value=factory(**extra,**{k:payload[k] for k in signature(factory).parameters if k in payload})
                _require(_plain(value._identity_payload())==payload,"Freq material identity differs")
                return value
            profile=restore(SamplingProfile._create,material["profile"])
            def ensemble(payload):
                return restore(ConformerEnsemble._create,payload,profile=profile)
            original=ensemble(material["original"]);prior=ensemble(material["prior"])
            def opened(item):
                pin(item.revision)
                source=SQLiteRuntimeStore._open_readonly_existing(item.original.core.path);stack.callback(source.close)
                transport=_ProgramTransportStore._open_readonly_existing(item.original.transport.path,approved_root=item.transport_root)
                stack.callback(transport.close)
                dest=stack.enter_context(SQLiteRuntimeStore.read_snapshot(item.revision.path))
                if item is selected:
                    _require(store._connection.serialize()==dest._connection.serialize(),"query view differs from Freq revision")
                return dict(source_store=source,transport_store=transport,destination=dest,
                    snapshot=_decode_program_review_semantics(json.loads(item.snapshot.content)),parser_version=item.parser_version)
            opts={s.member_id:opened(s) for s in self.optimization_sources}
            freqs={s.member_id:opened(s) for s in self.frequency_sources}
            inputs=[dict(member_id=mid,optimization=args,frequency=freqs.get(mid)) for mid,args in opts.items()]
            sources=(*self.optimization_sources,*self.frequency_sources)
            with _gaussian_receipt_sources(tuple(s.original for s in sources)):
                from ._successor_opt import refine_opt_ensemble
                opt=refine_opt_ensemble(original,profile,inputs=[dict(member_id=mid,**args) for mid,args in opts.items()])
                _require(_plain(opt._identity_payload())==material["opt_refined"],"registered Opt revision differs")
                refined=refine_freq_ensemble(prior,profile,optimization_ensemble=original,inputs=inputs,
                                             history=[ensemble(p) for p in material["history"]])
                _require(_plain(refined._identity_payload())==material["refined"],"registered Freq refinement differs")
                args=freqs[selected.member_id]
                with gaussian_freq_result_source(args["source_store"],snapshot=args["snapshot"],transport_store=args["transport_store"]) as (_,payload,_,log):
                    observation,result,_,parsed=parse_freq_source(payload,log)
                    require_pair(store,observation,result)
            member=next(m for m in refined.members if m["member_id"]==selected.member_id)
            authority=member["two_stage_minimum_authority"] or member["negative_frequency_authority"]
            facts=parsed.facts
            values=facts.get("frequencies_cm-1",())
            projection=_plain({"source":"Result:"+result.result_id,
                "provenance":{"source_observation_id":observation.observation_id,"source_payload_sha256":payload_hash(observation.data),
                    "parsed_result_id":result.result_id,"parsed_payload_sha256":payload_hash(result.data),
                    "parser_name":parsed.parser_name,"parser_version":parsed.parser_version,"input":payload["input"],"log":payload["log"],
                    "optimization_attempt_id":opts[selected.member_id]["snapshot"].attempt_id,"frequency_attempt_id":attempt_id,
                    **_frequency_counts(parsed),
                    "frequency_unit":"cm^-1","two_stage_minimum_authority_id":authority["two_stage_minimum_authority_id"]},
                "energy":facts.get("final_energy_hartree"),"geometry":facts.get("geometry_blocks",()),
                "frequencies":facts.get("frequency_blocks",()),"assessment":authority["assessment"],
                "optimization":{"scope":"Opt and Freq machine evidence; ScientificAcceptance and thermodynamics pending",
                    "optimization_authority_id":authority["optimization"]["optimization_geometry_authority_id"],
                    "ensemble":{"conformer_ensemble_id":refined.conformer_ensemble_id,"payload_sha256":refined.payload_sha256,
                        "revision":refined.revision,"supersedes_conformer_ensemble_id":prior.conformer_ensemble_id,
                        "member_id":selected.member_id,"status":member["post_dft_status"],
                        "members":[{"member_id":m["member_id"],"status":m["post_dft_status"]} for m in refined.members],
                        "thermodynamic_eligible_members":(),"ts_seed_members":(),"audit":refined.audit_evidence,"dedup":refined.dedup_decisions}}})
            for value in pins:value._read_and_check()
            return projection

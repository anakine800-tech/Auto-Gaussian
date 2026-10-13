"""Native, source-replayed Opt -> Freq evidence; never a V30 acceptance."""
from collections.abc import Mapping
import re
from auto_g16.execution._gaussian_result_source import gaussian_freq_result_source
from auto_g16.execution._gaussian_freq_resources import ROUTE
from auto_g16.result._successor import (parse_freq_source, require_pair, payload_hash,
                                       FREQ_SOURCE, FREQ_PARSED)
from auto_g16.scientific_validation._successor_freq import assess_frequency
from .models import ConformerEnsemble, _freeze_mapping
from .refinement_authority import _require, _member, _source, _coordinates_from_geometry
from ._successor_opt import (read_opt_authority, _same_destination, _input_member,
                            _output_method, _record_payload, _import_result_revision)

SCHEMA = "v31-conformer-successor-two-stage-minimum-authority/1"
SCHEMA_V2 = "v31-conformer-successor-two-stage-minimum-authority/2"


def optimization_link(opt):
    """Closed scientific plan linkage; evaluated only after original proof replay."""
    return {"optimization_geometry_authority_id": opt["optimization_geometry_authority_id"],
            "optimization_geometry_sha256": payload_hash(opt["selected_geometry"]),
            "optimization_result_id": opt["parsed_result"]["result_id"],
            "optimization_source_artifact_sha256": opt["selected_geometry"]["source_span"]["sha256"],
            "optimization_selected_geometry_span_sha256": payload_hash(opt["selected_geometry"]["source_span"])}


def _inputs(value):
    _require(isinstance(value, Mapping) and {"source_store", "snapshot", "transport_store", "destination"} <= set(value)
             <= {"source_store", "snapshot", "transport_store", "destination", "validation_driver", "parser_version"},
             "stage source inputs are not closed")
    return dict(value)


def read_two_stage_authority(ensemble, member_id, *, optimization, frequency, authority_schema=SCHEMA):
    _require(authority_schema in (SCHEMA, SCHEMA_V2), "unknown Freq authority schema")
    optimization, frequency = _inputs(optimization), _inputs(frequency)
    _require(optimization["snapshot"].attempt_id != frequency["snapshot"].attempt_id,
             "Opt and Freq must be distinct Attempts")
    opt = read_opt_authority(ensemble, member_id, **optimization)
    _require(opt["assessment"]["geometry_disposition"] == "accepted_opt_geometry", "Freq requires positive Opt geometry")
    member = _member(ensemble, member_id)
    species = ensemble.species_binding
    order = tuple(species["atom_order"])
    heavy = {frozenset((order.index(a),order.index(b))) for a,b,bond in species["bonds"]
             if order.index(a)<4 and order.index(b)<4 and bond==1.0}
    degrees = [0]*14
    valid_bonds = len(species["bonds"]) == 13
    for a,b,bond in species["bonds"]:
        i,j=order.index(a),order.index(b)
        valid_bonds = valid_bonds and bond==1.0 and i != j and (i<4 or j<4)
        if i < 14 and j < 14:
            degrees[i]+=1; degrees[j]+=1
    _require(valid_bonds and heavy=={frozenset((0,1)),frozenset((1,2)),frozenset((2,3))}
             and degrees==[4]*4+[1]*10 and species["formal_charge"]==0 and species["multiplicity"]==1,
             "Freq graph is not mapped neutral n-butane")
    _require(tuple(species["elements"]) == ("C",)*4+("H",)*10
             and species["component_count"] == 1, "Freq supports the closed n-butane domain")
    snapshot = frequency["snapshot"]
    _require(snapshot.project_physical_binding.project_id == optimization["snapshot"].project_physical_binding.project_id,
             "Opt/Freq execution Project differs")
    _require(frequency.get("parser_version", "1.2.0") == "1.2.0", "Freq parser version differs")
    with gaussian_freq_result_source(frequency["source_store"], snapshot=snapshot,
            transport_store=frequency["transport_store"], validation_driver=frequency.get("validation_driver")) as (source, payload, inp, log):
        _same_destination(source, frequency["destination"], snapshot, record_types=(FREQ_SOURCE, FREQ_PARSED))
        observation, result, envelope, parsed = parse_freq_source(payload, log)
        require_pair(frequency["destination"], observation, result)
        plan = source.load_calculation_plan(snapshot.calculation_plan_id)
        _require(plan.intent.get("optimization_source") == optimization_link(opt), "Freq plan does not bind exact Opt lineage")
        coordinates = _coordinates_from_geometry(opt["selected_geometry"], species["elements"])
        _input_member(ensemble, {**member, "coordinates_angstrom":coordinates}, inp, expected_route=ROUTE)
        # Both inputs are exact closed routes; method equality excludes stage-specific route versions.
        method = {k:v for k,v in opt["method_binding"].items() if k != "route_contract_version"}
        _require(plan.intent.get("method_binding") == method, "Freq scientific plan method differs from Opt")
        tail = None
        if (authority_schema == SCHEMA_V2 and parsed.parse_status.value == "parsed"
                and envelope.capture_completeness.value == "complete"
                and parsed.facts["normal_termination_count"] == 1
                and parsed.facts["error_termination_count"] == 0):
            from ._freq_tail import frequency_tail
            tail = frequency_tail(log, parsed.facts)
        geometry, assessment = assess_frequency(envelope, parsed, opt["selected_geometry"],
            policy="v31-successor-two-stage-minimum/2" if authority_schema == SCHEMA_V2 else "v31-successor-two-stage-minimum/1",
            tail_evidence=tail)
        if parsed.parse_status.value == "parsed" and parsed.facts.get("scf_calculations"):
            _output_method(log, parsed)
            basis = re.findall(rb"^\s*Standard basis:\s*(.+)$", log, re.M)
            _require(bool(basis) and all(b.strip() == b"def2SVP (5D, 7F)" for b in basis), "Freq output basis differs")
        if assessment["classification"] == "VALIDATED_TWO_STAGE_MINIMUM":
            _require(bool(parsed.facts.get("scf_calculations")), "Freq output lacks method evidence")
        facts = parsed.facts
        value = {"authority_schema":authority_schema, "source":_source(ensemble,member),
            "method_binding":method, "method_id":payload_hash({"domain":"v31-successor-stage-independent-method/1", "method":method}),
            "optimization":opt,
            "frequency":{"calculation_plan":{"calculation_plan_id":plan.calculation_plan_id,"revision":plan.revision,
                                                "payload_sha256":payload_hash(_record_payload(plan))},
                         "input":payload["input"],
                         "result_source":{"observation_id":observation.observation_id,"payload_sha256":payload_hash(observation.data)},
                         "parsed_result":{"result_id":result.result_id,"payload_sha256":payload_hash(result.data)},
                         "selected_geometry":geometry, "frequency_blocks":facts.get("frequency_blocks",()),
                         "frequencies_cm1":facts.get("frequencies_cm-1",()), "mode_count":facts.get("frequency_count",0)},
            "assessment":assessment}
        if authority_schema == SCHEMA_V2:
            value["frequency"]["tail_evidence"] = tail
        return _freeze_mapping({**value,"two_stage_minimum_authority_id":payload_hash({"domain":authority_schema,"payload":value})},"successor two-stage authority")


def import_freq_result_revision(*, source_store, snapshot, transport_store, destination_path,
                                output_path, approved_root, validation_driver=None, parser_version="1.2.0"):
    return _import_result_revision(source_store=source_store,snapshot=snapshot,transport_store=transport_store,
        destination_path=destination_path,output_path=output_path,approved_root=approved_root,
        validation_driver=validation_driver,parser_version=parser_version,source_reader=gaussian_freq_result_source,
        parser=parse_freq_source,record_types=(FREQ_SOURCE,FREQ_PARSED))


def refine_freq_ensemble(prior, profile, *, optimization_ensemble, inputs, history=(), authority_schema=SCHEMA):
    """Publish a new value; replay every claimed positive or negative Freq member."""
    from .refinement import _closed_ensemble, _closed_profile, _audit_and_deduplicate, _sampling_observation_by_member
    from ._successor_opt import refine_opt_ensemble
    _require(authority_schema in (SCHEMA, SCHEMA_V2), "unknown Freq authority schema")
    _closed_ensemble(prior); _closed_ensemble(optimization_ensemble); _closed_profile(profile)
    _require(bool(inputs) and isinstance(inputs,(tuple,list)), "Freq refinement requires stage sources")
    ids=set(); attempts=set(); authorities={}; opt_inputs=[]
    for item in inputs:
        _require(isinstance(item,Mapping) and set(item)=={"member_id","optimization","frequency"}, "Freq refinement fields differ")
        mid=item["member_id"]; _require(mid not in ids,"duplicate Freq member");ids.add(mid)
        opt_inputs.append({"member_id":mid,**_inputs(item["optimization"])})
        if item["frequency"] is not None:
            fid=item["frequency"]["snapshot"].attempt_id
            _require(fid not in attempts,"one Freq Attempt cannot validate two members");attempts.add(fid)
            authorities[mid]=read_two_stage_authority(optimization_ensemble,mid,optimization=item["optimization"],frequency=item["frequency"],authority_schema=authority_schema)
    _require(ids=={m["member_id"] for m in prior.members},"every retained member needs an explicit Opt source")
    fresh=refine_opt_ensemble(optimization_ensemble,profile,inputs=opt_inputs)
    _require(isinstance(history,(tuple,list)) and len(history) <= 32, "invalid Freq revision history")
    cursor = fresh
    retained = (*history, prior) if prior.conformer_ensemble_id != fresh.conformer_ensemble_id else history
    for revision in retained:
        _closed_ensemble(revision)
        previous = {}
        for member in revision.members:
            claimed = member.get("two_stage_minimum_authority") or member.get("negative_frequency_authority")
            if claimed is not None:
                item = next(i for i in inputs if i["member_id"] == member["member_id"])
                _require(item["frequency"] is not None, "retained Freq source is missing")
                current = read_two_stage_authority(optimization_ensemble, member["member_id"],
                    optimization=item["optimization"], frequency=item["frequency"],
                    authority_schema=claimed["authority_schema"])
                _require(current == claimed, "retained Freq authority differs from original source replay")
                previous[member["member_id"]] = current
        replayed = _apply_frequency(cursor,profile,previous)
        _require(replayed._identity_payload()==revision._identity_payload(), "retained Freq revision differs from full replay")
        cursor = replayed
    _require(cursor._identity_payload()==prior._identity_payload(), "retained ensemble differs from full replay")
    _require(bool(authorities), "Freq refinement requires at least one current Freq source")
    return _apply_frequency(prior,profile,authorities)


def _apply_frequency(prior,profile,authorities):
    from .refinement import _audit_and_deduplicate, _sampling_observation_by_member
    coordinates={m["member_id"]:m["coordinates_angstrom"] for m in prior.members if m["optimization_geometry_authority"] is not None}
    rejected, comparisons, blockers, clusters, reps, survivors=_audit_and_deduplicate(prior,profile,_sampling_observation_by_member(prior),coordinates)
    members=[];audit=[];negative=[]
    for old in prior.members:
        mid=old["member_id"];a=authorities.get(mid)
        if a is None:
            _require(old["post_dft_status"]=="optimized_frequency_pending","unreplayed Freq disposition cannot be promoted")
            members.append(old);continue
        passed=a["assessment"]["classification"]=="VALIDATED_TWO_STAGE_MINIMUM" and mid not in rejected
        status="validated_minimum" if passed else "frequency_failed"
        member={**old,"post_dft_status":status,"post_dft_minimum_evidence_available":passed,
                "two_stage_minimum_authority":a if passed else None,"negative_frequency_authority":None if passed else a}
        members.append(member)
        row={"member_id":mid,"stage":"successor_freq_refinement","status":status,
             "two_stage_minimum_authority_id":a["two_stage_minimum_authority_id"],"assessment":a["assessment"]}
        audit.append(row)
        if not passed:negative.append({**row,"retained_as_negative_evidence":True})
    return ConformerEnsemble._create(project_id=prior.project_id,calculation_plan_id=prior.calculation_plan_id,
        calculation_plan_revision=prior.calculation_plan_revision,profile=profile,sampling_observations=prior.sampling_observations,
        audit_evidence=(*prior.audit_evidence,*audit),negative_evidence=(*prior.negative_evidence,*negative),
        dedup_decisions=(*prior.dedup_decisions,*comparisons),independent_review_blockers=(*prior.independent_review_blockers,*blockers),
        clusters=prior.clusters,members=members,coverage=prior.coverage,thermodynamic_eligible_members=(),ts_seed_members=(),
        revision=prior.revision+1,supersedes_conformer_ensemble_id=prior.conformer_ensemble_id)

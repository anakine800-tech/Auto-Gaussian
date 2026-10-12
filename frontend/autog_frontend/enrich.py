"""Publish additional condition/grouping sidecars without reparsing existing Results."""
import argparse,json,uuid
from pathlib import Path
from hashlib import sha256
from .archive import read_pinned,LOG_LIMIT,LIMIT
from .details import document,read_json
from .conditions import extract
from .project_catalog import memberships

def additions(records,entries,manifest,source_label,save,read=document):
    groups=memberships(manifest,source_label)
    from .workflow_evidence import build
    workflows=build(manifest,read)
    for record in records:
        identity=record['archive_id'];e=entries[('archive',identity)];log=next(x for x in record['artifacts'] if x['role']=='log')
        packet=extract(read(e['log'],limit=LOG_LIMIT),log['logical_name'])
        from .calculation_analysis import extract as analysis
        try:
            e['analysis']=save('analysis/'+identity+'.json',analysis(read(e['log'],limit=LOG_LIMIT),log['logical_name']))
        except (ValueError, UnicodeError):
            # Keep archive ingestion usable for unsupported or oversized trajectories.
            e.pop('analysis',None)
        if identity in workflows:e['workflow']=save('workflow/'+identity+'.json',workflows[identity])
        e['conditions']=save('conditions/'+identity+'.json',packet)
        e['browse']=save('browse/'+identity+'.json',dict(schema='autog-browse-membership/1',id=identity,memberships=groups.get(identity,[])))
        inputs=[]
        if 'history_links' in e:
            history=json.loads(read(e['history_links']))
            seen=set()
            for candidate in history['candidates']:
                for item in candidate['inputs']:
                    ref=item['artifact']
                    if ref['sha256'] in seen:continue
                    seen.add(ref['sha256']);raw=read(ref)
                    inputs.append(dict(name=item['name'],input=ref,log_binding='unknown',submission_binding='sha256-verified',conditions=extract(raw,item['name'],input_file=True)))
        seen={x['input']['sha256'] for x in inputs}
        for row in workflows.get(identity,{}).get('items',[]):
            if row['stage']!='input-file' or row['document']['sha256'] in seen:continue
            ref=row['document'];seen.add(ref['sha256'])
            inputs.append(dict(name=row['name'],input=ref,log_binding='unknown',submission_binding='unverified-source-file',conditions=extract(read(ref),row['name'],input_file=True)))
        if inputs:e['input_conditions']=save('input-conditions/'+identity+'.json',dict(archive_id=identity,items=inputs))

def enrich(profile_path,destination,report_path):
    if not destination.is_absolute() or destination.exists() or destination.parent.resolve()!=destination.parent:raise ValueError('new canonical destination required')
    p=json.loads(profile_path.read_bytes());index=json.loads(read_pinned(Path(p['archive_index']),p['archive_sha256']));catalog=json.loads(read_pinned(Path(p['evidence_catalog']),p['evidence_sha256']));report=json.loads(report_path.read_bytes())
    entries={(e['kind'],e['id']):e for e in catalog['entries']};stage=destination.parent/('.pending-enrich-'+uuid.uuid4().hex);stage.mkdir()
    def save(name,data):
        raw=json.dumps(data,sort_keys=True,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode()
        if len(raw)>LIMIT:raise ValueError('sidecar too large')
        file=stage/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(raw)
        return dict(path=str(destination/name),sha256=sha256(raw).hexdigest(),size_bytes=len(raw))
    additions(index['records'],entries,report['files'],Path(report['source']).name,save)
    c=save('evidence-catalog.json',dict(schema=catalog['schema'],entries=list(entries.values())))
    save('profile.json',{**p,'evidence_catalog':c['path'],'evidence_sha256':c['sha256']})
    save('enrichment-report.json',dict(previous_profile=str(profile_path),previous_profile_sha256=sha256(profile_path.read_bytes()).hexdigest(),archive_index_unchanged=p['archive_sha256'],records=len(index['records']),original_result_references_unchanged=True))
    stage.rename(destination)
    return destination/'profile.json'
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True,type=Path);p.add_argument('--destination',required=True,type=Path);p.add_argument('--report',required=True,type=Path);a=p.parse_args();print(enrich(a.profile,a.destination,a.report))

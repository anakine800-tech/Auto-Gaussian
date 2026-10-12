"""Explicit offline reparse: new versioned batch; old artifacts never overwritten."""
import argparse
from collections import Counter
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
import uuid
from .archive import ArchiveQuery,read_pinned,validate_index,LOCAL_SCHEMA,PARSE_LIMIT,LOG_LIMIT,LIMIT
from .details import document,full_result
from .local_import import parse_log
from .vibrations import build_modes
from .history_links import build_links

def reparse(profile_path,destination,import_report=None):
    if not destination.is_absolute() or destination.exists() or destination.parent.resolve()!=destination.parent:raise ValueError('new canonical destination required')
    profile=json.loads(profile_path.read_bytes());old=ArchiveQuery(Path(profile['archive_index']),profile['archive_sha256'])._read()
    catalog=json.loads(read_pinned(Path(profile['evidence_catalog']),profile['evidence_sha256']))
    entries={(e['kind'],e['id']):dict(e) for e in catalog['entries']};timestamp=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    stage=destination.parent/('.pending-reparse-'+uuid.uuid4().hex);stage.mkdir()
    def save(name,value,limit=LIMIT):
        raw=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        if len(raw)>limit:raise ValueError('derived artifact exceeds bound')
        p=stage/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        return dict(path=str(destination/name),sha256=sha256(raw).hexdigest(),size_bytes=len(raw))
    changes=[];records=[]
    for before in old['records']:
        identity=before['archive_id'];entry=entries.get(('archive',identity));r=dict(before)
        if not entry or 'log' not in entry:raise ValueError('missing pinned log')
        raw=document(entry['log'],limit=LOG_LIMIT);log=next(a for a in r['artifacts'] if a['role']=='log')
        if sha256(raw).hexdigest()!=log['sha256'] or len(raw)!=log['size_bytes']:raise ValueError('source mismatch')
        new,payload,outcome=parse_log(raw,log['logical_name'],r['title'],timestamp)
        if before['parser']['status']=='parsed' and new['summary']!=before['summary']:raise ValueError('previously parsed summary changed')
        # Keep original import identity, metadata, input authority and capture clock.
        r.update(parser=new['parser'],summary=new['summary']);records.append(r)
        change=dict(id=identity,previous_parser=before['parser'],previous_parse_outcome=entry.get('parse_outcome'),parser=new['parser'],mode_status='no-frequency-result')
        entry['parse_outcome']=save('parsed/'+identity+'.json',payload,PARSE_LIMIT);entry.pop('vibrations',None)
        if new['summary'] and new['summary']['frequency_count']:
            try:
                packet=build_modes(dict(kind='archive',id=identity,result=full_result(outcome)),raw)
                entry['vibrations']=save('modes/'+identity+'.json',packet);change['mode_status']='available';change['mode_count']=len(packet['modes'])
            except (ValueError,KeyError,TypeError) as e:change['mode_status']=str(e)
        changes.append(change)
    history={}
    if import_report:
        source=json.loads(import_report.read_bytes());history=build_links(source['files'])
        for identity,packet in history.items():
            if ('archive',identity) in entries:entries[('archive',identity)]['history_links']=save('history/'+identity+'.json',packet)
    index=dict(schema=LOCAL_SCHEMA,records=records);validate_index(index)
    ix=save('archive-index.json',index);ca=save('evidence-catalog.json',dict(schema='auto-g16-local-evidence-catalog/1',entries=list(entries.values())))
    updated={**profile,'archive_index':ix['path'],'archive_sha256':ix['sha256'],'evidence_catalog':ca['path'],'evidence_sha256':ca['sha256']};save('profile.json',updated)
    report=dict(schema='autog-archive-reparse/1',created_at=timestamp,previous_profile=dict(path=str(profile_path),sha256=sha256(profile_path.read_bytes()).hexdigest()),
        previous_archive_sha256=profile['archive_sha256'],previous_evidence_sha256=profile['evidence_sha256'],
        historical_import_report=dict(path=str(import_report),sha256=sha256(import_report.read_bytes()).hexdigest()) if import_report else None,
        statuses=dict(Counter(r['parser']['status'] for r in records)),modes_available=sum(c['mode_status']=='available' for c in changes),
        history_linked_archives=len(history),changes=changes,old_results_preserved=True,scientific_acceptance='unchanged')
    save('reparse-report.json',report,PARSE_LIMIT)
    if destination.exists():raise ValueError('destination appeared')
    stage.rename(destination)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--profile',required=True,type=Path);p.add_argument('--destination',required=True,type=Path);p.add_argument('--import-report',type=Path)
    a=p.parse_args();r=reparse(a.profile,a.destination,a.import_report);print(json.dumps({k:v for k,v in r.items() if k!='changes'},indent=2))

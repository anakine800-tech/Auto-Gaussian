"""Browse-only historical memberships; never manufacture Core ancestry."""
from hashlib import sha256
import json
from datetime import datetime, timezone
from pathlib import Path
from auto_g16.query import QueryError
from .details import read_json
SCHEMA='autog-project-library/1'

def memberships(manifest,source_label):
    out={}
    for f in manifest:
        identity=f.get('archive_id')
        if not identity:continue
        parent=str(Path(f['relative_path']).parent)
        if parent=='.':continue
        label=Path(parent).parts[0]
        key='history-'+sha256((source_label+'\0'+label).encode()).hexdigest()
        value=dict(id=key,label=label,source_label=source_label,basis='source-directory',relative_paths=[])
        existing=next((x for x in out.setdefault(identity,[]) if x['id']==key),None)
        if existing is None:out[identity].append(value);existing=value
        if f['relative_path'] not in existing['relative_paths']:existing['relative_paths'].append(f['relative_path'])
    return out

class ProjectLibrary:
    def __init__(self,core_query,details):self.core=core_query;self.details=details
    def snapshots(self):
        detail=self.details.manager.queries()[1] if hasattr(self.details,'manager') else self.details
        archives=detail.archives.list_archives()['items'];groups={};rows={}
        for record in archives:
            identity=record['archive_id'];entry=detail._entry('archive',identity);packet=read_json(entry['browse']) if 'browse' in entry else dict(id=identity,memberships=[])
            if packet['id']!=identity:raise ValueError('browse identity mismatch')
            members=packet['memberships'] or [dict(id='history-unassigned',label='待分组历史结果',source_label='历史导入',basis='unassigned',relative_paths=[])]
            for m in members:
                if m['basis'] not in ('source-directory','unassigned') or not isinstance(m['label'],str):raise ValueError('invalid membership')
                if m['basis']=='source-directory' and m['id']!='history-'+sha256((m['source_label']+'\0'+m['label']).encode()).hexdigest():raise ValueError('membership hash mismatch')
                g=groups.setdefault(m['id'],dict(id=m['id'],kind='historical',label=m['label'],source_label=m['source_label'],basis=m['basis'],count=0,task_count=None,states=[],state_counts={},issue_archive_ids=[],archive_ids=[]))
                if identity not in rows.setdefault(m['id'],{}):
                    g['count']+=1;g['archive_ids'].append(identity);rows[m['id']][identity]=record
                    state=record['summary']['termination'] if record['summary'] else record['parser']['status']
                    for axis in dict.fromkeys([state,record['parser']['status']]):
                        if axis not in g['states']:g['states'].append(axis)
                        g['state_counts'][axis]=g['state_counts'].get(axis,0)+1
                    if state in ('error-termination','unknown','unparseable','partial') or record['parser']['status'] in ('unparseable','partial'):
                        g['issue_archive_ids'].append(identity)
        return groups,rows
    def list_projects(self):
        try:
            native=self.core.list_projects()['data']['items'];groups,rows=self.snapshots()
            items=[dict(id=p['project_id'],kind='native',label=p['name']['value'] if p['name']['availability']=='available' else p['project_id'],source_label='Core',basis='public-core-hierarchy',count=p['attempt_summary']['total'],task_count=p['task_count'],state_counts=p['attempt_summary']['state_counts'],issue_count=sum(p['attempt_summary']['state_counts'].get(k,0) for k in ('FAILED','UNKNOWN')),states=[k for k,v in p['attempt_summary']['state_counts'].items() if v]) for p in native]
            items+=sorted(groups.values(),key=lambda x:x['label'])
            records={k:v for members in rows.values() for k,v in members.items()}
            digest=sha256(json.dumps(dict(items=items,archives=records),sort_keys=True,ensure_ascii=True,separators=(',',':')).encode()).hexdigest()
            captures=[r['captured_at'] for r in records.values() if r.get('captured_at')]
            return dict(schema=SCHEMA,items=items,snapshot=dict(content_sha256=digest,read_at=datetime.now(timezone.utc).isoformat(),latest_archive_capture=max(captures) if captures else None,scope='browse-index-content-not-live-state'))
        except QueryError:raise
        except (ValueError,KeyError,TypeError,OSError):raise QueryError('invalid-evidence') from None
    def get_project(self,identity):
        try:
            groups,rows=self.snapshots()
            if identity not in groups:raise QueryError('not-found')
            return dict(schema=SCHEMA,project=groups[identity],items=list(rows[identity].values()))
        except QueryError:raise
        except (ValueError,KeyError,TypeError,OSError):raise QueryError('invalid-evidence') from None

"""Hash-verified input/submission claims, never inferred Core/result ancestry."""
import json
from pathlib import Path
from hashlib import sha256
from .details import document
SCHEMA='autog-historical-input-links/1'
CLAIMS=('project','job_name','batch_id','scientific_task_id','attempt_id')

def build_links(manifest, read_artifact=None):
    read_artifact=read_artifact or (lambda ref:document(ref,limit=32*1024*1024))
    inputs={}; intents=[]; logs={}
    for item in manifest:
        ref=item.get('artifact');relative=item['relative_path'];p=Path(relative)
        if not ref:continue
        if p.suffix.lower() in ('.gjf','.com','.inp'):
            inputs.setdefault(ref['sha256'],[]).append(item)
        if item.get('archive_id'):logs.setdefault(item['archive_id'],[]).append(p)
        if p.suffix.lower()=='.json':
            try:data=json.loads(read_artifact(ref))
            except (ValueError,UnicodeError):continue
            if isinstance(data,dict) and data.get('schema')=='gaussian-submission-intent/1':intents.append((item,data))
    result={}
    for identity,paths in logs.items():
        candidates=[];seen=set()
        for item,data in intents:
            # Co-location only selects candidates; it never proves log/input linkage.
            if not any(p.parent==Path(item['relative_path']).parent for p in paths):continue
            if item['artifact']['sha256'] in seen:continue
            seen.add(item['artifact']['sha256']);matched=[]
            for inp in inputs.get(data.get('input_sha256'),[]):
                raw=read_artifact(inp['artifact'])
                if sha256(raw).hexdigest()!=data['input_sha256']:raise ValueError('input digest mismatch')
                matched.append(dict(name=inp['relative_path'],artifact=inp['artifact']))
            candidates.append(dict(submission_name=item['relative_path'],submission=item['artifact'],
                claims={k:data.get(k) if isinstance(data.get(k),str) else None for k in CLAIMS},
                declared_input_sha256=data.get('input_sha256'),inputs=matched,
                input_binding='sha256-verified' if matched else 'unknown',log_binding='unknown',
                candidate_basis='same-source-directory',native_core_binding='unknown'))
        if candidates:result[identity]=dict(schema=SCHEMA,id=identity,log_sha256=identity.removeprefix('archive-'),candidates=candidates)
    return result

def project_links(packet,identity):
    if not isinstance(packet,dict) or packet.get('schema')!=SCHEMA or packet.get('id')!=identity or packet.get('log_sha256')!=identity.removeprefix('archive-'):raise ValueError('history link identity mismatch')
    out=[]
    for c in packet['candidates']:
        data=json.loads(document(c['submission']))
        if data.get('schema')!='gaussian-submission-intent/1' or c['log_binding']!='unknown' or c['native_core_binding']!='unknown' or c['candidate_basis']!='same-source-directory':raise ValueError('unsupported history claim')
        if c['claims']!={k:data.get(k) if isinstance(data.get(k),str) else None for k in CLAIMS} or c['declared_input_sha256']!=data.get('input_sha256'):raise ValueError('submission claims changed')
        inputs=[]
        for i in c['inputs']:
            raw=document(i['artifact']);digest=sha256(raw).hexdigest()
            if digest!=data['input_sha256']:raise ValueError('input not bound to submission')
            inputs.append(dict(name=i['name'],sha256=digest,text=raw.decode('utf-8')))
        if c['input_binding']!=('sha256-verified' if inputs else 'unknown'):raise ValueError('invalid input status')
        out.append(dict(submission_name=c['submission_name'],submission_sha256=c['submission']['sha256'],claims=c['claims'],inputs=inputs,input_binding=c['input_binding'],log_binding='unknown',native_core_binding='unknown'))
    return dict(schema=SCHEMA,id=identity,candidates=out)

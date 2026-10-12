"""Historical workflow documents with explicit source/binding limitations."""
import json,re
from pathlib import Path
from hashlib import sha256
SCHEMAS={'gaussian-submission-intent/1':'submission-intent','gaussian-remote-submission-receipt/1':'submission-receipt','rtwin-pbs-gaussian/1':'historical-job','codex-gaussian-pbs/1':'historical-job','gaussian-allcheck-input-manifest/1':'input-preparation','gaussian-opt-freq-sp/1':'input-preparation','chemdraw-gaussian/1':'input-preparation','auto-g16-main-group-open-shell-minimum-stability-input-manifest/1':'input-preparation'}
KEYS=('project','job_name','attempt_id','scientific_task_id','batch_id','reserved_at','job_id','status','input_sha256','gaussian_input_sha256','route','charge','multiplicity','resources','scheduler','mem','nprocshared','candidate_only','calculation_ready','stages','continuation_kind')

def build(manifest,read):
    logs={};documents=[];inputs={}
    for f in manifest:
        if not f.get('artifact'):continue
        if f.get('archive_id'):logs.setdefault(f['archive_id'],set()).add(str(Path(f['relative_path']).parent))
        if Path(f['relative_path']).suffix.lower() in ('.com','.gjf','.inp'):inputs.setdefault(f['artifact']['sha256'],f['artifact'])
        if Path(f['relative_path']).suffix.lower() in ('.com','.gjf','.inp','.pbs'):
            stage='submission-script' if f['relative_path'].endswith('.pbs') else 'input-file'
            documents.append((f,dict(schema='local-'+stage+'/1')))
        if f['relative_path'].endswith('.json'):
            try:d=json.loads(read(f['artifact']))
            except (ValueError,UnicodeError):continue
            if isinstance(d,dict) and d.get('schema') in SCHEMAS:documents.append((f,d))
    result={}
    for identity,parents in logs.items():
        rows=[];seen=set()
        for f,d in documents:
            parent=str(Path(f['relative_path']).parent)
            if not any(parent==p or p!='.' and parent==p+'/results' for p in parents):continue
            digest=f['artifact']['sha256']
            if digest in seen:continue
            seen.add(digest);h=d.get('input_sha256',d.get('gaussian_input_sha256'));matched=inputs.get(h) if isinstance(h,str) else None
            if matched and sha256(read(matched)).hexdigest()!=h:raise ValueError('workflow input digest mismatch')
            rows.append(dict(name=f['relative_path'],document=f['artifact'],input=matched,schema=d['schema'],stage=SCHEMAS.get(d['schema'],d['schema'].removeprefix('local-').removesuffix('/1')),input_binding='sha256-verified' if matched else 'unknown',log_binding='unknown'))
        result[identity]=dict(schema='autog-historical-workflow/1',id=identity,items=rows)
    return result

def project(packet,identity,read):
    if packet['schema']!='autog-historical-workflow/1' or packet['id']!=identity:raise ValueError('workflow identity mismatch')
    rows=[]
    for row in packet['items']:
        raw=read(row['document'])
        if row['schema'] in ('local-input-file/1','local-submission-script/1'):
            if row['stage']!=row['schema'].removeprefix('local-').removesuffix('/1') or row['log_binding']!='unknown' or row['input_binding']!='unknown':raise ValueError('unsupported text binding')
            text=raw.decode('utf-8')
            declarations=[line.strip() for line in text.splitlines() if re.match(r'^\s*(?:#PBS\s|%(?:mem|nprocshared|chk)=)',line,re.I)]
            rows.append(dict(name=row['name'],sha256=row['document']['sha256'],stage=row['stage'],input_binding='unknown',log_binding='unknown',claims=dict(file_size=len(raw),declarations=declarations[:100],scope='saved-file-only-not-execution-evidence')))
            continue
        data=json.loads(raw)
        if data.get('schema')!=row['schema'] or row['stage']!=SCHEMAS.get(row['schema']) or row['log_binding']!='unknown':raise ValueError('workflow document mismatch')
        if row['input']:
            h=sha256(read(row['input'])).hexdigest()
            if h!=data.get('input_sha256',data.get('gaussian_input_sha256')) or row['input_binding']!='sha256-verified':raise ValueError('workflow input mismatch')
        elif row['input_binding']!='unknown':raise ValueError('unsupported input claim')
        rows.append(dict(name=row['name'],sha256=row['document']['sha256'],stage=row['stage'],input_binding=row['input_binding'],log_binding='unknown',claims={k:data[k] for k in KEYS if k in data}))
    return dict(schema=packet['schema'],id=identity,items=rows,live_scheduler='unavailable',native_core_binding='unknown')

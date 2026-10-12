"""Offline, source-bound Gaussian setup observations; independent of Result parsing.

No default solvent/temperature, no cross-step inheritance, no scientific verdict.
Unresolved Gen/ECP data remains an exact, bounded source block.
"""
import re
from hashlib import sha256
SCHEMA='autog-calculation-conditions/1'
VERSION='1.0.0'
SEP=re.compile(r'^\s*-{5,}\s*$')
FIELDS=('method','basis','environment','dispersion','charge','multiplicity','temperature_k','pressure_atm')

def route_fields(route):
    # Gaussian wraps inside tokens (e.g. SCRF\n =(...) and basis names).
    compact=re.sub(r'\s+','',route)
    pairs=re.findall(r'(?i)(?<![\w=])([A-Za-z][A-Za-z0-9+_-]*)/([^\s]+)',route)
    out={}
    if len(pairs)==1 and 'oniom' not in compact.lower() and pairs[0][1].count('(')==pairs[0][1].count(')'):out.update(method=pairs[0][0],basis=pairs[0][1])
    for name,key in [('scrf','environment'),('empiricaldispersion','dispersion')]:
        match=re.search(r'(?i)\b'+name+r'\s*=\s*(\([^\r\n]*?\)|[^\s]+)',route)
        if match:out[key]=match.group(1)
    return out

def extract(raw,name,*,input_file=False):
    raw.decode('utf-8')
    lines=raw.splitlines(keepends=True);texts=[x.decode().rstrip('\r\n') for x in lines];offsets=[0]
    for line in lines:offsets.append(offsets[-1]+len(line))
    source=dict(artifact_kind='gaussian-input' if input_file else 'gaussian-log',envelope_observation_id='local-file-'+sha256(raw).hexdigest(),logical_name=name,sha256=sha256(raw).hexdigest(),size_bytes=len(raw))
    def evidence(value,a,b,kind):return dict(value=value,source_span={**source,'start':offsets[a],'end':offsets[b]},line_start=a+1,line_end=b,evidence_kind=kind)
    routes=[];pending=input_file
    for i,t in enumerate(texts):
        if not input_file and re.match(r'^\s*(Entering Gaussian System, Link 0=g(?:16|09)|(?:Link1:\s*)?Proceeding to internal job step number\s+\d+\.)',t):pending=True
        if input_file and t.strip()=='--Link1--':pending=True
        if not pending:continue
        if not re.match(r'^\s*#[pPnNtT]?(?:\s|$)',t):continue
        if not input_file and (i==0 or not SEP.fullmatch(texts[i-1])):continue
        end=i+1
        while end<len(texts) and end-i<100 and (bool(texts[end].strip()) if input_file else not SEP.fullmatch(texts[end])):end+=1
        if end>=len(texts) or end-i>=100:continue
        route=''.join(x.strip() for x in texts[i:end]) if len(texts[i:end])>1 else texts[i].strip()
        # Preserve word boundaries except physical wraps at non-space boundaries.
        route=' '.join(x.strip() for x in texts[i:end]);route=re.sub(r'\s*=\s*','=',route)
        routes.append((i,end,route));pending=False
    steps=[]
    for n,(start,end,route) in enumerate(routes):
        stop=routes[n+1][0] if n+1<len(routes) else len(texts)
        step=dict(index=n+1,route=evidence(route,start,end,'input-route' if input_file else 'printed-route'),fields={k:[] for k in FIELDS},basis_blocks=[],ecp_blocks=[],diagnostics=[])
        for k,v in route_fields(route).items():step['fields'][k].append(evidence(v,start,end,'input-route' if input_file else 'printed-route'))
        if input_file:
            # Charge/multiplicity is after the title's blank separator, never a coordinate row.
            j=end+1
            while j<stop and texts[j].strip():j+=1
            j+=1
            if j<stop and (m:=re.fullmatch(r'\s*([+-]?\d+)\s+([1-9]\d*)\s*',texts[j])):
                for k,v in zip(('charge','multiplicity'),m.groups()):step['fields'][k].append(evidence(int(v),j,j+1,'input-molecule'))
            # Explicit named/primitive blocks kept by selectors, with exact raw cards.
            mixed=bool(re.search(r'(?i)\b(genecp|gen)\b',route));basis_end=end;found=False
            if mixed:
                for j in range(end+1,stop):
                    if not re.fullmatch(r'\s*(?:-?[A-Z][a-z]?|[1-9]\d*)(?:\s+(?:-?[A-Z][a-z]?|[1-9]\d*))*\s+0\s*',texts[j]):continue
                    if j+1>=stop or not texts[j+1].strip():continue
                    k=j+1
                    while k<stop and texts[k].strip() and texts[k].strip()!='****':k+=1
                    if k<stop and texts[k].strip()=='****':
                        step['basis_blocks'].append(dict(selectors=texts[j].split()[:-1],**evidence('\n'.join(texts[j:k+1]),j,k+1,'input-basis-cards')));basis_end=k+1;found=True
                if not found:step['diagnostics'].append('general-basis-selectors-unresolved')
            if found and re.search(r'(?i)\bgenecp\b|\bpseudo\s*=\s*(?:read|\(read\))',route):
                j=basis_end
                while j<stop:
                    if re.fullmatch(r'\s*(?:-?[A-Z][a-z]?|[1-9]\d*)(?:\s+(?:-?[A-Z][a-z]?|[1-9]\d*))*\s+0\s*',texts[j]):
                        k=j+1
                        while k<stop and texts[k].strip():
                            if k>j+1 and re.fullmatch(r'\s*(?:[A-Z][a-z]?|[1-9]\d*)(?:\s+(?:[A-Z][a-z]?|[1-9]\d*))*\s+0\s*',texts[k]):break
                            k+=1
                        if k>j+1:step['ecp_blocks'].append(dict(selectors=texts[j].split()[:-1],**evidence('\n'.join(texts[j:k]),j,k,'input-ecp-cards')))
                        j=k
                    else:j+=1
                if not step['ecp_blocks']:step['diagnostics'].append('ecp-selectors-unresolved')
        else:
            for j in range(end,stop):
                t=texts[j]
                for pattern,keys in [(r'^\s*Charge\s*=\s*([+-]?\d+)\s+Multiplicity\s*=\s*([1-9]\d*)\s*$',('charge','multiplicity')),(r'^\s*Temperature\s+([0-9.]+)\s+Kelvin\.\s+Pressure\s+([0-9.]+)\s+Atm\.',('temperature_k','pressure_atm'))]:
                    m=re.match(pattern,t)
                    if m:
                        for key,value in zip(keys,m.groups()):step['fields'][key].append(evidence(int(value) if key in ('charge','multiplicity') else float(value),j,j+1,'printed-value'))
                m=re.match(r'^\s*Standard basis:\s*(.+)$',t)
                if m:step['fields']['basis'].append(evidence(m.group(1).strip(),j,j+1,'printed-standard-basis'))
                # Preserve specialized per-center output verbatim; never map center indices to elements without evidence.
                if re.match(r'^\s*(General basis read from cards:|Pseudopotential Parameters)\s*',t):
                    k=j+1
                    while k<stop and k-j<3000 and not re.match(r'^\s*(Leave Link\s+301|[0-9]+ basis functions|There are\s+\d+)',texts[k]):k+=1
                    if k-j>=3000:step['diagnostics'].append('printed-table-exceeds-window-inspect-full-log')
                    value='\n'.join(texts[j:k])
                    role='ecp_blocks' if 'Pseudopotential' in t else 'basis_blocks'
                    step[role].append(dict(selectors=['see-printed-centers'],**evidence(value,j,k,'printed-center-table')))
                    step['diagnostics'].append('per-center-table-preserved-no-global-basis-inference')
        # Preserve distinct values and first/last locations; collapse repeated optimizer printouts.
        for key in FIELDS:
            unique={}
            for ev in step['fields'][key]:
                signature=(str(ev['value']),ev['evidence_kind'])
                if signature not in unique:unique[signature]={**ev,'occurrence_count':0,'last_source_span':ev['source_span']}
                unique[signature]['occurrence_count']+=1;unique[signature]['last_source_span']=ev['source_span']
            if len(unique)>100:raise ValueError('too many distinct condition values')
            step['fields'][key]=list(unique.values())
        steps.append(step)
    if len(steps)>100:raise ValueError('too many calculation steps')
    return dict(schema=SCHEMA,extractor_version=VERSION,source=source,steps=steps,scope='input-declaration' if input_file else 'log-observation',scientific_acceptance='not-assessed')

def validate(packet,ref,name=None):
    if packet.get('schema')!=SCHEMA or packet.get('extractor_version')!=VERSION:raise ValueError('invalid conditions version')
    if packet.get('scope') not in ('input-declaration','log-observation') or packet.get('scientific_acceptance')!='not-assessed':raise ValueError('invalid condition scope')
    source=packet['source']
    if any(source[k]!=ref[k] for k in ('sha256','size_bytes')) or name is not None and source['logical_name']!=name:raise ValueError('conditions source mismatch')
    if not isinstance(packet['steps'],list) or len(packet['steps'])>100:raise ValueError('invalid steps')
    for n,step in enumerate(packet['steps']):
        if step['index']!=n+1 or set(step['fields'])!=set(FIELDS):raise ValueError('invalid step fields')
        for ev in [step['route'],*sum(step['fields'].values(),[]),*step['basis_blocks'],*step['ecp_blocks']]:
            for span in [ev['source_span']]+([ev['last_source_span']] if 'last_source_span' in ev else []):
                if any(span[k]!=v for k,v in source.items()) or any(type(span[k]) is not int for k in ('start','end')) or not 0<=span['start']<span['end']<=ref['size_bytes']:raise ValueError('invalid condition span')
            if 'occurrence_count' in ev and (type(ev['occurrence_count']) is not int or ev['occurrence_count']<1):raise ValueError('invalid occurrence count')
    return packet

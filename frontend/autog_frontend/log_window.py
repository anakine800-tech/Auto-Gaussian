"""Bounded read-only windows over a hash-verified archived log (max 32 MiB)."""
import base64
from hashlib import sha256
from auto_g16.query import QueryError
from .archive import LOG_LIMIT, read_pinned
from pathlib import Path

SCHEMA = 'auto-g16-log-window/1'

def number(value,maximum):
    if not isinstance(value,str) or not value.isascii() or not value.isdigit() or len(value)>10 or int(value)>maximum:
        raise QueryError('invalid-id')
    return int(value)

def read_window(query,kind,identity,mode,start='0',end='120',digest=None,term=None):
    try:
        entry=query._entry(kind,identity)
        if kind=='archive':
            record=query.archives.get_archive(identity)['data'];expected=next(a for a in record['artifacts'] if a['role']=='log')
        else:
            detail=query.get_details(kind,identity);source=detail['result']['source'];expected=source['artifact'] if source else None
        ref=entry.get('log')
        if not ref or not expected:raise QueryError('not-found')
        if any(ref[k]!=expected[k] for k in ('sha256','size_bytes')):raise QueryError('invalid-evidence')
        raw=read_pinned(Path(ref['path']),ref['sha256'],limit=LOG_LIMIT)
        text=raw.decode('utf-8');lines=text.splitlines(keepends=True)
        if not lines:lines=['']
        match_count=None
        if mode=='span':
            lo,hi=number(start,len(raw)),number(end,len(raw))
            if not lo<hi or hi-lo>262144 or digest!=ref['sha256']:raise QueryError('invalid-id')
            raw[:lo].decode('utf-8');excerpt=raw[lo:hi].decode('utf-8')
            first=raw[:lo].count(b'\n');last=first+len(excerpt.rstrip('\r\n').split('\n'))-1
        else:
            first=number(start,len(lines)-1) if mode=='page' or start!='last' else 0
            count=number(end,200)
            if count<1:raise QueryError('invalid-id')
            if mode=='find':
                try:
                    needle=base64.b64decode(term+'='*(-len(term)%4),altchars=b'-_',validate=True).decode('utf-8')
                except (ValueError,UnicodeError):raise QueryError('invalid-id') from None
                if not needle or len(needle)>256:raise QueryError('invalid-id')
                matches=[i for i,line in enumerate(lines) if needle.casefold() in line.casefold()]
                match_count=len(matches)
                found=(matches[-1] if start=='last' else next((i for i in matches if i>=first),matches[0] if matches else None)) if matches else None
                first=max(0,found-3) if found is not None else first
            last=min(len(lines)-1,first+count-1);excerpt=''.join(lines[first:last+1]);lo=sum(len(x.encode('utf-8')) for x in lines[:first]);hi=lo+len(excerpt.encode('utf-8'))
        if len(excerpt.encode('utf-8'))>262144:raise QueryError('response-too-large')
        return dict(schema=SCHEMA,kind=kind,id=identity,mode=mode,sha256=ref['sha256'],size_bytes=ref['size_bytes'],logical_name=expected['logical_name'],
            start=lo,end=hi,first_line=first,last_line=last,total_lines=len(lines),text=excerpt,segment_sha256=sha256(excerpt.encode('utf-8')).hexdigest(),match_count=match_count)
    except QueryError:raise
    except (OSError,ValueError,KeyError,TypeError,StopIteration):raise QueryError('invalid-evidence') from None

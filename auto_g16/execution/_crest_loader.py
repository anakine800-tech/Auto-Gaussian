"""Fixed CREST-only Linux loader closure source for qualification and guards."""

_SOURCE = r'''
"""Bounded Linux ELF64 CPU loader observation; no scientific main is entered."""
import hashlib as _cl_hashlib
import json as _cl_json
import os as _cl_os
import posixpath as _cl_path
import re as _cl_re
import stat as _cl_stat
import struct as _cl_struct
import subprocess as _cl_subprocess
import selectors as _cl_selectors
import time as _cl_time
import errno as _cl_errno
import base64 as _cl_base64

_cl_diagnostics = {}


def cl_raw(stdout,stderr,complete,returncode=None):
    value={'complete':complete,'returncode':returncode}
    for name,raw in (('stdout',stdout),('stderr',stderr)):
        value[name]=raw.decode('utf-8','replace')
        value[name+'_base64']=_cl_base64.b64encode(raw).decode('ascii')
        value[name+'_sha256']=_cl_hashlib.sha256(raw).hexdigest()
        value[name+'_size_bytes']=len(raw)
    return value


def cl_canonical(value):
    return (_cl_json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n').encode()


def cl_id(value):
    return _cl_hashlib.sha256(cl_canonical(value)).hexdigest()


def cl_require(value, message):
    if not value: raise ValueError('crest-loader: '+message)


def cl_path(path):
    cl_require(type(path) is str and path.startswith('/') and path!='/' and '\x00' not in path and _cl_path.normpath(path)==path and not path.startswith('//'), 'noncanonical path')
    return path


def cl_requested(path):
    cl_require(type(path) is str and path.startswith('/') and not path.startswith('//') and '\x00' not in path and 0<len(path)<=4096 and '' not in path[1:].split('/'),'requested path')
    return path


def cl_alias(path, allow_absent=False):
    requested=cl_requested(path);pending=requested[1:].split('/');current='/';root=_cl_os.lstat('/');nodes=[{'path':'/','kind':'directory','device':root.st_dev,'inode':root.st_ino,'link_target':''}];links=0
    while pending:
        name=pending.pop(0)
        if name=='..':current=_cl_path.dirname(current)
        elif name!='.':current=_cl_path.join(current,name)
        try: info=_cl_os.lstat(current)
        except FileNotFoundError:
            cl_require(allow_absent and not pending, 'unresolved alias')
            result={'requested_path':requested,'canonical_path':'','state':'absent','nodes':nodes}
            return {'alias_id':cl_id(result),**result}
        kind='link' if _cl_stat.S_ISLNK(info.st_mode) else 'directory' if _cl_stat.S_ISDIR(info.st_mode) else 'regular' if _cl_stat.S_ISREG(info.st_mode) else 'other'
        target=_cl_os.readlink(current) if kind=='link' else ''
        nodes.append({'path':current,'kind':kind,'device':info.st_dev,'inode':info.st_ino,'link_target':target})
        cl_require(len(nodes)<=512 and kind!='other','alias bounds/type')
        if kind=='link':
            links+=1;cl_require(links<=40,'symlink cycle')
            cl_require(target and '\x00' not in target and len(target)<=4096,'symlink target')
            if target.startswith('/'):
                pending=target[1:].split('/')+pending;current='/'
            else:
                pending=target.split('/')+pending;current=_cl_path.dirname(current)
            cl_require(all(pending),'empty symlink component')
        elif pending: cl_require(kind=='directory','non-directory alias parent')
        else: cl_require(kind=='regular','alias final type')
    result={'requested_path':requested,'canonical_path':current,'state':'present','nodes':nodes}
    return {'alias_id':cl_id(result),**result}


def cl_file(path, elf=False):
    path=cl_path(path);fd=_cl_os.open(path,_cl_os.O_RDONLY|_cl_os.O_NOFOLLOW|_cl_os.O_NONBLOCK|_cl_os.O_CLOEXEC)
    try:
        before=_cl_os.fstat(fd)
        cl_require(_cl_stat.S_ISREG(before.st_mode) and 0<=before.st_size<=256*1024*1024,'file bounds/type')
        digest=_cl_hashlib.sha256();total=0
        while True:
            block=_cl_os.read(fd,1024*1024)
            if not block:break
            total+=len(block);cl_require(total<=before.st_size,'file grew');digest.update(block)
        result={'path':path,'device':before.st_dev,'inode':before.st_ino,'size_bytes':total,'sha256':digest.hexdigest()}
        if elf:result['elf']=cl_elf(fd,before.st_size)
        after=_cl_os.fstat(fd);named=_cl_os.lstat(path)
        key=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
        cl_require(key(before)==key(after)==key(named) and total==before.st_size,'file identity/content drift')
        return result
    finally:_cl_os.close(fd)


def cl_elf(fd,size):
    def read(offset,count):
        cl_require(type(offset) is int and type(count) is int and 0<=offset<=size and 0<=count<=1024*1024 and offset+count<=size,'ELF bounds')
        raw=_cl_os.pread(fd,count,offset);cl_require(len(raw)==count,'short ELF');return raw
    header=read(0,64)
    cl_require(header[:7]==b'\x7fELF\x02\x01\x01','only ELF64 little endian version1')
    fields=_cl_struct.unpack('<HHIQQQIHHHHHH',header[16:])
    etype,machine,version,entry,phoff,shoff,flags,ehsize,phsize,phnum,shsize,shnum,shstr=fields
    cl_require(etype in (2,3) and machine==62 and version==1 and ehsize==64 and phsize==56 and 0<phnum<=128,'ELF target/header')
    segments=[_cl_struct.unpack('<IIQQQQQQ',read(phoff+i*phsize,phsize)) for i in range(phnum)]
    interps=[s for s in segments if s[0]==3];dynamics=[s for s in segments if s[0]==2]
    cl_require(len(interps)<=1 and len(dynamics)<=1,'ELF duplicated interpreter/dynamic')
    def string(raw,offset=0):
        cl_require(0<=offset<len(raw),'ELF string offset');end=raw.find(b'\x00',offset)
        cl_require(end>=offset and end-offset<=4096,'ELF string bounds');return raw[offset:end].decode('utf-8')
    interpreter=string(read(interps[0][2],interps[0][5])) if interps else ''
    entries=[]
    if dynamics:
        seg=dynamics[0];cl_require(seg[5]%16==0 and seg[5]<=65536,'dynamic size')
        for i in range(seg[5]//16):
            tag,val=_cl_struct.unpack('<qQ',read(seg[2]+i*16,16))
            if tag==0:break
            entries.append((tag,val))
        else:raise ValueError('crest-loader: unterminated dynamic')
    tags={tag:[v for t,v in entries if t==tag] for tag in (5,10,14,15,29)}
    cl_require(all(len(v)<=1 for v in tags.values()),'duplicate dynamic singleton')
    need=[v for t,v in entries if t==1];cl_require(len(need)<=64,'NEEDED bounds')
    if entries:
        cl_require(len(tags[5])==len(tags[10])==1 and 0<tags[10][0]<=1024*1024,'dynamic string table')
        address=tags[5][0];length=tags[10][0]
        loads=[s for s in segments if s[0]==1 and s[3]<=address and address+length<=s[3]+s[5]]
        cl_require(len(loads)==1,'unmapped dynamic strings');seg=loads[0]
        table=read(seg[2]+address-seg[3],length)
    else:table=b''
    needed=[string(table,v) for v in need]
    cl_require(len(set(needed))==len(needed) and all(_cl_re.fullmatch(r'[A-Za-z0-9_.+\-]+',v) for v in needed),'NEEDED names')
    text=lambda tag:string(table,tags[tag][0]) if tags[tag] else ''
    return {'class':64,'endian':'little','machine':machine,'type':etype,'interpreter':interpreter,'needed':needed,'soname':text(14),'rpath':text(15),'runpath':text(29)}


def cl_bounded_process(argv,**kwargs):
    process=_cl_subprocess.Popen(argv,stdout=_cl_subprocess.PIPE,stderr=_cl_subprocess.PIPE,**kwargs)
    selector=_cl_selectors.DefaultSelector();chunks={};deadline=_cl_time.monotonic()+20
    try:
        for stream in (process.stdout,process.stderr):
            _cl_os.set_blocking(stream.fileno(),False);selector.register(stream,_cl_selectors.EVENT_READ);chunks[stream]=bytearray()
        while selector.get_map():
            remaining=deadline-_cl_time.monotonic();cl_require(remaining>0,'trace deadline')
            for key,_ in selector.select(min(remaining,0.1)):
                block=_cl_os.read(key.fileobj.fileno(),65536)
                if not block:selector.unregister(key.fileobj);continue
                chunks[key.fileobj].extend(block)
                cl_require(sum(map(len,chunks.values()))<=262144,'trace output cap')
        remaining=deadline-_cl_time.monotonic();cl_require(remaining>0,'trace wait deadline')
        returncode=process.wait(timeout=remaining)
        return returncode,bytes(chunks[process.stdout]),bytes(chunks[process.stderr])
    except Exception as error:
        out=bytes(chunks.get(process.stdout,b''))[:262144]
        err=bytes(chunks.get(process.stderr,b''))[:262144-len(out)]
        error.loader_raw=cl_raw(out,err,False)
        raise
    finally:
        selector.close()
        if process.poll() is None:process.kill();process.wait(timeout=2)
        process.stdout.close();process.stderr.close()


def cl_no_secure(fd):
    info=_cl_os.fstat(fd)
    cl_require(not info.st_mode&(_cl_stat.S_ISUID|_cl_stat.S_ISGID) and _cl_os.getuid()==_cl_os.geteuid() and _cl_os.getgid()==_cl_os.getegid(),'secure execution route')
    try:capability=_cl_os.getxattr(fd,'security.capability')
    except OSError as error:
        cl_require(error.errno==_cl_errno.ENODATA,'capability state not acquired')
    else:cl_require(not capability,'file capabilities outside scope')


def cl_searches(raw):
    cl_require(raw.endswith(b'\n'),'incomplete debug stream')
    result=[];current=None;pid=None
    for line in raw.decode('utf-8').splitlines():
        match=_cl_re.fullmatch(r'\s*([0-9]+):\s?(.*)',line)
        cl_require(match is not None,'unknown debug prefix')
        if pid is None:pid=match[1]
        cl_require(pid==match[1],'multiple debug processes')
        text=match[2].strip()
        if not text:
            if current is not None:
                cl_require(current['events'] and current['events'][-1]['kind']=='try','incomplete search block')
                result.append(current);current=None
            continue
        match=_cl_re.fullmatch(r'find library=([A-Za-z0-9_.+\-]+) \[0\]; searching',text)
        if match:
            cl_require(current is None,'unclosed search block');current={'name':match[1],'events':[]};continue
        cl_require(current is not None,'debug outside search')
        match=_cl_re.fullmatch(r'search path=(\S+)\s+\((RPATH|RUNPATH) from file (\S+)\)',text)
        if match:
            paths=match[1].split(':');[cl_requested(p) for p in paths];cl_requested(match[3])
            current['events'].append({'kind':match[2],'paths':paths,'source':match[3]});continue
        match=_cl_re.fullmatch(r'search path=(\S+)\s+\(system search path\)',text)
        if match:
            paths=match[1].split(':');[cl_requested(p) for p in paths]
            current['events'].append({'kind':'system','paths':paths});continue
        if text=='search cache=/etc/ld.so.cache':current['events'].append({'kind':'cache'});continue
        match=_cl_re.fullmatch(r'trying file=(\S+)',text)
        if match:
            cl_require(current['events'],'try without search phase')
            current['events'].append({'kind':'try','path':cl_requested(match[1])});continue
        raise ValueError('crest-loader: unknown debug event')
    cl_require(current is None and 0<len(result)<=64 and len({s['name'] for s in result})==len(result),'search inventory')
    return result


def cl_dedup_candidate(search,root):
    # Only bundled RPATH/RUNPATH, with candidates explained by their active path.
    bundle=_cl_path.dirname(_cl_path.dirname(root));active=None;last=None
    cl_require(search['events'],'empty dedup search')
    for event in search['events']:
        if event['kind'] in ('RPATH','RUNPATH'):
            cl_require(_cl_path.commonpath((bundle,_cl_path.normpath(event['source'])))==bundle,'dedup search source outside bundle')
            cl_require(all(_cl_path.commonpath((bundle,_cl_path.normpath(p)))==bundle for p in event['paths']),'dedup path outside bundle')
            active=event['paths']
        else:
            cl_require(event['kind']=='try' and active is not None,'dedup cache/default/unknown phase')
            last=event['path'];cl_require(last in [p+'/'+search['name'] for p in active],'dedup unexplained candidate')
    cl_require(last is not None and search['events'][-1]['kind']=='try','dedup incomplete candidate')
    return last


def cl_dedup_path(search,root,loaded_paths):
    last=cl_dedup_candidate(search,root)
    candidate=cl_alias(last);data=cl_file(candidate['canonical_path'],elf=True)
    matching=[v for v in loaded_paths if v==data]
    cl_require(len(matching)==1,'dedup candidate not unique actual mapped object')
    return last


def cl_trace(path,expected,interpreter_expected):
    fd=_cl_os.open(path,_cl_os.O_RDONLY|_cl_os.O_NOFOLLOW|_cl_os.O_CLOEXEC)
    interpreter_fd=None
    try:
        cl_no_secure(fd)
        interpreter_fd=_cl_os.open(interpreter_expected['path'],_cl_os.O_RDONLY|_cl_os.O_NOFOLLOW|_cl_os.O_CLOEXEC)
        cl_no_secure(interpreter_fd)
        ii=_cl_os.fstat(interpreter_fd)
        cl_require((ii.st_dev,ii.st_ino,ii.st_size)==(interpreter_expected['device'],interpreter_expected['inode'],interpreter_expected['size_bytes']),'trace interpreter identity')
        info=_cl_os.fstat(fd)
        cl_require(_cl_stat.S_ISREG(info.st_mode) and (info.st_dev,info.st_ino,info.st_size)==(expected['device'],expected['inode'],expected['size_bytes']),'trace executable identity')
        digest=_cl_hashlib.sha256();total=0
        while total<info.st_size:
            block=_cl_os.read(fd,min(1024*1024,info.st_size-total));cl_require(block,'short trace executable');digest.update(block);total+=len(block)
        cl_require(not _cl_os.read(fd,1) and digest.hexdigest()==expected['sha256'],'trace executable bytes')
        try:
            code,stdout,stderr=cl_bounded_process([path],executable='/proc/self/fd/'+str(fd),pass_fds=(fd,),env={'LD_TRACE_LOADED_OBJECTS':'1','LD_DEBUG':'libs'},stdin=_cl_subprocess.DEVNULL)
        except Exception as error:
            _cl_diagnostics['raw_trace']=getattr(error,'loader_raw',{});raise
        _cl_diagnostics['raw_trace']=cl_raw(stdout,stderr,True,code)
        cl_require(code==0 and 0<len(stdout)+len(stderr)<=262144 and stdout.endswith(b'\n'),'direct loader trace failed')
        records=[];virtual=[]
        for line in stdout.decode('utf-8').splitlines():
            line=line.strip()
            match=_cl_re.fullmatch(r'([^\s]+) => (/[^\s]+) \(0x[0-9a-fA-F]+\)',line)
            if match: records.append({'name':match[1],'path':cl_requested(match[2])});continue
            match=_cl_re.fullmatch(r'(/[^\s]+) \(0x[0-9a-fA-F]+\)',line)
            if match: records.append({'name':'','path':cl_requested(match[1])});continue
            if _cl_re.fullmatch(r'linux-vdso\.so\.1(?:\s+=>)?\s+\(0x[0-9a-fA-F]+\)',line):virtual.append('linux-vdso.so.1');continue
            raise ValueError('crest-loader: unknown trace line')
        cl_require(0<len(records)<=64 and virtual==['linux-vdso.so.1'] and len({r['name'] for r in records})==len(records),'trace inventory')
        return {'objects':records,'kernel_objects':virtual,'searches':cl_searches(stderr)}
    finally:
        if interpreter_fd is not None:_cl_os.close(interpreter_fd)
        _cl_os.close(fd)


def cl_selectors():
    selectors=[]
    for path in ('/etc/ld.so.cache','/etc/ld.so.preload'):
        alias=cl_alias(path,allow_absent=True)
        entry={'path':path,'state':alias['state'],'alias':alias,'file':{}}
        if alias['state']=='present':
            entry['file']=cl_file(alias['canonical_path'])
            if path.endswith('preload'):cl_require(entry['file']['size_bytes']==0,'global preload is outside scope')
        selectors.append(entry)
    return selectors


def cl_observe(root,host_key,review_sha256,evidence_sha256):
    _cl_diagnostics.clear();_cl_diagnostics['phase']='initial-objects'
    try:return cl_observe_inner(root,host_key,review_sha256,evidence_sha256)
    except Exception as error:
        error.loader_diagnostics=dict(_cl_diagnostics)
        raise


def cl_observe_inner(root,host_key,review_sha256,evidence_sha256):
    aliases={};objects={}
    def add(path):
        alias=cl_alias(path);aliases[alias['alias_id']]=alias
        canonical=alias['canonical_path']
        if canonical not in objects:
            data=cl_file(canonical,elf=True);objects[canonical]={'object_id':cl_id(data),**data}
            cl_require(len(objects)<=64 and sum(o['size_bytes'] for o in objects.values())<=512*1024*1024,'aggregate ELF budget')
        return alias,objects[canonical]
    root_alias,root_object=add(root)
    interpreter=root_object['elf']['interpreter'];cl_require(interpreter,'missing PT_INTERP')
    interpreter_alias,interpreter_object=add(interpreter)
    selectors=cl_selectors()
    _cl_diagnostics['phase']='direct-trace'
    trace=cl_trace(root_alias['canonical_path'],root_object,interpreter_object)
    _cl_diagnostics['trace']=trace;_cl_diagnostics['phase']='recursive-needed'
    mappings={record['name']:record['path'] for record in trace['objects']}
    for record in trace['objects']:add(record['path'])
    loaded_paths=[{k:v for k,v in o.items() if k!='object_id'} for o in objects.values() if o['object_id']!=root_object['object_id']]
    cl_require('' in mappings and cl_alias(mappings[''])['canonical_path']==interpreter_object['path'],'trace interpreter mismatch')
    interpreter_name=interpreter_object['elf']['soname']
    if interpreter_name and interpreter_name not in mappings:mappings[interpreter_name]=mappings['']
    edges=[];todo=[root_object,interpreter_object];visited=set()
    while todo:
        obj=todo.pop(0)
        if obj['object_id'] in visited:continue
        visited.add(obj['object_id'])
        for ordinal,name in enumerate(obj['elf']['needed']):
            _cl_diagnostics['needed']={'source':obj['path'],'ordinal':ordinal,'name':name}
            if name not in mappings:
                search=[s for s in trace['searches'] if s['name']==name]
                cl_require(len(search)==1,'NEEDED missing from actual trace and unique search: '+name)
                mappings[name]=cl_dedup_path(search[0],root_object['path'],loaded_paths)
            alias,target=add(mappings[name])
            edges.append({'source_object_id':obj['object_id'],'needed_ordinal':ordinal,'requested_name':name,'alias_id':alias['alias_id'],'target_object_id':target['object_id']})
            todo.append(target)
    cl_require(visited=={o['object_id'] for o in objects.values()},'unreachable loaded object')
    cl_require(cl_selectors()==selectors,'selectors changed during trace')
    _cl_diagnostics['phase']='manifest-validation'
    result={'schema':'v31-crest-loader-closure/1','host_key':host_key,'root_object_id':root_object['object_id'],'interpreter_alias_id':interpreter_alias['alias_id'],
            'objects':sorted(objects.values(),key=lambda v:v['path']),'aliases':sorted(aliases.values(),key=lambda v:(v['requested_path'],v['alias_id'])),
            'needed_edges':sorted(edges,key=lambda v:(v['source_object_id'],v['needed_ordinal'])),'selectors':selectors,'trace':trace,
            'loading_policy':{'route':'cpu-internal-tblite','plugin_policy':'none','environment_policy':'no-ld-overrides','trace_policy':'direct-ld-trace-before-child-and-publication','dynamic_loading_review_sha256':review_sha256},'evidence_manifest_sha256':evidence_sha256}
    cl_validate(result)
    # Re-read every named object after the bounded loader observation.
    for alias in result['aliases']:cl_require(cl_alias(alias['requested_path'])==alias,'alias changed during observation')
    for obj in result['objects']:cl_require(cl_file(obj['path'],elf=True)=={k:v for k,v in obj.items() if k!='object_id'},'object changed during observation')
    return result


def cl_validate(value):
    def keys(v,expected):cl_require(type(v) is dict and set(v)==set(expected),'closed fields')
    def digest(v):cl_require(type(v) is str and _cl_re.fullmatch('[0-9a-f]{64}',v),'digest')
    def file(v):
        keys(v,('path','device','inode','size_bytes','sha256'));cl_path(v['path']);digest(v['sha256'])
        cl_require(all(type(v[k]) is int and v[k]>=0 for k in ('device','inode','size_bytes')) and v['inode']>0 and v['size_bytes']<=256*1024*1024,'file integers')
    def alias(v):
        keys(v,('alias_id','requested_path','canonical_path','state','nodes'));digest(v['alias_id']);cl_requested(v['requested_path'])
        cl_require(v['state'] in ('present','absent') and type(v['nodes']) is list and 0<len(v['nodes'])<=512,'alias fields')
        if v['state']=='present':cl_path(v['canonical_path'])
        else:cl_require(v['canonical_path']=='','absent alias canonical')
        for node in v['nodes']:
            keys(node,('path','kind','device','inode','link_target'))
            if node['path']!='/':cl_path(node['path'])
            cl_require(node['kind'] in ('directory','link','regular') and type(node['device']) is int and node['device']>=0 and type(node['inode']) is int and node['inode']>0 and type(node['link_target']) is str,'alias node')
            cl_require(bool(node['link_target'])==(node['kind']=='link') and '\x00' not in node['link_target'],'alias link')
        cl_require(cl_id({k:v[k] for k in v if k!='alias_id'})==v['alias_id'],'alias digest')
    keys(value,('schema','host_key','root_object_id','interpreter_alias_id','objects','aliases','needed_edges','selectors','trace','loading_policy','evidence_manifest_sha256'))
    cl_require(value['schema']=='v31-crest-loader-closure/1','schema')
    for key in ('host_key','root_object_id','interpreter_alias_id','evidence_manifest_sha256'):digest(value[key])
    policy=value['loading_policy'];keys(policy,('route','plugin_policy','environment_policy','trace_policy','dynamic_loading_review_sha256'))
    cl_require({k:v for k,v in policy.items() if k!='dynamic_loading_review_sha256'}=={'route':'cpu-internal-tblite','plugin_policy':'none','environment_policy':'no-ld-overrides','trace_policy':'direct-ld-trace-before-child-and-publication'},'policy');digest(policy['dynamic_loading_review_sha256'])
    cl_require(type(value['objects']) is list and 2<=len(value['objects'])<=64 and type(value['aliases']) is list and 2<=len(value['aliases'])<=128,'inventory bounds')
    objects={};paths=[]
    for obj in value['objects']:
        keys(obj,('object_id','path','device','inode','size_bytes','sha256','elf'));file({k:obj[k] for k in ('path','device','inode','size_bytes','sha256')})
        digest(obj['object_id']);cl_require(cl_id({k:v for k,v in obj.items() if k!='object_id'})==obj['object_id'] and obj['object_id'] not in objects,'object identity')
        elf=obj['elf'];keys(elf,('class','endian','machine','type','interpreter','needed','soname','rpath','runpath'))
        cl_require(elf['class']==64 and type(elf['class']) is int and elf['endian']=='little' and elf['machine']==62 and type(elf['machine']) is int and type(elf['type']) is int and elf['type'] in (2,3),'ELF target')
        cl_require(type(elf['needed']) is list and len(elf['needed'])<=64 and len(set(elf['needed']))==len(elf['needed']) and all(type(n) is str and _cl_re.fullmatch(r'[A-Za-z0-9_.+\-]+',n) for n in elf['needed']),'NEEDED')
        cl_require(all(type(elf[k]) is str and '\x00' not in elf[k] for k in ('interpreter','soname','rpath','runpath')),'ELF text')
        if elf['interpreter']:cl_path(elf['interpreter'])
        objects[obj['object_id']]=obj;paths.append(obj['path'])
    cl_require(paths==sorted(set(paths)) and value['root_object_id'] in objects,'object order/root')
    cl_require(sum(o['size_bytes'] for o in objects.values())<=512*1024*1024,'aggregate ELF budget')
    aliases={};alias_order=[]
    for a in value['aliases']:
        alias(a);cl_require(a['state']=='present' and a['canonical_path'] in paths and a['alias_id'] not in aliases,'object alias');aliases[a['alias_id']]=a;alias_order.append((a['requested_path'],a['alias_id']))
    cl_require(alias_order==sorted(set(alias_order)) and value['interpreter_alias_id'] in aliases,'alias order/interpreter')
    interpreter=aliases[value['interpreter_alias_id']]
    cl_require(interpreter['requested_path']==objects[value['root_object_id']]['elf']['interpreter'],'PT_INTERP alias')
    path_to_id={o['path']:i for i,o in objects.items()};seen=set();edges=value['needed_edges'];cl_require(type(edges) is list and len(edges)<=4096,'edges')
    adjacency={i:[] for i in objects}
    for edge in edges:
        keys(edge,('source_object_id','needed_ordinal','requested_name','alias_id','target_object_id'))
        source=edge['source_object_id'];target=edge['target_object_id'];ordinal=edge['needed_ordinal']
        cl_require(source in objects and target in objects and edge['alias_id'] in aliases and type(ordinal) is int and 0<=ordinal<len(objects[source]['elf']['needed']),'edge references')
        cl_require(objects[source]['elf']['needed'][ordinal]==edge['requested_name'] and aliases[edge['alias_id']]['canonical_path']==objects[target]['path'] and (source,ordinal) not in seen,'edge mapping')
        seen.add((source,ordinal));adjacency[source].append(target)
    cl_require([(e['source_object_id'],e['needed_ordinal']) for e in edges]==sorted(seen) and seen=={(i,n) for i,o in objects.items() for n in range(len(o['elf']['needed']))},'complete ordered NEEDED edges')
    reached=set();todo=[value['root_object_id'],path_to_id[interpreter['canonical_path']]]
    while todo:
        i=todo.pop()
        if i not in reached:reached.add(i);todo.extend(adjacency[i])
    cl_require(reached==set(objects),'recursive closure')
    selectors=value['selectors'];cl_require(type(selectors) is list and len(selectors)==2,'selectors')
    for selector,path in zip(selectors,('/etc/ld.so.cache','/etc/ld.so.preload')):
        keys(selector,('path','state','alias','file'));alias(selector['alias'])
        cl_require(selector['path']==path==selector['alias']['requested_path'] and selector['state']==selector['alias']['state'],'selector path/state')
        if selector['state']=='present':
            file(selector['file']);cl_require(selector['file']['path']==selector['alias']['canonical_path'],'selector file')
            if path.endswith('preload'):cl_require(selector['file']['size_bytes']==0,'global preload')
        else:cl_require(selector['file']=={},'absent selector file')
    trace=value['trace'];keys(trace,('objects','kernel_objects','searches'));cl_require(trace['kernel_objects']==['linux-vdso.so.1'] and type(trace['objects']) is list and 0<len(trace['objects'])<=64,'trace')
    cl_require(type(trace['searches']) is list and len(trace['searches'])<=64,'searches')
    search_names=[]
    for search in trace['searches']:
        keys(search,('name','events'));cl_require(type(search['name']) is str and _cl_re.fullmatch(r'[A-Za-z0-9_.+\-]+',search['name']),'search name');search_names.append(search['name'])
        events=search['events'];cl_require(type(events) is list and 0<len(events)<=512,'search events')
        lines=['1: find library='+search['name']+' [0]; searching']
        for event in events:
            kind=event.get('kind') if type(event) is dict else None
            if kind in ('RPATH','RUNPATH','system'):
                keys(event,('kind','paths','source') if kind!='system' else ('kind','paths'))
                cl_require(type(event['paths']) is list and 0<len(event['paths'])<=512,'search paths')
                [cl_requested(p) for p in event['paths']]
                suffix='system search path' if kind=='system' else kind+' from file '+cl_requested(event['source'])
                lines.append('1: search path='+':'.join(event['paths'])+' ('+suffix+')')
            elif kind=='cache':keys(event,('kind',));lines.append('1: search cache=/etc/ld.so.cache')
            elif kind=='try':keys(event,('kind','path'));lines.append('1: trying file='+cl_requested(event['path']))
            else:raise ValueError('crest-loader: unknown search event')
        cl_require(cl_searches(('\n'.join(lines)+'\n1:\n').encode())==[search],'search normalization')
    cl_require(len(set(search_names))==len(search_names),'duplicate search')
    names=[];traced=set()
    for record in trace['objects']:
        keys(record,('name','path'));cl_requested(record['path']);cl_require(type(record['name']) is str,'trace name')
        matching=[a for a in aliases.values() if a['requested_path']==record['path']];cl_require(len(matching)==1,'trace alias')
        traced.add(path_to_id[matching[0]['canonical_path']]);names.append(record['name'])
    cl_require(len(set(names))==len(names) and '' in names and traced==set(objects)-{value['root_object_id']},'trace closure')
    for edge in edges:
        record=[r for r in trace['objects'] if r['name']==edge['requested_name']]
        if not record and edge['requested_name']==objects[path_to_id[interpreter['canonical_path']]]['elf']['soname'] and edge['target_object_id']==path_to_id[interpreter['canonical_path']]:
            record=[r for r in trace['objects'] if r['name']=='']
        if not record:
            search=[s for s in trace['searches'] if s['name']==edge['requested_name']]
            cl_require(len(search)==1,'missing dedup search')
            selected=cl_dedup_candidate(search[0],objects[value['root_object_id']]['path'])
            cl_require(selected==aliases[edge['alias_id']]['requested_path'] and edge['target_object_id'] in traced,'dedup selected mapped object')
            record=[{'path':selected}]
        cl_require(len(record)==1 and record[0]['path']==aliases[edge['alias_id']]['requested_path'],'trace NEEDED selection')
    return value


def cl_guard(root, expected):
    _cl_diagnostics.clear();_cl_diagnostics['phase']='guard-precheck'
    try:
        cl_validate(expected)
        cl_recheck(expected)
        actual=cl_observe(root,expected['host_key'],expected['loading_policy']['dynamic_loading_review_sha256'],expected['evidence_manifest_sha256'])
        _cl_diagnostics['phase']='guard-compare'
        cl_require(actual==expected,'current loader closure drift')
        _cl_diagnostics['phase']='guard-postcheck'
        cl_recheck(expected)
    except Exception as error:
        error.loader_diagnostics=dict(_cl_diagnostics)
        raise


def cl_recheck(expected):
    for alias in expected['aliases']:cl_require(cl_alias(alias['requested_path'])==alias,'fixed alias drift before trace')
    for obj in expected['objects']:cl_require(cl_file(obj['path'],elf=True)=={k:v for k,v in obj.items() if k!='object_id'},'fixed object drift before trace')
    cl_require(cl_selectors()==expected['selectors'],'fixed selector drift before trace')
'''


def _namespace():
    namespace = {}
    exec(compile(_SOURCE, "<fixed-crest-loader>", "exec"), namespace)
    return namespace


def _validate_closure(value):
    return _namespace()["cl_validate"](value)


__all__: tuple[str, ...] = ()

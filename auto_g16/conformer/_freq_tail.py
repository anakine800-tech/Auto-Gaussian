"""Narrow A.03 Freq tail evidence, reconstructed only from source-replayed bytes."""
import re
from hashlib import sha256
from .refinement_authority import _require
from auto_g16.execution._gaussian_freq_resources import ROUTE


def frequency_tail(log, facts):
    _require(sha256(log).hexdigest() == facts['source_artifact']['sha256']
             and len(log) == facts['source_artifact']['size_bytes'], 'Freq tail raw source differs')
    markers = (facts['optimization_completed_evidence'], facts['stationary_point_evidence'])
    if not any(markers) and not facts['optimization_completed_marker'] and not facts['stationary_point_marker']:
        return None
    _require(all(len(x) == 1 for x in markers), 'Freq tail marker inventory differs')
    section = facts['job_section']
    start, end = section['start'], section['end']
    raw = log[start:end]
    def one(pattern, after=0):
        matches = [m for m in re.finditer(pattern, raw, re.M) if m.start() >= after]
        _require(len(matches) == 1, 'Freq tail execution grammar is not unique')
        return matches[0]
    def span(match):
        return {**facts['source_artifact'], 'start': start+match.start(), 'end': start+match.end()}
    one(rb'^ Gaussian 16: +[^\r\n]*G16RevA\.03 [^\r\n]+$')
    route = one(rb'^ +-+\n( #p [^\n]+\n(?: [^-#\n][^\n]*\n)*?) +-+\n')
    _require(b''.join(line.strip() for line in route.group(1).splitlines()) == ROUTE.encode(), 'Freq output route differs')
    archive = one(rb'^ 1\\1\\[^\n]*(?:\n (?!1\\1\\)[^\n]*)*?@\n')
    flat = b''.join(line.strip() for line in archive.group().splitlines())
    fields = flat.split(b'\\')
    _require(len(fields) > 5 and fields[3] == b'Freq', 'Freq archive job type differs')
    _require(flat.count(b'\\\\#p ') == 1 and flat.split(b'\\\\')[1] == ROUTE.encode(), 'Freq archive route differs')
    enter101 = one(rb'^ \(Enter [^\n]*?/l101\.exe\)\n')
    leave716 = one(rb'^ Leave Link +716 at [^\n]+\n')
    enter103 = one(rb'^ \(Enter [^\n]*?/l103\.exe\)\n', leave716.end())
    step = one(rb'^ Step number +1 out of a maximum of +2\n')
    opt = one(rb'^ Optimization completed\.\n')
    stationary = one(rb'^    -- Stationary point found\.\n')
    leave103 = one(rb'^ Leave Link +103 at [^\n]+\n', leave716.end())
    enter9999 = one(rb'^ \(Enter [^\n]*?/l9999\.exe\)\n')
    _require(facts['frequency_blocks'] and len(facts['geometry_blocks']) == 1
             and len(facts['scf_calculations']) == 1, 'Freq tail requires one geometry and SCF')
    last = facts['frequency_blocks'][-1]['source_span']['end']-start
    first_geometry = facts['geometry_blocks'][0]['source_span']['start']-start
    _require(route.end() <= enter101.start() < enter101.end() <= first_geometry < last <= leave716.start()
             < leave716.end() <= enter103.start() < enter103.end() <= step.start()
             < step.end() <= opt.start() < opt.end() == stationary.start()
             < stationary.end() <= leave103.start() < leave103.end() <= enter9999.start()
             < enter9999.end() <= archive.start(), 'Freq tail execution order differs')
    _require(not re.search(rb'^ \(Enter ', raw[last:leave716.start()], re.M), 'Freq tail contains an extra link before exit')
    tail = raw[leave716.start():enter9999.end()]
    _require(len(re.findall(rb'^ Step number ', raw, re.M)) == 1
             and len(re.findall(rb'^ \(Enter ', tail, re.M)) == 2
             and len(re.findall(rb'^ Leave Link ', tail, re.M)) == 2,
             'Freq tail contains another execution step')
    _require(not re.search(rb'(?im)^.*(?:SCF Done:|orientation:|Frequencies --|Entering Gaussian|--Link1--)', tail),
             'Freq tail contains another evaluation')
    _require(markers[0][0] == span(opt) and markers[1][0] == span(stationary), 'Freq tail marker spans differ')
    return {'schema':'v31-gaussian-freq-tail-evidence/1', 'form':'g16-a03-freq-l716-l103/1',
            'source_artifact':facts['source_artifact'], 'job_section':section,
            'route_echo_span':span(route), 'archive_span':span(archive),
            'tail_span':{**facts['source_artifact'], 'start':start+leave716.start(), 'end':start+enter9999.end()},
            'optimization_completed_span':span(opt), 'stationary_point_span':span(stationary)}

"""Read persisted condition packets independent of Result summary success."""
from auto_g16.query import QueryError
from .details import read_json,document
from .conditions import validate,SCHEMA

def conditions(query,identity):
    try:
        record=query.archives.get_archive(identity)['data'];entry=query._entry('archive',identity)
        log=next(x for x in record['artifacts'] if x['role']=='log')
        observed=None
        if 'conditions' in entry:observed=validate(read_json(entry['conditions']),log,log['logical_name'])
        declarations=[]
        if 'input_conditions' in entry:
            saved=read_json(entry['input_conditions'])
            if saved['archive_id']!=identity:raise ValueError('input conditions identity mismatch')
            for item in saved['items']:
                # References explicitly refer to historical inputs, not established log bindings.
                if item['log_binding']!='unknown':raise ValueError('unexpected log binding')
                document(item['input']);packet=validate(item['conditions'],item['input'])
                if item['submission_binding']=='sha256-verified':
                    verified={i['sha256'] for c in query.get_history_links(identity)['candidates'] for i in c['inputs']}
                    if item['input']['sha256'] not in verified:raise ValueError('submission binding unavailable')
                elif item['submission_binding']!='unverified-source-file':raise ValueError('invalid input provenance')
                declarations.append(dict(name=item['name'],submission_binding=item['submission_binding'],binding='input-declaration-log-binding-unknown',conditions=packet))
        return dict(schema='autog-conditions-view/1',id=identity,observed=observed,declarations=declarations)
    except QueryError:raise
    except (ValueError,KeyError,TypeError,OSError):raise QueryError('invalid-evidence') from None

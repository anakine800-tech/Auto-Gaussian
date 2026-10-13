"""Exact Q8 native functions on a local virtual filesystem, no child process.

The OS path adapter emulates the server namespace using real temporary inodes.
It is offline identity/recomputation evidence, not native target qualification.
The full unchanged loader stops after wrapper-handoff, before Gaussian launch.
"""
import base64
import copy
import json
import os
from pathlib import Path
import shlex
from types import SimpleNamespace

from auto_g16.execution import _gaussian_freq_resources as freq
from auto_g16.execution._program_artifacts import _stage_material
from auto_g16.transport import _gaussian_freq_submit as submit


class _OS:
    def __init__(self, root, workspace):
        self.root, self.workspace = root, workspace
        self.environ = {'PBS_JOBID':'123.server'}
    def __getattr__(self, name): return getattr(os, name)
    def _path(self, path, kw):
        if isinstance(path,str) and path.startswith('/'):
            return str(self.root/path.lstrip('/'))
        if path == '.' and 'dir_fd' not in kw: return str(self.workspace)
        return path
    def open(self, path, *args, **kw): return os.open(self._path(path,kw),*args,**kw)
    def stat(self, path, *args, **kw): return os.stat(self._path(path,kw),*args,**kw)


def run(test, snapshot, raw, *, negative=False):
    root=test.root/('virtual-server-negative' if negative else 'virtual-server-positive');root.mkdir(mode=0o700)
    workspace=root/snapshot.workspace_binding.remote_attempt_dir.lstrip('/')
    workspace.mkdir(parents=True,mode=0o700);workspace.parent.chmod(0o700)
    py=root/'usr/bin/python3';py.parent.mkdir(parents=True);py.write_bytes(b'python')
    proxy=_OS(root,workspace)
    ns={'__name__':'inert_associated_native'}
    exec(compile(submit.source_bytes().decode().split('try: main()\n',1)[0],'<exact-Q8-native>','exec'),ns)
    ns['os']=proxy
    loader={'__name__':'inert_associated_loader'}
    # Execute the exact compressed outer source, not a copied identity algorithm.
    exec(compile(freq._LOADER_SOURCE,'<exact-Q8-outer-loader>','exec'),loader)
    loader['os']=proxy
    loader['sys']=SimpleNamespace(executable='/usr/bin/python3',argv=[],stdin=None)
    fd,token=ns['directory'](snapshot.workspace_binding.remote_attempt_dir)
    pfd,ptoken=ns['directory'](snapshot.project_physical_binding.remote_project_dir)
    try:
        staged=[];rows=[]
        artifacts=_stage_material(snapshot,input_bytes={'flow.gjf':raw},scheduler_artifact_bytes={a['portable_name']:a['content_utf8'].encode() for a in snapshot.scheduler_artifacts})
        for index,(declaration,data) in enumerate(artifacts):
            name=declaration['portable_name'];file=workspace/name;file.write_bytes(data);file.chmod(0o600)
            physical=ns['g_b64'](ns['g_json'](['v31-file/1',token,name,ns['g_ident'](file.stat())]))
            staged.append({**declaration,'artifact_physical_token':physical})
            if index:
                rows.append({'role':ns['G_ROLES'][index-1],'artifact_authority_id':'a'+str(index),'stage_receipt_id':'s'+str(index),
                    'stage_receipt_payload_sha256':'1'*64,'physical_token_base64':physical})
        b={'remote_workspace':snapshot.workspace_binding.remote_attempt_dir,'workspace_physical_token':token,
           'project_directory':snapshot.project_physical_binding.remote_project_dir,'project_physical_identity':ptoken,
           'attempt_id':snapshot.attempt_id,'program_execution_snapshot_id':snapshot.program_execution_snapshot_id,
           'effect_intent_id':snapshot.effect_intent_id,'resolved_server_profile_id':snapshot.resolved_server_profile.resolved_server_profile_id}
        predecessor={k:k for k in ('transport_store_id','store_instance_id','runtime_attestation_id','workspace_authority_id','allocation_receipt_id')}
        predecessor['allocation_receipt_payload_sha256']='3'*64
        # The shell-quoted loader contains newlines; tokenize the whole command.
        command=snapshot.scheduler_artifacts[0]['content_utf8'].partition('\nexec ')[2]
        constants=json.loads(base64.b64decode(shlex.split(command)[-2]))
        p={'request_payload':{'scheduler_portable_name':'gaussian.pbs','scheduler_artifact_authority_id':'a1','program_input_artifact_authority_ids':['science'],
             'startup_payload_artifact_authority_ids':['a2'],'handoff_artifact_authority_ids':['a3','a4']},'resources':constants['resources'],'staged':staged,
           'launch_context':{'project_id':snapshot.project_physical_binding.project_id,'project_physical_binding_id':snapshot.project_physical_binding_id,
             'workspace_binding_id':snapshot.workspace_binding.workspace_binding_id,'approvals':{k:{'authority_id':k,'payload_sha256':'2'*64} for k in ('scientific','finite_batch','operational_confirmation','live_gate')},
             'predecessor':predecessor,'stages':rows}}
        calls=[]
        def inert_qsub(*args):calls.append(args);return 0,b'123.server\n',b''
        ns['run_exact']=inert_qsub
        test.assertEqual(ns['g_submit'](b,p,{'server_qsub':{'path':'/inert/qsub'}},fd,pfd),{'job_id':'123.server'})
        test.assertEqual(len(calls),1)
        command=(workspace/ns['G_ENTRY']).read_text().partition('\nexec ')[2]
        carrier=shlex.split(command)[-1]
        if not negative:
            class HandoffReached(Exception): pass
            publish=loader['g_publish'];stages=[]
            def observed_publish(*args):
                value=publish(*args)
                stages.append(args[2])
                if args[2]=='.auto-g16-v31-wrapper-handoff.json':raise HandoffReached()
                return value
            loader['g_publish']=observed_publish
            with test.assertRaises(HandoffReached):loader['g_loader'](constants,carrier)
            test.assertEqual(stages,['.auto-g16-v31-entry-start.json','.auto-g16-v31-payload-verified.json','.auto-g16-v31-wrapper-handoff.json'])
            test.assertFalse((workspace/'gaussian.log').exists())
            return
        # Rejections precede any stage publication, so they can share the fixture.
        for key in ('project_physical_binding_id','resolved_server_profile_id'):
            changed=copy.deepcopy(constants);changed[key]='wrong-binding'
            with test.assertRaises(ValueError):loader['g_loader'](changed,carrier)
        marker=workspace/'.auto-g16-v31-submit-intent';saved=marker.read_bytes()
        marker.write_bytes(saved.replace(snapshot.effect_intent_id.encode(),b'x'*len(snapshot.effect_intent_id)))
        with test.assertRaises(ValueError):loader['g_loader'](constants,carrier)
        # Restoring bytes changes metadata; use a separate positive fixture rather
        # than silently accepting changed physical stage identities.
        return constants, carrier, ns, loader, workspace, saved
    finally:
        os.close(fd);os.close(pfd)

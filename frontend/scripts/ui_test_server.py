"""Disposable synthetic-store server for browser tests; never reads business data."""
import tempfile
import os
import sys
import json
import hashlib
from pathlib import Path

if '--installed' not in sys.argv:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from auto_g16 import core
from autog_frontend.api import create_app
import uvicorn
import autog_frontend
# Test fixture imports only; -I keeps installed packages ahead of this path.
sys.path.append(str(Path(__file__).resolve().parents[1]))
from tests.result_fixture import add_result_fixtures

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="autog-ui-test-") as temporary:
        database = Path(temporary).resolve() / "core.sqlite3"
        with core.SQLiteRuntimeStore(database) as store:
            store.store_project(core.Project(project_id="测试%2F?project"))
            store.store_project(core.Project(project_id="empty"))
            store.store_workflow_run(core.WorkflowRun(workflow_run_id="run", project_id="测试%2F?project", workflow_name="Synthetic workflow"))
            for task_id in ("task", "without-attempt"):
                store.store_task(core.Task(task_id=task_id, workflow_run_id="run", task_kind="fixture"))
            store.create_attempt(core.Attempt(attempt_id="attempt%2F中文", task_id="task", ordinal=1))
            store.record_submission_intent("attempt%2F中文", "intent")
            store.record_submission_outcome("attempt%2F中文", "intent", core.SubmissionOutcome.UNKNOWN)
            store.append_result(core.Result(result_id="future", attempt_id="attempt%2F中文", result_type="future-result/1", data={"private": "must-not-expose"}))
            add_result_fixtures(store)
            mode_entry = None
            if os.environ.get('AUTOG_TEST_MODE_REVIEW') == '1' or os.environ.get('AUTOG_TEST_CONTEXT') == '1':
                from tests.mode_review_fixture import add_mode_review_fixture
                from tests.test_result_context import INTENT
                mode_entry = add_mode_review_fixture(store,Path(temporary).resolve(),intent=INTENT if os.environ.get('AUTOG_TEST_CONTEXT') == '1' else None)
        installed = '--installed' in sys.argv
        if installed and 'site-packages' not in autog_frontend.__file__:
            raise RuntimeError('installed test must use wheel package')
        ui_directory = (Path(autog_frontend.__file__).resolve().parent / 'ui' if installed else
                        Path(__file__).resolve().parents[1] / 'web/dist')
        from tests.archive_fixture import archive_capture
        from autog_frontend.archive_import import build_archive_evidence
        from autog_frontend.archive import SCHEMA
        source_root = Path(temporary).resolve()
        archive_index = source_root / 'archive-index.json'
        record, outcome = build_archive_evidence(archive_capture(source_root))
        raw = json.dumps({'schema': SCHEMA, 'records': [record]}).encode()
        archive_index.write_bytes(raw)
        def artifact_ref(p):
            b=p.read_bytes()
            return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'size_bytes':len(b)}
        parse_file=source_root/'parse.json'; parse_file.write_text(json.dumps(outcome))
        catalog=source_root/'catalog.json'
        catalog.write_text(json.dumps({'schema':'auto-g16-local-evidence-catalog/1','entries':[
            {'kind':'archive','id':record['archive_id'],'log':artifact_ref(source_root/'synthetic.log'),
             'job':artifact_ref(source_root/'job.json'),'parse_outcome':artifact_ref(parse_file)}]+([mode_entry] if mode_entry else [])}))
        review_directory = None
        if mode_entry and os.environ.get('AUTOG_TEST_MODE_REVIEW') == '1':
            review_directory=source_root/'mode-reviews';review_directory.mkdir()
        archive_options = {'archive_index': archive_index, 'archive_sha256': hashlib.sha256(raw).hexdigest(),
                           'evidence_catalog': catalog,'evidence_sha256':artifact_ref(catalog)['sha256']}
        if os.environ.get('AUTOG_TEST_CONDITIONS')=='1':
            from tests.test_project_conditions import LOG,INPUT
            from autog_frontend.local_import import import_folder
            folder=source_root/'condition-source';study=folder/'study-A';study.mkdir(parents=True)
            (study/'failed.log').write_bytes(LOG);(study/'input.gjf').write_bytes(INPUT)
            (study/'job.pbs').write_text('#!/bin/bash\n#PBS -l nodes=1:ppn=8\n')
            (study/'submission-intent.json').write_text(json.dumps(dict(schema='gaussian-submission-intent/1',input_sha256=hashlib.sha256(INPUT).hexdigest(),attempt_id='historical-only')))
            seed=source_root/'seed.json';seed.write_text(json.dumps(dict(database=str(database),archive_index=str(archive_index),archive_sha256=artifact_ref(archive_index)['sha256'],evidence_catalog=str(catalog),evidence_sha256=artifact_ref(catalog)['sha256'])))
            import_folder(folder,source_root/'conditions-batch',seed)
            enriched=json.loads((source_root/'conditions-batch/profile.json').read_text())
            archive_options={k:Path(enriched[k]) if k in ('archive_index','evidence_catalog') else enriched[k] for k in archive_options}
        library_manager=None
        if os.environ.get('AUTOG_TEST_LIBRARY')=='1':
            from autog_frontend.library import LibraryManager
            from tests.result_fixture import PREFIX,FREQUENCY
            from tests.test_vibrations import GEOMETRY,VECTORS
            seed=source_root/'profile.json'
            seed.write_text(json.dumps(dict(database=str(database),archive_index=str(archive_index),archive_sha256=artifact_ref(archive_index)['sha256'],evidence_catalog=str(catalog),evidence_sha256=artifact_ref(catalog)['sha256'])))
            library_manager=LibraryManager(source_root/'settings.json',seed)
            library_manager.configure(dict(root=str(source_root/'library'),auto_archive=True))
            recovered=source_root/'fetch-complete';recovered.mkdir()
            (recovered/'recovered.log').write_bytes(PREFIX+GEOMETRY+FREQUENCY+VECTORS+b' Normal termination of Gaussian 16\n'+b' \n'*(1024*1024))
            inp=recovered/'recovered.gjf';inp.write_text('#p hf/sto-3g opt freq\n\nRecovered test\n\n0 1\nH 0 0 0\n\n')
            (recovered/'submission-intent.json').write_text(json.dumps(dict(schema='gaussian-submission-intent/1',input_sha256=artifact_ref(inp)['sha256'],attempt_id='historic-test-attempt')))
        monitor=None
        if os.environ.get('AUTOG_TEST_WORKFLOW')=='1':
            from tests.test_workflows import Monitor,monitor as monitor_fixture,receipt,observation
            with core.SQLiteRuntimeStore(database) as store:
                store.store_project(core.Project(project_id='workflow-live-project'))
                store.store_workflow_run(core.WorkflowRun(workflow_run_id='workflow-live-run',project_id='workflow-live-project',workflow_name='运行联测'))
                store.store_task(core.Task(task_id='workflow-live-task',workflow_run_id='workflow-live-run',task_kind='synthetic-readonly'))
                store.create_attempt(core.Attempt(attempt_id='workflow-live-attempt',task_id='workflow-live-task',ordinal=1))
                store.append_observation(observation(receipt('workflow-live-attempt')))
            monitor=Monitor(monitor_fixture())
            monitor.start=lambda:None
            monitor.close=lambda:None
        task_queue=None
        if os.environ.get('AUTOG_TEST_OPERATIONS')=='1':
            from tests.test_operations import Gateway,CYCLE
            from tests.test_vibrations import GEOMETRY
            from tests.result_fixture import PREFIX,FREQUENCY
            from autog_frontend.task_queue import TaskQueue
            from autog_frontend.local_import import import_folder
            folder=source_root/'operations-source';study=folder/'screening-fixtures';study.mkdir(parents=True)
            for n in range(2):
                raw=PREFIX.replace(b' SCF Done:',GEOMETRY+b' SCF Done:')+CYCLE.replace(b'-75.00',b'-75.01')+FREQUENCY+b' Normal termination of Gaussian 16\n'
                (study/f'candidate-{n}.log').write_bytes(raw.replace(b'-75.01',b'-75.02' if n else b'-75.01'))
            seed=source_root/'operations-seed.json';seed.write_text(json.dumps(dict(database=str(database),**{k:str(v) if isinstance(v,Path) else v for k,v in archive_options.items()})))
            import_folder(folder,source_root/'operations-batch',seed)
            prepared=json.loads((source_root/'operations-batch/profile.json').read_text())
            archive_options={k:Path(prepared[k]) if k in ('archive_index','evidence_catalog') else prepared[k] for k in archive_options}
            queue_dir=source_root/'task-queue';queue_dir.mkdir()
            task_queue=TaskQueue(queue_dir,Gateway())
        app = create_app(database, token="" if os.environ.get("AUTOG_TEST_NO_TOKEN") == "1" else "browser-test-only-" + "0" * 32,
                         local_no_token=os.environ.get("AUTOG_TEST_NO_TOKEN") == "1",
                         ui_directory=ui_directory, mode_review_directory=review_directory, library_manager=library_manager, monitor=monitor, task_queue=task_queue, **archive_options)
        uvicorn.run(app, host="127.0.0.1", port=18765, access_log=False,
                    proxy_headers=False, server_header=False, log_level="warning")

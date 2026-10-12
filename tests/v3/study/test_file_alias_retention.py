"""Real SQLite lock retention after an existing-file open races a DB alias."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.v3.study.test_installation import Fixture
from tests.v3.study.test_stage_session import CHILD as SESSION_CHILD

CHILD = SESSION_CHILD.split("if mode.startswith('close-')")[0] + r'''
import sqlite3
from tests.v31.transport.test_publisher_pilot_orchestration import file_binding
real_open,real_close,real_fstat=os.open,os.close,os.fstat
opened=[];closed=[];original=KeyboardInterrupt('synthetic first identity failure')
owners=None;session=None;connection=None
path=root/'pin-evidence';path.write_bytes(b'original synthetic reader evidence')
binding=file_binding(path)
def raced(name,flags,*args,**kwargs):
 if str(name)==path.name and not flags & os.O_DIRECTORY and not opened:
  connection.execute('BEGIN EXCLUSIVE')
  path.unlink();os.link(database,path)
  fd=real_open(name,flags,*args,**kwargs)
  opened.append(fd)
  path.unlink()  # Restore DB nlink=1; the opened alias remains dangerous to close.
  return fd
 return real_open(name,flags,*args,**kwargs)
def identify(fd):
 if opened and fd==opened[0] and mode.endswith('unclassified'):raise original
 return real_fstat(fd)
def close(fd):
 if opened and fd==opened[0]:closed.append(fd);raise AssertionError('unsafe alias close')
 return real_close(fd)
try:
 with r.open_registered(sid) as scope:
  owners=dict(scope.stores);connection=owners['core']._connection
  with native._open_study_xtb_session(scope,'review') as session:
   database=Path(session._store_bindings['core']['path'])
   if mode.startswith('business'):
    directory=files.root(session,'reviews')
    path=Path(directory.path)/'xtb-preparation.json'
    path.write_bytes(b'{}')
   with patch.object(os,'open',raced),patch.object(os,'fstat',identify),patch.object(os,'close',close):
    if mode.startswith('business'):directory.read(path.name)
    else:rtwin._PinnedPublisherFile(binding,1024)
except BaseException as error:
 assert error is original if mode.endswith('unclassified') else isinstance(error,native.ExecutionValueError),repr(error)
else:raise AssertionError('aliased file accepted')
assert len(opened)==1 and not closed
assert scope._session_unresolved and r._RETAINED and native._PROCESS_LOCK.locked()
assert all(not owner._closed for owner in owners.values())
assert connection.in_transaction and r.installed._FACTS is not None
record=session._unknown[0]
assert record['retention_cause']==('file-identity-unclassified' if mode.endswith('unclassified') else 'store-alias')
assert not record['attempted'] and opened[0] in record['descriptors']
assert (real_fstat(opened[0]).st_dev,real_fstat(opened[0]).st_ino)==tuple(session._store_bindings['core']['file_identity'])
child=os.fork()
if child==0:
 other=sqlite3.connect(str(database),timeout=0)
 try:other.execute('BEGIN IMMEDIATE')
 except sqlite3.OperationalError as error:
  os._exit(0 if error.sqlite_errorcode==sqlite3.SQLITE_BUSY else 10)
 os._exit(9)
assert os.waitpid(child,0)[1]==0,'original SQLite lock was released'
token=native._CURRENT.set(session)
try:
 with patch.object(os,'close',side_effect=AssertionError('retained descriptor closed again')):
  reject(lambda:session.close_resource(record['resource']))
finally:native._CURRENT.reset(token)
reject(reopen);locks_retained()
print('real SQLite lock retained after '+mode)
'''


class OpenedAliasRetentionTests(unittest.TestCase):
    def run_case(self, mode):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            Fixture(root, full=True)
            result = subprocess.run([sys.executable, '-B', '-c', CHILD, str(root), mode],
                cwd=root/'bundle'/'source', capture_output=True, text=True, timeout=240)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_business_alias_retains_real_lock(self):self.run_case('business-alias')
    def test_publisher_alias_retains_real_lock(self):self.run_case('publisher-alias')
    def test_business_unclassified_retains_original_exception(self):self.run_case('business-unclassified')
    def test_publisher_unclassified_retains_original_exception(self):self.run_case('publisher-unclassified')

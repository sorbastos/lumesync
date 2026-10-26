import fcntl
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from lumesync.instance import SingleInstance

ROOT = Path(__file__).resolve().parents[1]
CHILD = r'''
import sys,time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QCoreApplication,QTimer
from lumesync.instance import SingleInstance
app=QCoreApplication([])
folder=Path(sys.argv[2])
instance=SingleInstance(folder/'profile',runtime_dir=folder/'runtime')
try:
 if instance.start():
  (folder/'primary').write_text(str(__import__('os').getpid()))
  def activated():
   with (folder/'activations').open('a') as handle:handle.write('show\n')
  instance.activation_requested.connect(activated)
  if len(sys.argv)>3:time.sleep(float(sys.argv[3]))
  QTimer.singleShot(10000,app.quit)
  app.exec()
 else:
  print('FORWARDED',flush=True)
finally:
 instance.close()
'''
GUI = r'''
import os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
folder=Path(sys.argv[2])
os.environ['QT_QPA_PLATFORM']='offscreen'
os.environ['LUMESYNC_DATA_DIR']=str(folder/'profile')
os.environ['XDG_RUNTIME_DIR']=str(folder/'runtime')
os.environ['XDG_CONFIG_HOME']=str(folder/'config')
from PySide6.QtCore import QTimer
from lumesync import app as module
original=module.Window
class Window(original):
 def __init__(self):
  super().__init__()
  with (folder/'windows').open('a') as handle:handle.write('window\n')
  def hide_first():
   self.hide()
   (folder/'hidden').touch()
  QTimer.singleShot(30,hide_first)
  QTimer.singleShot(10000,self.request_quit)
 def restore_window(self):
  super().restore_window()
  (folder/'restored').write_text(str(self.isVisible()))
module.Window=Window
sys.argv=['lume-sync']
raise SystemExit(module.main())
'''


class SingleInstanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lume-instance-')
        self.root = Path(self.temp.name)
        (self.root/'runtime').mkdir(mode=0o700)
        self.children = []

    def tearDown(self):
        for child in self.children:
            if child.poll() is None:
                child.terminate()
            child.communicate(timeout=5)
        self.temp.cleanup()

    def spawn(self, code=CHILD, *extra):
        child = subprocess.Popen([sys.executable, '-I', '-c', code, str(ROOT), str(self.root), *extra],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.children.append(child)
        return child

    def wait_for(self, predicate):
        deadline = time.monotonic()+6
        while time.monotonic()<deadline:
            if predicate():return
            time.sleep(.01)
        self.fail('O processo não alcançou o estado esperado.')

    def test_second_process_activates_first_without_starting_another(self):
        first = self.spawn()
        self.wait_for(lambda: (self.root/'primary').exists())
        second = self.spawn()
        stdout, stderr = second.communicate(timeout=5)
        self.assertEqual(second.returncode, 0, stderr)
        self.assertIn('FORWARDED', stdout)
        self.assertEqual((self.root/'activations').read_text(), 'show\n')
        self.assertIsNone(first.poll())

    def test_simultaneous_starts_leave_exactly_one_primary(self):
        processes = [self.spawn() for _ in range(3)]
        self.wait_for(lambda: (self.root/'activations').exists() and len((self.root/'activations').read_text().splitlines())==2)
        self.wait_for(lambda: sum(p.poll() is None for p in processes)==1)
        for child in processes:
            if child.poll() is not None:
                stdout,stderr=child.communicate()
                self.assertEqual(child.returncode,0,stderr)
                self.assertIn('FORWARDED',stdout)

    def test_activation_waits_for_first_process_to_finish_starting(self):
        self.spawn(CHILD, '.3')
        self.wait_for(lambda: (self.root/'primary').exists())
        second=self.spawn()
        stdout,stderr=second.communicate(timeout=5)
        self.assertEqual(second.returncode,0,stderr)
        self.assertIn('FORWARDED',stdout)

    def test_crashed_process_does_not_leave_a_permanent_lock(self):
        first=self.spawn()
        self.wait_for(lambda: (self.root/'primary').exists())
        first.kill();first.wait(timeout=5)
        instance=SingleInstance(self.root/'profile',runtime_dir=self.root/'runtime')
        try:self.assertTrue(instance.start())
        finally:instance.close()

    def test_locked_but_unresponsive_instance_does_not_open_a_duplicate(self):
        instance=SingleInstance(self.root/'profile',runtime_dir=self.root/'runtime')
        fd=os.open(instance.lock_path,os.O_CREAT|os.O_RDWR,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError,'já está aberto'):
                instance.start(timeout_ms=100)
            self.assertIsNone(instance.lock_fd)
        finally:os.close(fd)

    def test_directory_symlink_is_refused(self):
        (self.root/'runtime/lumesync').symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(RuntimeError):
            SingleInstance(self.root/'profile',runtime_dir=self.root/'runtime')

    def test_second_gui_launch_restores_hidden_window_and_creates_only_one(self):
        first=self.spawn(GUI)
        self.wait_for(lambda:(self.root/'hidden').exists())
        second=self.spawn(GUI)
        stdout,stderr=second.communicate(timeout=6)
        self.assertEqual(second.returncode,0,stderr)
        self.assertEqual((self.root/'windows').read_text(),'window\n')
        self.assertEqual((self.root/'restored').read_text(),'True')
        self.assertIsNone(first.poll())

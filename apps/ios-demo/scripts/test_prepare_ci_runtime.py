import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('gate',Path(__file__).with_name('prepare-ci-runtime.py'))
gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
class ExactRuntimeTests(unittest.TestCase):
 def runtime(self,version='18.2',available=True,identifier='com.apple.CoreSimulator.SimRuntime.iOS-18-2'):
  return {'version':version,'isAvailable':available,'identifier':identifier,'buildversion':'22C150'}
 def test_selects_exact_available_runtime_among_newer_versions(self):
  correct=self.runtime()
  self.assertEqual(gate.select_runtime({'runtimes':[self.runtime('18.6',True,'com.apple.CoreSimulator.SimRuntime.iOS-18-6'),correct]}),correct)
 def test_rejects_wrong_version_unavailable_wrong_identifier_and_duplicates(self):
  for values in [[self.runtime('18.20')],[self.runtime(available=False)],[self.runtime(identifier='foreign')],[self.runtime(),self.runtime()]]:
   with self.subTest(values=values): self.assertIsNone(gate.select_runtime({'runtimes':values}))

import json
import subprocess
import tempfile
class RuntimeAcquisitionTests(unittest.TestCase):
 def run_gate(self,outputs):
  calls=[]
  def runner(argv,remaining):
   calls.append(argv)
   return subprocess.CompletedProcess(argv,0,outputs.pop(0),'')
  with tempfile.TemporaryDirectory() as directory:
   result=gate.prepare(Path(directory),runner,30)
  return result,calls
 def inventory(self,available=True):
  return json.dumps({'runtimes':[ExactRuntimeTests().runtime(available=available)]})
 def test_wrong_xcode_fails_without_download(self):
  result,calls=self.run_gate(['Xcode 27.1\nBuild version 27A9269\n'])
  self.assertEqual(result['classification'],'INFRA_FAILURE')
  self.assertEqual(calls,[['xcodebuild','-version']])
 def test_exact_runtime_is_acquired_then_verified(self):
  result,calls=self.run_gate(['Xcode 16.2\nBuild version 16C5032a\n',self.inventory(False),'download complete',self.inventory()])
  self.assertEqual(result['classification'],'PASS')
  self.assertIn(['xcodebuild','-downloadPlatform','iOS','-buildVersion','18.2'],calls)
  self.assertEqual(result['runtime']['version'],'18.2')
 def test_download_without_exact_available_runtime_is_infra(self):
  result,calls=self.run_gate(['Xcode 16.2\nBuild version 16C5032a\n',self.inventory(False),'download complete',self.inventory(False)])
  self.assertEqual(result['classification'],'INFRA_FAILURE')

class RuntimeFailureTests(unittest.TestCase):
 def test_timeout_is_infra_and_preserves_partial_command_output(self):
  def runner(argv,remaining):
   raise subprocess.TimeoutExpired(argv,remaining,output='partial output',stderr='partial error')
  with tempfile.TemporaryDirectory() as directory:
   result=gate.prepare(Path(directory),runner,1)
   self.assertEqual(result['classification'],'INFRA_FAILURE')
   self.assertTrue(result['commands'][0]['timedOut'])
   self.assertEqual((Path(directory)/'command-1.stdout.log').read_text(),'partial output')
 def test_nonzero_xcode_is_infra_and_never_downloads(self):
  calls=[]
  def runner(argv,remaining):
   calls.append(argv)
   return subprocess.CompletedProcess(argv,1,'','tool unavailable')
  with tempfile.TemporaryDirectory() as directory:
   result=gate.prepare(Path(directory),runner,1)
  self.assertEqual(result['classification'],'INFRA_FAILURE')
  self.assertEqual(calls,[['xcodebuild','-version']])
 def test_malformed_inventory_is_infra_and_never_selects_default(self):
  outputs=['Xcode 16.2\nBuild version 16C5032a\n','not json']
  calls=[]
  def runner(argv,remaining):
   calls.append(argv)
   return subprocess.CompletedProcess(argv,0,outputs.pop(0),'')
  with tempfile.TemporaryDirectory() as directory:
   result=gate.prepare(Path(directory),runner,1)
  self.assertEqual(result['classification'],'INFRA_FAILURE')
  self.assertNotIn(['xcodebuild','-downloadPlatform','iOS','-buildVersion','18.2'],calls)

class ActualCommandDeadlineTests(unittest.TestCase):
 def test_owned_command_timeout_preserves_output(self):
  import sys
  with self.assertRaises(subprocess.TimeoutExpired) as caught:
   gate.run_command([sys.executable,'-c','import time; print("started",flush=True); time.sleep(60)'],0.25)
  self.assertIn('started',caught.exception.output)

class MalformedInventoryEnvelopeTests(unittest.TestCase):
 def test_valid_json_with_wrong_inventory_shape_does_not_trigger_acquisition(self):
  outputs=['Xcode 16.2\nBuild version 16C5032a\n','[]','download complete',json.dumps({'runtimes':[ExactRuntimeTests().runtime()]})]
  calls=[]
  def runner(argv,remaining):
   calls.append(argv)
   return subprocess.CompletedProcess(argv,0,outputs.pop(0),'')
  with tempfile.TemporaryDirectory() as directory:
   result=gate.prepare(Path(directory),runner,1)
  self.assertEqual(result['classification'],'INFRA_FAILURE')
  self.assertNotIn(['xcodebuild','-downloadPlatform','iOS','-buildVersion','18.2'],calls)
if __name__=='__main__':unittest.main()

import json
import tempfile
import unittest
from pathlib import Path
from verification import managed_api, managed_mutations, managed_tools, managed_verify

ROOT = Path(__file__).resolve().parents[1]
class ManagedEvaluatorTests(unittest.TestCase):
    def test_frozen_anchors_patch_once_and_preserve_branch_body(self):
        matrix = json.loads((ROOT/'verification/managed-mutation-matrix.json').read_text())
        for m in matrix['mutations']:
            source = 'header\n'+m['original']+'\n    rejectForeign()\n}\n'
            patched = managed_mutations.patch(source,m)
            self.assertIn(m['replacement'],patched)
            self.assertIn('rejectForeign()',patched)
            with self.assertRaises(ValueError): managed_mutations.patch(source+source,m)
            with self.assertRaises(ValueError): managed_mutations.patch('no guard',m)
    def test_api_negative_diagnostic_is_specific(self):
        self.assertTrue(managed_api.expected_diagnostic('swift','owner',"error: 'owner' is inaccessible due to 'private' protection level"))
        self.assertTrue(managed_api.expected_diagnostic('kotlin','mutation','error: val cannot be reassigned'))
        self.assertFalse(managed_api.expected_diagnostic('swift','owner','error: no such module AsyncNativeContract'))
        self.assertFalse(managed_api.expected_diagnostic('kotlin','constructor','error: unexpected tokens'))
    def test_swift_conventional_layout_is_detected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); debug=root/'ios/.build/debug'
            modules=debug/'Modules'; modules.mkdir(parents=True)
            objects=[]
            for name in ('NativeContract','AsyncNativeContract'):
                (modules/f'{name}.swiftmodule').write_text('module fixture')
                target=debug/f'{name}.build'; target.mkdir()
                obj=target/f'{name}.swift.o'; obj.write_text('object fixture'); objects.append(obj)
            self.assertEqual(managed_api.swift_artifacts(root),(modules,objects))
    def test_swift_xcode_product_layout_is_detected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); products=root/'ios/.build/out/Products/Debug'; products.mkdir(parents=True)
            (root/'ios/.build/debug').symlink_to(products,target_is_directory=True)
            debug=root/'ios/.build/debug'; objects=[]
            for name in ('NativeContract','AsyncNativeContract'):
                module=products/f'{name}.swiftmodule'; module.mkdir()
                (module/'arm64-apple-macos.swiftmodule').write_text('module fixture')
                (products/f'{name}.o').write_text('object fixture'); objects.append(debug/f'{name}.o')
            self.assertEqual(managed_api.swift_artifacts(root),(debug,objects))
            (products/'NativeContract.o').unlink()
            self.assertIsNone(managed_api.swift_artifacts(root))
    def test_constructor_arity_failure_is_not_access_evidence(self):
        output="constructor.kt: error: no value passed for parameter 'owner'.\nfun forbidden() { RefreshRequest(1L) }"
        self.assertFalse(managed_api.expected_diagnostic('kotlin','constructor',output))
        self.assertTrue(managed_api.expected_diagnostic('kotlin','constructor',"error: cannot access 'constructor(requestId: Long, owner: Any): RefreshRequest': it is private"))
    def test_native_missing_is_not_run(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertIsNone(managed_tools.runner(root,'swift'))
            self.assertIsNone(managed_tools.runner(root,'kotlin'))
    def test_gate_aggregation_never_passes_skips(self):
        for v in ('NOT_RUN','INCONCLUSIVE','INFRA_FAILURE','SEMANTIC_FAIL'):
            self.assertNotEqual(managed_verify.aggregate(['PASS',v]),'PASS')
    def test_exit_one_mutant_build_failure_not_semantic_detection(self):
        self.assertEqual(managed_mutations.classify(1,0,'FAIL'),'INFRA_FAILURE')
        self.assertEqual(managed_mutations.classify(0,1,'FAIL'),'INFRA_FAILURE')
        self.assertEqual(managed_mutations.classify(0,0,'INVALID_HISTORY'),'INFRA_FAILURE')
        self.assertEqual(managed_mutations.classify(0,0,'FAIL'),'PASS')
        self.assertEqual(managed_mutations.classify(0,0,'PASS'),'SEMANTIC_FAIL')
    def test_process_timeout_is_infrastructure(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            result = managed_tools.capture(['python3','-c','import time; time.sleep(10)'],out,'timeout',cwd=out,timeout=0.05)
            self.assertTrue(result['timedOut'])
            self.assertNotEqual(result['exitCode'],0)
            self.assertTrue((out/'timeout.stdout.log').exists())

if __name__ == '__main__': unittest.main()

"""Machine-generated metadata must not become protected program input."""
from pathlib import Path
import tempfile
import unittest

from integration import protocol_config
from verification import change_protocol as protocol


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "d2ce1847cb2644252f7c4d069ef9e36142bb327b"


class GeneratedMetadataMembershipTests(unittest.TestCase):
    def test_nested_finder_and_local_control_metadata_do_not_change_snapshot(self):
        config = protocol_config.build_config(ROOT, "reports/metadata-membership", BASELINE)
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory).resolve()
            for relative in protocol.snapshot(ROOT, config):
                target = candidate / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / relative).read_bytes())
            before = protocol.snapshot(candidate, config)
            for relative in (
                "apps/ios-demo/.DS_Store", "integration/.DS_Store",
                "verification/.DS_Store", "docs/experiments/control-location.json",
                "android/.kotlin/errors/errors-2026-10-13.log",
                "apps/android-demo/.kotlin/errors/errors-2026-10-13.log",
                "apps/ios-demo/NativeContractDemo.xcodeproj/xcuserdata/runner.xcuserdatad/xcschemes/xcschememanagement.plist",
                "apps/ios-demo/NativeContractDemo.xcodeproj/project.xcworkspace/xcuserdata/runner.xcuserdatad/UserInterfaceState.xcuserstate",
                "apps/ios-demo/NativeContractDemo.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved",
            ):
                target = candidate / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"generated metadata\n")
            after = protocol.snapshot(candidate, config)
            self.assertEqual(after, before)
            self.assertIn("integration/check.py", after)
            self.assertIn("verification/change_protocol.py", after)

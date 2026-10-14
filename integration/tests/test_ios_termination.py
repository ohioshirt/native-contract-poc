"""Termination classification with the OS command boundary substituted."""
import subprocess
import unittest

from integration.controller import _ios_terminate_app


class IosTerminationTests(unittest.TestCase):
    def run_termination(self, terminate, listing):
        commands = []
        def runner(argv, **kwargs):
            commands.append(argv)
            code, stdout, stderr = terminate if argv[2] == "terminate" else listing
            return subprocess.CompletedProcess(argv, code, stdout, stderr)
        events = []
        result = _ios_terminate_app("owned-device", "attempt/APP-12/p1", 1, events, command_runner=runner)
        return result, events, commands

    def test_already_terminated_requires_independent_absence(self):
        result, events, commands = self.run_termination(
            (3, "", "An error was encountered processing the command (domain=NSPOSIXErrorDomain, code=3):\nfound nothing to terminate"),
            (0, "PID\tStatus\tLabel\n-\t0\tcom.apple.other\n", ""),
        )
        self.assertEqual([e["kind"] for e in events], ["forceStopped", "terminated"])
        self.assertTrue(events[0]["pidAbsent"])
        self.assertEqual(commands[-1], ["xcrun", "simctl", "spawn", "owned-device", "launchctl", "list"])
        self.assertEqual(len(result), 2)

    def test_successful_terminate_with_surviving_process_is_rejected(self):
        with self.assertRaises(OSError):
            self.run_termination((0, "", ""), (0, "PID\tStatus\tLabel\n123\t0\tUIKitApplication:dev.nativecontract.demo.ios[abc]\n", ""))

    def test_unknown_command_error_does_not_claim_termination(self):
        with self.assertRaises(OSError):
            self.run_termination((1, "", "Invalid device"), (0, "PID\tStatus\tLabel\n", ""))

    def test_failed_or_malformed_absence_probe_is_rejected(self):
        for listing in ((1, "", "spawn failed"), (0, "", ""), (0, "unexpected output", "")):
            with self.subTest(listing=listing), self.assertRaises(OSError):
                self.run_termination((0, "", ""), listing)

    def test_dormant_launch_service_is_not_a_running_process(self):
        _, events, _ = self.run_termination((0, "", ""), (0, "PID\tStatus\tLabel\n-\t0\tUIKitApplication:dev.nativecontract.demo.ios[abc]\n", ""))
        self.assertTrue(events[0]["pidAbsent"])

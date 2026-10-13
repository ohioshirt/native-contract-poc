#!/usr/bin/env python3
"""Create or remove only the native device resources owned by this CI attempt."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from integration.ci_devices import CiDeviceBootstrap, DeviceBootstrapError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="create one unique owned platform device")
    prepare.add_argument("--platform", choices=("ios", "android"), required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--run-id", required=True)
    prepare.add_argument("--timeout-seconds", type=float, default=900)
    prepare.add_argument("--android-port", type=int, default=5580)
    prepare.add_argument("--github-env", type=Path)
    cleanup = commands.add_parser("cleanup", help="remove only resources listed in ownership.json")
    cleanup.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "prepare":
        manager = CiDeviceBootstrap(
            output=args.output,
            run_id=args.run_id,
            platform=args.platform,
            timeout_seconds=args.timeout_seconds,
            android_port=args.android_port,
        )
        try:
            result = manager.prepare(github_env=args.github_env)
        except (DeviceBootstrapError, OSError, ValueError, json.JSONDecodeError) as exc:
            print(json.dumps({"classification": "INFRA_FAILURE", "detail": str(exc)}, sort_keys=True), file=sys.stderr)
            return 2
    else:
        output = args.output.absolute()
        ownership_path = output / "ownership.json"
        try:
            ownership = json.loads(ownership_path.read_text(encoding="utf-8"))
            resources = ownership.get("resources")
            if not isinstance(resources, dict):
                raise DeviceBootstrapError("owned-device manifest has no resources map")
            resource_platform = "ios" if "ios" in resources else "android" if "android" in resources else None
            if resource_platform is None:
                result = {"classification": "PASS", "detail": "no owned device was created"}
                print(json.dumps(result, sort_keys=True))
                return 0
            manager = CiDeviceBootstrap(
                output=output,
                run_id=ownership.get("runId"),
                platform=resource_platform,
                host_platform=sys.platform,
            )
            result = manager.cleanup()
        except (DeviceBootstrapError, OSError, ValueError, json.JSONDecodeError) as exc:
            result = {"classification": "INFRA_FAILURE", "detail": str(exc)}
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("classification") == "READY" or result.get("classification") == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())

"""Generate complete semantic-failure histories for the evaluator only.

The adapter calls the repository's managed reducer for each event. It then
deliberately applies the old response payload after the managed reducer has
returned a stale no-op. These files are evaluator fixtures, never native-app
observations.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from verification.async_contract import step as managed_step


ROOT = Path(__file__).resolve().parents[2]
OWNER_ID = "owner-1"
REQUEST_TAG_SUFFIX = ":refresh:3"


def _snapshot(owner_id, state, pending, next_id):
    return {
        "ownerId": owner_id,
        "state": state,
        "pendingRequestId": pending,
        "nextRequestId": next_id,
    }


def _store(kind, account=None, version=None):
    if kind == "Absent":
        return {"kind": "Absent"}
    return {"kind": "Present", "account": account, "version": version}


def _view(phase, account, version, pending, command_id, status):
    return {
        "phase": phase,
        "account": account,
        "credentialVersion": version,
        "pendingRequestId": pending,
        "lastCompletedCommandId": command_id,
        "lastCommandStatus": status,
    }


def _event_ref(process_id, sequence):
    return {"processInstanceId": process_id, "localSequence": sequence}


def _command_ref(process_id, ident):
    return {"processInstanceId": process_id, "id": ident}


class _History:
    def __init__(self, scenario_id, run_id):
        self.scenario_id = scenario_id
        self.run_id = run_id
        self.process_id = f"unsafe-evaluator/{scenario_id}/p1"
        self.events = []
        self.inventory = []
        self.sequence = 0
        self.revision = 0
        self.store = _store("Absent")
        self.managed = _snapshot(OWNER_ID, "Unauthenticated", None, 1)
        self.spec = json.loads((ROOT / "contract" / "specification.json").read_text())

        self.add("processStart", initialView=_view("Booting", None, None, None, None, None))

    def add(self, kind, **fields):
        self.sequence += 1
        event = {
            "processInstanceId": self.process_id,
            "launchOrdinal": 1,
            "localSequence": self.sequence,
            "kind": kind,
            **fields,
        }
        self.events.append(event)
        return event

    def acknowledge(self, command_ref, view):
        self.revision += 1
        return self.add("uiPublishAck", commandRef=command_ref, revision=self.revision, view=view)

    def command(
        self,
        ident,
        name,
        *,
        phase,
        account=None,
        version=None,
        status="Completed",
        managed_event=None,
        managed_epoch_id="epoch-1",
        slot_issue=None,
        delivery=None,
        mutation=None,
        signing_out=False,
    ):
        command_ref = _command_ref(self.process_id, ident)
        if name == "Bootstrap" and mutation is None:
            mutation = {
                "operation": "clear",
                "cause": "Bootstrap",
                "before": _store("Absent"),
                "after": _store("Absent"),
            }
        self.inventory.append({"commandRef": command_ref, "name": name})
        self.add("commandEnqueued", commandRef=command_ref, name=name)
        self.add("commandStarted", commandRef=command_ref)

        if signing_out:
            interim = _view("SigningOut", None, None, self.managed["pendingRequestId"], ident - 1, "Completed")
            self.acknowledge(command_ref, interim)

        if delivery is not None:
            self.add(
                "transportReceived",
                commandRef=command_ref,
                slotId=delivery["slotId"],
                outcome=delivery["outcome"],
                failureCode=delivery.get("failureCode"),
                requestTag=delivery["requestTag"],
            )

        if managed_event is not None:
            pre = dict(self.managed)
            reduced = managed_step(
                self.spec,
                pre["state"],
                pre["pendingRequestId"],
                pre["nextRequestId"],
                managed_event,
            )
            result = {"ownerId": pre["ownerId"], **reduced}
            fields = {
                "commandRef": command_ref,
                "event": managed_event,
                "pre": pre,
                "result": result,
                "epochId": managed_epoch_id,
            }
            if delivery is not None:
                fields.update(slotId=delivery["slotId"], requestOwnerId=delivery["ownerId"])
            self.add("managedReduced", **fields)
            self.managed = _snapshot(
                result["ownerId"],
                result["state"],
                result["pendingRequestId"],
                result["nextRequestId"],
            )

        if slot_issue is not None:
            self.add("slotIssued", commandRef=command_ref, **slot_issue)

        if mutation is not None:
            before, after = mutation["before"], mutation["after"]
            self.add(
                "storeMutation",
                commandRef=command_ref,
                operation=mutation["operation"],
                cause=mutation["cause"],
                before=before,
                after=after,
                **{key: mutation[key] for key in ("slotId", "epochId", "ownerId") if key in mutation},
            )
            self.add("storeReadback", commandRef=command_ref, operation=mutation["operation"], observation=after)
            self.store = after

        view = _view(phase, account, version, self.managed["pendingRequestId"], ident, status)
        acknowledgement = self.acknowledge(command_ref, view)
        receipt = self.add(
            "commandReceipt",
            commandRef=command_ref,
            status=status,
            observation={
                "managed": dict(self.managed),
                "store": dict(self.store),
                "view": view,
                "revision": self.revision,
            },
            acknowledgedEventRef=_event_ref(self.process_id, acknowledgement["localSequence"]),
        )
        if delivery is not None:
            self.add(
                "completionProcessed",
                commandRef=command_ref,
                slotId=delivery["slotId"],
                receiptEventRef=_event_ref(self.process_id, receipt["localSequence"]),
            )
        return {"commandRef": command_ref, "ack": acknowledgement, "receipt": receipt}

    def finish(self):
        return self.add("processEnd")

    def trace(self):
        return {
            "version": 1,
            "runId": self.run_id,
            "scenarioId": self.scenario_id,
            "platform": "ios",
            "buildHash": "sha256:" + "a" * 64,
            "processInstances": [{"processInstanceId": self.process_id, "launchOrdinal": 1}],
            "controllerEvents": [],
            "commandInventory": self.inventory,
            "events": self.events,
            "artifactPaths": [f"{self.scenario_id}/p1/native.jsonl", f"{self.scenario_id}/p1/ui.jsonl"],
        }


def _fixture(scenario_id):
    run_id = f"unsafe-{scenario_id.lower()}"
    history = _History(scenario_id, run_id)
    process_id = history.process_id
    request_tag = process_id + REQUEST_TAG_SUFFIX
    ui_observations = []
    controller = []
    server = []

    def control(kind, **fields):
        row = {"sequence": len(controller) + 1, "kind": kind, "processInstanceId": process_id, **fields}
        controller.append(row)
        return row

    control("launch", launchOrdinal=1)
    control("requestHeld", requestTag=request_tag)
    server.append({"runId": run_id, "sequence": 1, "kind": "requestHeld", "requestTag": request_tag, "requestId": "1"})

    history.command(1, "Bootstrap", phase="SignedOut")
    history.command(
        2,
        "Login(A)",
        phase="SignedIn",
        account="A",
        version=0,
        managed_event={"event": "LoginSucceeded"},
        mutation={"operation": "replace", "cause": "Login", "epochId": "epoch-1", "before": _store("Absent"), "after": _store("Present", "A", 0)},
    )
    history.command(
        3,
        "Expire",
        phase="Refreshing",
        account="A",
        version=0,
        managed_event={"event": "TokenExpired"},
        slot_issue={
            "slotId": "slot-A1",
            "ownerId": OWNER_ID,
            "epochId": "epoch-1",
            "requestId": 1,
            "wireRequestId": "1",
            "account": "A",
            "seedVersion": 0,
            "wireTag": process_id + REQUEST_TAG_SUFFIX,
        },
    )
    logout = history.command(
        4,
        "Logout",
        phase="SignedOut",
        managed_event={"event": "Logout"},
        mutation={"operation": "clear", "cause": "Logout", "epochId": "epoch-1", "before": _store("Present", "A", 0), "after": _store("Absent")},
        signing_out=True,
    )
    controller.append({
        "sequence": len(controller) + 1,
        "kind": "receiptObserved",
        "processInstanceId": process_id,
        "commandRef": logout["commandRef"],
        "eventRef": _event_ref(process_id, logout["receipt"]["localSequence"]),
    })

    if scenario_id == "APP-02":
        logout_probe_step = "APP-02-after-logout-store"
        logout_view_step = "APP-02-after-logout-view"
        logout_probe = control("probeCaptured", stepId=logout_probe_step)
        ui_observations.extend([
            {"kind": "storageProbe", "stepId": logout_probe_step, "processInstanceId": process_id, "commandRef": logout["commandRef"], "controllerSequence": logout_probe["sequence"], "observation": _store("Absent")},
            {"kind": "renderedView", "stepId": logout_view_step, "processInstanceId": process_id, "revision": logout["ack"]["revision"], "eventRef": _event_ref(process_id, logout["ack"]["localSequence"]), "phase": "SignedOut", "account": None},
        ])
        release_command = "Logout"
        login_b = None
    else:
        logout_probe_step = "APP-04-after-logout-store"
        logout_view_step = "APP-04-after-logout-view"
        logout_probe = control("probeCaptured", stepId=logout_probe_step)
        ui_observations.extend([
            {"kind": "storageProbe", "stepId": logout_probe_step, "processInstanceId": process_id, "commandRef": logout["commandRef"], "controllerSequence": logout_probe["sequence"], "observation": _store("Absent")},
            {"kind": "renderedView", "stepId": logout_view_step, "processInstanceId": process_id, "revision": logout["ack"]["revision"], "eventRef": _event_ref(process_id, logout["ack"]["localSequence"]), "phase": "SignedOut", "account": None},
        ])
        login_b = history.command(
            5,
            "Login(B)",
            phase="SignedIn",
            account="B",
            version=0,
            managed_event={"event": "LoginSucceeded"},
            managed_epoch_id="epoch-2",
            mutation={"operation": "replace", "cause": "Login", "epochId": "epoch-2", "before": _store("Absent"), "after": _store("Present", "B", 0)},
        )
        control(
            "receiptObserved",
            commandRef=login_b["commandRef"],
            eventRef=_event_ref(process_id, login_b["receipt"]["localSequence"]),
        )
        login_probe = control("probeCaptured", stepId="APP-04-after-login-b-store")
        ui_observations.extend([
            {"kind": "storageProbe", "stepId": "APP-04-after-login-b-store", "processInstanceId": process_id, "commandRef": login_b["commandRef"], "controllerSequence": login_probe["sequence"], "observation": _store("Present", "B", 0)},
            {"kind": "renderedView", "stepId": "APP-04-after-login-b-view", "processInstanceId": process_id, "revision": login_b["ack"]["revision"], "eventRef": _event_ref(process_id, login_b["ack"]["localSequence"]), "phase": "SignedIn", "account": "B"},
        ])
        release_command = "Login(B)"

    control("releaseRequested", requestTag=request_tag)
    server.append({"runId": run_id, "sequence": 2, "kind": "releaseAccepted", "requestTag": request_tag, "outcome": "success"})
    control("releaseAccepted", requestTag=request_tag)
    server.append({"runId": run_id, "sequence": 3, "kind": "responseWritten", "requestTag": request_tag, "outcome": "success"})
    control("responseWritten", requestTag=request_tag)

    before = _store("Absent") if scenario_id == "APP-02" else _store("Present", "B", 0)
    final_store = _store("Present", "A", 1)
    delivery = {"slotId": "slot-A1", "outcome": "success", "requestTag": request_tag, "ownerId": OWNER_ID}
    stale = history.command(
        5 if scenario_id == "APP-02" else 6,
        "Deliver(slot-A1,success)",
        phase="SignedIn",
        account="A",
        version=1,
        status="IgnoredStale",
        managed_event={"event": "RefreshSucceeded", "requestId": 1},
        managed_epoch_id="epoch-1",
        delivery=delivery,
        mutation={"operation": "replace", "cause": "RefreshSuccess", "slotId": "slot-A1", "epochId": "epoch-1", "ownerId": OWNER_ID, "before": before, "after": final_store},
    )
    completion_event = next(event for event in reversed(history.events) if event["kind"] == "completionProcessed")
    control(
        "completionProcessedObserved",
        commandRef=stale["commandRef"],
        eventRef=_event_ref(process_id, completion_event["localSequence"]),
    )
    final_probe_step = f"{scenario_id}-final-probe"
    final_probe = control("probeCaptured", stepId=final_probe_step)
    final_view_step = f"{scenario_id}-final-view"
    ui_observations.extend([
        {"kind": "storageProbe", "stepId": final_probe_step, "processInstanceId": process_id, "commandRef": stale["commandRef"], "controllerSequence": final_probe["sequence"], "observation": final_store},
        {"kind": "renderedView", "stepId": final_view_step, "processInstanceId": process_id, "revision": stale["ack"]["revision"], "eventRef": _event_ref(process_id, stale["ack"]["localSequence"]), "phase": "SignedIn", "account": "A"},
    ])
    process_end = history.finish()
    control(
        "processEndAcknowledged",
        eventRef=_event_ref(process_id, process_end["localSequence"]),
    )
    control("terminated", launchOrdinal=1)
    trace = history.trace()
    trace["controllerEvents"] = controller
    return trace, server, ui_observations


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def generate(output: Path | str):
    """Write complete APP-02 and APP-04 evaluator-only histories."""
    output = Path(output)
    manifest = {
        "evidenceKind": "evaluator-fixture",
        "fixtureId": "unsafe-unconditional-commit",
        "scenarios": [
            {"scenarioId": "APP-02", "expectedClassification": "SEMANTIC_FAIL", "requiredInvariants": ["I2", "I3"]},
            {"scenarioId": "APP-04", "expectedClassification": "SEMANTIC_FAIL", "requiredInvariants": ["I2", "I4"]},
        ],
    }
    _write_json(output / "fixture.json", manifest)
    for scenario_id, expected in (("APP-02", {"I2", "I3"}), ("APP-04", {"I2", "I4"})):
        scenario_dir = output / scenario_id
        trace, server, observations = _fixture(scenario_id)
        _write_json(scenario_dir / "trace.json", trace)
        _write_json(scenario_dir / "server-events.json", server)
        _write_json(scenario_dir / "ui-observations.json", observations)
        _write_json(scenario_dir / "fixture.json", {"evidenceKind": "evaluator-fixture", "scenarioId": scenario_id, "requiredInvariants": sorted(expected)})
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    output = Path(args.output)
    try:
        generate(output)
        from integration.check import check_trace

        contract = json.loads((ROOT / "integration" / "contract.json").read_text())
        scenarios = {row["id"]: row for row in json.loads((ROOT / "integration" / "scenarios.json").read_text())["scenarios"]}
        summary = {"evidenceKind": "evaluator-fixture", "scenarios": []}
        for scenario_id, expected in (("APP-02", {"I2", "I3"}), ("APP-04", {"I2", "I4"})):
            directory = output / scenario_id
            trace = json.loads((directory / "trace.json").read_text())
            server = json.loads((directory / "server-events.json").read_text())
            observations = json.loads((directory / "ui-observations.json").read_text())
            report = check_trace(contract, scenarios[scenario_id], trace, server, observations)
            _write_json(directory / "report.json", report)
            actual = {row["invariant"] for row in report["violations"]}
            passed = report["classification"] == "SEMANTIC_FAIL" and expected <= actual
            summary["scenarios"].append({
                "scenarioId": scenario_id,
                "expectedClassification": "SEMANTIC_FAIL",
                "actualClassification": report["classification"],
                "requiredInvariants": sorted(expected),
                "observedInvariants": sorted(actual),
                "fixtureVerdict": "PASS" if passed else "FAIL",
            })
        _write_json(output / "summary.json", summary)
        print(json.dumps(summary, sort_keys=True))
        return 0 if all(row["fixtureVerdict"] == "PASS" for row in summary["scenarios"]) else 1
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"fixtureVerdict": "INFRA_FAILURE", "detail": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

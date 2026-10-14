# Standalone app evaluator — authenticated Fable review

Review run: tools-disabled Claude CLI, escalated only to access the already-authenticated Keychain/network session after the user completed `/login`. The command exited 0 with `is_error=false`, `stop_reason=end_turn`, and no permission denials. API duration was 988.899 seconds. The actual canonical model was `claude-fable-5-1`; usage and cost are preserved in `reports/standalone/task1/claude-review-refresh-metadata.json`.

The review packet SHA-256 is `84feea10fb2289ccf2320610d796d679411d088d82278b8c18cd5e59d9a19cdb`. Its exact input hashes, the raw outer response, parsed reviewer JSON and CLI logs are saved under `reports/standalone/task1/claude-review-refresh-*`.

**Disposition: FAIL / NOT READY.** The JSON result lists 15 findings: 2 Critical, 7 Important and 6 Minor. This review does not approve a freeze or unimplemented native apps.

The findings are:

1. **Critical — variants and controls cannot be checked.** APP-09/10/11/13 lack a selected command inventory path; control rows lack platform/launch evidence. Hook arrival/release, APP-11 FIFO barriers and detached effects are not represented or checked.
2. **Critical in the reviewed packet, stale against current source — observation violation provenance.** The packet's checker SHA is `85ba96651d5152db6238b36bf239f23a1d7f0e720ba13fc9ae16632df04c9292`; current `integration/check.py` has a newer SHA after the zero-reference correction. Verify the live checker output through integration-report binding before marking this fixed.
3. **Important — protocol aggregation does not validate model and per-control witnesses.** A stage needs per-control result/witness requirements and a checked model report.
4. **Important — event-array order affects semantic traversal.** Require serialized sequence order or process records after a stable sequence sort; preserve real I1 counterexamples as semantic failures.
5. **Important — several required probes/views have no expected values.** Freeze explicit expectation coverage for each observation.
6. **Important — APP-03/04/05 barrier inventories are incomplete.** Require release, receipt, probe and Login B ordering evidence where declared.
7. **Important — Bootstrap I9 checks can pass when the probe or clear is absent.** Require and order bootstrap clear plus verified readback for every process launch.
8. **Important — foreign delivery evidence is under-specified.** Require `slotId` and `requestOwnerId` on delivery reductions and compare them to the issued slot; add APP-10-RECOVER-OLD fixtures for a genuine old-owner no-op and owner-ignored mutation.
9. **Important — control inventory witnesses disagree with checker behavior.** Correct N1-LOGOUT witness set and identify N2 late clear by effect ID and origin Logout command independently of a refresh slot.
10. **Minor in the review, regraded Important for APP-08/13 — error detail is not represented consistently.** Validate failure code and expected transport outcomes in schema, inventory and checker.
11. **Minor — mismatch invariant labels are inferred from step-name text.** Freeze the invariant with each expectation or record a justified alternative in the ledger.
12. **Minor — finite-model boundary/mutant report concerns.** Verify terminal behavior at revision/epoch exhaustion, report unexpected mutant violations, and align the unconditional mutant with its declared definition or narrow the abstraction explicitly.
13. **Minor in the review, regraded Important for I6 — UI publication does not prove the command is still active.** Add a same-command/open-command acknowledgement regression so an old command cannot publish after its receipt.
14. **Minor — audit inventory and transport links need stricter reconciliation.** Use frozen issuance wire tags, record artifact/slot conventions and keep the response inventory exact.
15. **Minor — protocol classification and invocation metadata have edge gaps.** Review INVALID_HISTORY classification and the stage entry point/Python executable provenance.

The full, unmodified reviewer JSON is the source of record for the concrete schedules, consequences and requested changes. Findings are being reproduced against current hashes before fixes are accepted. The full implementation gate remains closed until the current variant/control findings and other freeze-blocking items are fixed, hand-authored regressions pass, and a focused independent re-review gives a usable passing disposition.

# Finite TLA+ model and its verification boundary

`contract/specification.json` is the behavior authority. `Session.tla` is a generic observer of its generated `ContractData.tla`; neither file is used to generate Swift or Kotlin implementation code. `toolchain.json` pins the official TLC distribution and records the SHA-256 trust origin.

## State and behavior

Let S be the declared session states, E the known events, and F the effect alphabet. The validated total deterministic function is δ:S×E→S×F*. Its effect lists are ordered. Each processed model step selects e∈E and applies δ to the current state.

The TLC state is the tuple `(state, previousState, event, effects)`, not just the session state. For each declared row `(s,e)↦(s',fx)`, the observed tuple is `(s',s,e,fx)`. Distinct rows give distinct observations because `(s,e)` is retained. A separate initial observation uses `__initial__`, which is forbidden in E. The dump bridge checks exact equality with this observation set, and the existing validator checks reachability and total/deterministic domain coverage. Reported TLC search depth is the depth at which exploration reached its fixed point, not a configured event-length limit.

`Spec = Init /\ [][Next]_vars` allows TLA+ stuttering. A stutter represents no new processed event; it does not execute the last effect again. Effect fields describe the last transition observation, not credential side effects or an execution history.

## What the checker establishes

The pinned TLC process must finish breadth-first exploration with no queued states, exit zero, and a parseable dump. It checks state/previous-state/event/effect closure, the declared effect bound, transition observation soundness, and default deadlock checking. The dump's observations must exactly match the direct JSON projection. The isolated negative model must produce a validated named-invariant counterexample; syntax or execution failures do not qualify.

This is finite model checking, not a TLAPS deductive proof. Projection equality alone does not prove every graph edge or implementation refinement. Causal predecessor assignment in the handwritten `Next` relation is a reviewed assumption. JSON generation, parser/checker implementation, the JVM and TLC remain part of the trusted toolchain. The source and JAR hashes identify the executed inputs; they do not certify tool correctness or publisher signatures.

## What remains unverified

Native behavior is checked using its independent contract/differential/mutation gates over the defined finite input set. No theorem about arbitrary Swift/Kotlin programs follows from the TLA+ run. No fairness has been specified, so refresh completion/liveness is not claimed. Concurrent API calls, credentials, persistence and OS integration are not represented in this model.

## Async correlation abstraction

`AsyncSession.tla` is checked separately from the synchronous `Session.tla` gate by `scripts/async-formal-verify.sh`. Its transition records are generated from the validated v3 `async.transitions` rows. It tracks the session state, a Boolean pending-request flag and predecessor observations. A response may be labelled CURRENT only while a request is pending; under the same-instance routing assumption, CURRENT means the response ID equals that pending ID. STALE represents all other IDs, including duplicate, old, future and foreign-session responses. The model abstracts away numeric IDs, signed64 allocation and native implementation refinement. Allocation may nondeterministically take an atomic exhaustion branch. It checks pending iff Refreshing, row/effect closure, stale no-op safety and rejection atomicity; it makes no liveness claim. The isolated mutant removes the stale response guard and must produce a parsed `StaleResponseSafety` counterexample. See [async verification evidence](../docs/agent-reports/async-verification.md).

## Commands

```sh
bash scripts/formal-verify.sh "$PWD/reports/formal-manual"
bash scripts/verify.sh "$PWD/reports/full"
```

The standalone output directory must be empty or marked as owned by the runner. Full verification creates a fresh formal run directory and records its exact path in the gate command log. Never interpret an unrelated or older report as the result of the current run. Tool cache files stay outside evidence.

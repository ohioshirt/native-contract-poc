# Claude Fable review before main integration

Requested model: Fable. Resolved model for each scoped review: claude-fable-5-1.

Review input was a byte-verified source copy under the permitted original checkout, candidate digest 635754a4683503f28d4c83112056ae8eb9a2bd85fb78fede5c30cdccd314c157. Original worktree read permission was unavailable to the first tool agent; that attempt performed no review. A broad tool call timed out. The scoped reviews below completed successfully. Reviewers performed static inspection, not new gate execution.

Overall disposition before fix: native and semantics approved; protocol P2 requires correction before merge. PR/hosted CI was not deemed a mandatory gate for this isolated local PoC.

## native

Agent: adf3172b599be024c; model: claude-fable-5-1

**Scope reviewed**: `/Users/shigeo/work/mobile/native-contract-poc/reports/fable-review-candidate/native-bundle.md` (Swift/Kotlin `ManagedAsyncSession`, `AsyncSession`, history runners), plus one targeted read of `candidate/ios/Sources/NativeContract/AuthReducer.swift` to confirm the Swift fallthrough paths.

**Verdict: APPROVED** within the native scope. No findings at confidence >= 80.

What I verified against the required semantics:

- Refreshing + Logout: both `AsyncSession.swift:81-85` and `AsyncSession.kt:88-93` set Unauthenticated, clear pending, emit exactly `ClearCredentials`, and leave `nextRequestId` untouched (including `nil`/exhausted).
- Stale refresh replies: `AsyncSession.swift:58` and `AsyncSession.kt:54` return no-op with no effects and no rejection.
- Swift general-case fallthrough (`AsyncSession.swift:86-97`) cannot reach `mapEffect`'s `preconditionFailure`: `AuthReducer` only emits `requestTokenRefresh` for `(.authenticated, .tokenExpired)`, which is intercepted at line 71. Refreshing + loginSucceeded/tokenExpired and Unauthenticated + tokenExpired are no-ops in both languages, so the two low-level machines agree.
- Managed layer: wrong-owner rejection precedes any numeric handling (`ManagedAsyncSession.swift:66`, `.kt:57`); owner is a private retained reference, tokens are only producible by the session; Swift `handle`/`snapshot` are synchronous actor methods (no `await` inside, so the snapshot is atomic with the reduction); Kotlin uses one monitor for `handle` and `snapshot`.
- Runners: token publication happens after the return stamp in both (`HistoryProcessor.swift:297/308`, `ManagedHistoryRunner.kt:147/150-152`); dependency waits plus acyclicity validation rule out barrier deadlock; failure propagation resumes/throws all waiters so no hang. JSON shape (explicit `null` for snapshot IDs, omitted `tokenRef`/`token`/`event` when absent) is consistent across the two runners.

One cross-scope note for the checker reviewer (not a native finding, confidence below the reporting bar): both runners silently return the last of 20 trials when a declared `concurrentPhases` entry never produced overlapping stamps (`HistoryProcessor.swift:191-196`, `ManagedHistoryRunner.kt:38-42`). Validation also permits two same-phase operations with a dependency between them, which can never overlap. If the common checker does not independently require observed overlap per concurrent phase, the concurrency property is vacuously satisfied. Worth confirming on the checker side.

**PR / hosted CI**: not strictly required for this isolated PoC. Direct Fable review plus a fresh full local gate is sufficient, provided the report claims only local evidence (which the bundle's semantics already state). I did not run any tests; this is source review only.

## semantics

Agent: a503b959bf3ff75e7; model: claude-fable-5-1

**Scope reviewed:** `reports/fable-review-candidate/semantics-bundle.md` only (full source of `verification/linearizability.py`, `numeric_model.py`, `async_contract.py`, `contract.py`, `formal/AsyncSession.tla`). I did not run anything; no test or gate results are claimed here.

**Verdict: APPROVED (semantics scope).** No critical or important findings. The required semantics are implemented and cross-checked consistently:

- Refreshing+Logout invalidate policy: `contract.py:129-132` forces exact `Unauthenticated / [ClearCredentials] / clear`; `async_contract.py:127-135` and `AsyncSession.tla:91-102` re-check it independently; allocator preservation incl. exhausted (`nextRequestId` None) at `async_contract.py:128-129`, `numeric_model.py:66`.
- Stale responses: `step` guard `async_contract.py:103` plus `policy_errors:138-140`, `numeric_model.py:71-72`, `AsyncSession.tla:80-85`.
- Owner check precedes numeric handling: `linearizability.py:149-150`, `numeric_model.py:27-29` and `:54-55`; provenance binds token to issuing owner (`linearizability.py:119`, `:137`).
- Real-time precedence: globally distinct integer stamps (`:105-107`), `predecessors` from `return < invoke` (`:141`), producer-return-before-consumer-invoke (`:133`), lower-phase ordering (`:129`). Memo key in `search` (`:170`) is sound because successor state is fully determined by `done` + per-owner triples.
- Bool/int confusion is closed everywhere equality is used (`integer()` uses `type is int`; `:89`, `:103`, `:135`).

**P3 notes (non-blocking):**

1. `linearizability.check_document` and `numeric_model.explore` consume `spec` without calling `validate`/`validate_async`. A non-total table makes `next()` at `async_contract.py:102` / `numeric_model.py:30` raise uncaught `StopIteration` (traceback, exit 1). Fail-closed, not a false PASS; only matters if the gate does not validate the spec earlier (not visible in this bundle).
2. `numeric_model.actions` (`:81-87`) only feeds issued IDs as response tokens; never-issued IDs within 1..3 are not exercised in the two-owner product. Covered single-owner by `future-unissued-id` (`async_contract.py:83`). Coverage gap, not a bug.
3. `validate_workload` failures surface as `INVALID_HISTORY` (`linearizability.py:209-210`); label is misleading, exit code identical.
4. `_wire_shape_errors:193` accepts string-form events while `validate_output:225` requires object-form equality. Inconsistent but fail-closed.

**PR / hosted CI:** Not strictly required for this isolated PoC given its stated scope (local source and evidence only, no hosted-CI claim). Direct Fable review plus a fresh full local gate is sufficient, provided the gate treats `linearizability` exit codes 2 and 3 (INFRA_FAILURE / INCONCLUSIVE) as failures. I could not confirm that mapping from this bundle; please verify it in the gate script before merge.

## protocol

Agent: add991e573a6736bc; model: claude-fable-5-1

**Scope reviewed:** `verification/change_protocol.py`, `managed_api.py`, `managed_mutations.py`, `managed_verify.py`, `managed_tools.py`, `scripts/verify.sh` (from the bundle) plus `candidate/scripts/change-protocol.sh` (thin `exec` passthrough, so CLI semantics are exposed unchanged). Source review only; I ran nothing.

**Verdict: APPROVED within scope**, with one Important finding to fix before `check --result` is used as a merge gate.

### Important (P2)

**`check --result` reports `classification: PASS` / exit 0 for a result whose own verdict is `SEMANTIC_FAIL` or `INFRA_FAILURE`.**
`/Users/shigeo/work/mobile/native-contract-poc/verification/change_protocol.py:270-272` recomputes `classify(...)`, requires it to equal `result['classification']`, then unconditionally returns `{'classification':'PASS', ...}`; `main` (line 445) maps that to exit 0. The stage verdict is never surfaced. Repro: an attempt whose comparator exited 1 with `swift: FAIL` produces `result.json` with `classification: SEMANTIC_FAIL`; `change-protocol.sh check --result <that>` prints `PASS` and exits 0. Any controller or human treating that exit code as "evidence passed" has a false-positive path. Fix: include `resultClassification: result['classification']` in the returned dict and/or make the exit code follow the result's verdict (0 only when both binding and verdict are PASS).

### Nits (P3, no action required)

- `change_protocol.py:333-339`: full-gate `Overall: FAIL` is always `INFRA_FAILURE`, never `SEMANTIC_FAIL`. Conservative, not a false positive, but the exit-code 1 branch of `main` is unreachable for full-gate stages.
- `change_protocol.py:211,263`: `Path(...).absolute()` vs `root.resolve()` — a symlinked cwd (macOS `/tmp`) yields "manifest must be under candidate evidence". Fails closed.
- `managed_api.py:16,19`: `probe in text` is trivially satisfied because the fixture filename (`owner.swift` etc.) appears in compiler diagnostics; the oracle reduces to the access-control phrase. The mandatory positive compile/run (lines 62-67) prevents a renamed API from laundering a PASS, so acceptable.
- `managed_api.py:55`: `compiler_cp` globs every jar in the Gradle cache; multiple cached Kotlin compiler versions would make class selection order-dependent. Worst case is `INFRA_FAILURE`.

### Verified fail-closed paths (no issues found)

Manifest digest + re-validation (`read_manifest`), snapshot symlink refusal and protected-descendant walk (`snapshot`), pre/post `check_sources` equality in `run`, `command.json` argv/cwd binding, artifact mtime ≥ `startedNs`, `__pycache__`-only protected-overlap exception, budget ledger under `flock`, `managed_verify` never PASS on absent native evidence, `verify.sh` `overall=1` on any nonzero gate.

### PR / hosted CI

Not strictly required for this isolated PoC. The protocol binds source snapshot, command, raw logs, artifacts and recomputed verdict locally, and the stated threat model excludes a malicious controller. Direct Fable review plus a fresh full local gate executed through `change-protocol.sh run` (so evidence is digest-bound) is sufficient; hosted CI would add only independent-environment reproduction, which the project explicitly does not claim.

## Controller cross-scope checks

- Observed-overlap requirement is enforced in verification/linearizability.py:207 as INCONCLUSIVE; managed_verify maps INCONCLUSIVE to non-PASS, and its CLI exits 2.
- Managed evaluator validates the contract before invoking numeric/history checks (managed_verify.py:25); unexpected uncaught errors still fail the outer gate.
- Numeric managed model only creates issued capabilities by design; raw future numeric IDs are exercised by the low-level async fixture. No expanded unbounded claim is made.
- Protocol P2 verified in check(): binding verification currently overwrites stage failure classification with PASS. Original protocol worker is implementing a focused correction and regression tests.

## Full supplied-source CLI review

Actual CLI result: success; modelUsage names claude-fable-5-1. Tools disabled, all three source bundles supplied in stdin. No test execution by this reviewer.

**総合判定: APPROVED**（ブロッキング所見なし。P3 が 3 件）

要求セマンティクスは提示されたソース上で全て満たしています。

- **Refreshing/Logout**: `AsyncSession.swift:81-85` と `AsyncSession.kt:88-93` で Unauthenticated・pending nil・ClearCredentials のみ・nextRequestId 不変（exhausted の nil も不変）。
- **stale 応答 no-op**: `AsyncSession.swift:58-60`、`AsyncSession.kt:54-56` で状態・effects・rejection すべて不変。
- **owner 検査が数値処理より先**: `ManagedAsyncSession.swift:65-68`、`ManagedAsyncSession.kt:56-60`。トークンは fileprivate init / private constructor + internal companion で外部ソースから構築不能、`requestId` は `let`/`val`。
- **スナップショットの原子性**: Swift actor 内 `handle` に await なし（`ManagedAsyncSession.swift:59-85`）、Kotlin は単一 monitor（`ManagedAsyncSession.kt:48-76`）。
- **checker**: 実時間先行は `linearizability.py:141` の return < invoke、トークン出自は `linearizability.py:133-137` で producer の return 先行と effect 内容一致を要求。両 runner とも return スタンプ後に公開（`HistoryProcessor.swift:297,308`、`ManagedHistoryRunner.kt:147-152,163`）なので整合。
- **有限モデル**: `numeric_model.py` は 2 owner・ID 1..3 の BFS、mutant 2 種の期待不変量を `main` で名指し確認。
- **protocol**: 出力パスの symlink 拒否（`change_protocol.py:165-173`）、command.json による argv/cwd 束縛（`:318-322`）、artifact の mtime・digest 束縛（`:302-315`）。

**P3（非ブロッキング）**

1. `change_protocol.py:330-331` — full-gate は exit 1 + `Overall: FAIL` を INFRA_FAILURE に分類し、セマンティック回帰と環境故障を区別しません。async-comparator だけ SEMANTIC_FAIL を持つ非対称です。修正案: exit 1 かつ先頭行 `Overall: FAIL` を SEMANTIC_FAIL に写す。
2. `managed_mutations.py:58-60` — コメントは「foreign workload 由来の FAIL のみ」と述べますが、コードは checker の任意 FAIL を検出成功とみなします。コメントを実態に合わせるか、witness 不在の原因が foreign 行であることを確認する。
3. `managed_verify.py:12` — `aggregate` は NOT_RUN を SEMANTIC_FAIL より優先するため、一方の runner が未ビルドで他方が意味論的に失敗した場合、総合が NOT_RUN になり失敗が見えにくくなります。PASS には化けないので安全側ですが、順序を SEMANTIC_FAIL 優先に入れ替えるのが簡単です。

**直接 main マージの妥当性**

この PoC では直接ローカル main へマージし、クリーンツリーで full gate を再実行する手順で十分です。hosted CI も外部レビュア導線も無いので PR は追加の保証を与えません。マージ後に `git-dirty.txt` が clean、`git-sha.txt` がマージコミットと一致する report.md を証拠として残してください。

**保証の限界**

- テストは実行していません。提示ソースの静的読解のみです。
- 未提示の入力（`AuthReducer`、`contract/specification.json`、`schema.json`、`managed-workload.json`、`managed-mutation-matrix.json`、managed-api fixture、`scripts/managed-verify.sh` / `async-verify.sh`）に依存する経路は未検証です。特に `AsyncSession.swift:107` は core reducer が非 allocate 行で `requestTokenRefresh` を出さない前提で、`validate_async` はこれを直接は検査していません。
- 両 runner は producer がトークンを発行しなかった場合に試行全体を失敗させ INFRA_FAILURE に落ちます（`HistoryProcessor.swift:152-158`、`ManagedHistoryRunner.kt:126`）。同一 owner で TokenExpired と Logout が競合するフェーズを workload に置くと不安定になります。現 workload の構成は未確認です。
- 並行フェーズの重なりは OS スケジューリング依存で、20 試行後は INCONCLUSIVE になる設計です。PASS を偽装はしませんが、再実行で結果が揺れ得ます。
- 有限モデルは 2 owner・ID 1..3 の範囲のみで、無限域の証明ではありません。TLA モデルは pending を真偽値に抽象化しており数値 ID の性質は扱いません。
- 保護プロトコルは協調的作業者の事故防止用で、manifest やチェッカー自体を書き換える controller は想定外です。
- Kotlin の公開 API 検査は Gradle キャッシュ内の全 jar をコンパイラ classpath に載せており（`managed_api.py:55`）、キャッシュ内容次第で挙動が変わり得ます。

## Disposition of CLI P3 notes

- Keep aggregate full-gate exit1 classified conservatively: Overall FAIL can include compiler/infrastructure failures, so mapping all such failures to SEMANTIC_FAIL would weaken the existing acceptance boundary.
- Owner mutants are evaluated only on the one foreign-same-id workload selected at managed_mutations.py:35-36, with exact scenario membership checked. A claim of pinpointing the failing operation is not made.
- NOT_RUN priority remains fail-closed and individual stage verdicts remain in the report; no masking as PASS.
- Hosted CI workflow exists (.github/workflows/verify.yml); the CLI reviewer did not receive that file. Its statement that hosted CI is absent is not adopted. No new hosted run is claimed.
- Protocol P2 from the focused review is fixed despite the broader reviewer finding no blocker. Regression evidence is in fable-protocol-fix.md; scoped Fable re-review pending.

## Scoped P2 fix re-review

Model: claude-fable-5-1. Agent: ad3ccbb82b304007b.

Reviewed `/Users/shigeo/work/mobile/native-contract-poc/reports/fable-review-candidate/fix-review.md` only (diffs plus supplied logs; I executed nothing myself).

**APPROVED**

Basis:

- `change_protocol.py` diff lines 13–14: the bound-result path now returns the recomputed verdict as `classification` (which the CLI exit mapping keys on) and `resultClassification`, with `bindingClassification: PASS` separate. The verdict-mismatch guard (line 12) and all preceding digest/evidence/freshness checks are untouched, so a stored record claiming PASS against failing output still raises `ProtocolError` -> `INFRA_FAILURE`.
- Failure path (lines 18–20) adds `bindingClassification: INFRA_FAILURE` only when `--result` was given and never emits `resultClassification`; source-only `check` output is unchanged.
- Regressions use `subprocess.run` on the real CLI and assert `proc.returncode` (test diff lines 39–40, 51, 60, 68), covering 0/1/2 for PASS/SEMANTIC_FAIL/INFRA_FAILURE/NOT_RUN, altered `stdout.log` -> exit 2 with no `resultClassification`, and source-only PASS exit 0 for a semantically failing candidate. The RED tail (`0 != 2`, `failures=3, errors=2`) confirms the tests detect the original defect; the GREEN tail reports `Ran 19 tests ... OK`.
- Docs (lines 87, 96) state the source-only limitation and the bound non-PASS behaviour explicitly.

Non-blocking nit: `test_cli_result_check_rejects_invalid_evidence_binding` omits `self.manifest.unlink()`; harmless if `tearDown` cleans the temp root.

Final review disposition: APPROVED after the P2 correction. Direct local main integration is appropriate after fresh full validation. No hosted CI result is claimed.

# Scoped Swift/Kotlin Logout review

Verdict: APPROVED for Tasks 3A and 4A. No concrete correctness or scope issue found in the reviewed changes. This approval covers the low-level Logout patches; managed facade work and final frozen evaluation remain separate gates.

Reviewed `evolution-design.md` section A, `native-anchors.md`, author reports `task3a.md` / `task4a.md`, and the diff/current contents of only these native files:

- `ios/Sources/AsyncNativeContract/AsyncSession.swift`
- `ios/Tests/AsyncNativeContractTests/AsyncNativeContractTests.swift`
- `android/async-library/src/main/kotlin/nativecontract/async/AsyncSession.kt`
- `android/async-library/src/test/kotlin/nativecontract/async/AsyncSessionTest.kt`

The new branch implements `(Refreshing, pending=p, next=n) + Logout -> (Unauthenticated, pending=nil/null, next=n)` with exactly `[ClearCredentials]` and no rejection. Neither branch writes the allocator, so ordinary progression and exhausted `nil`/`null` are preserved. Repeated Logout delegates to the unchanged Unauthenticated no-op. Existing guards still require Refreshing and matching pending ID, so cancelled success and failure cannot affect a subsequent login/new refresh. A fresh response remains accepted. The Swift core reducer delegation and Kotlin other transition branches, constructors and public APIs are unchanged by the scoped production diff.

Tests explicitly cover cancellation output, repeated Logout, both stale response variants during the newer refresh, fresh success, and cancellation of the maximum allocated ID followed by atomic exhaustion. Kotlin asserts full snapshots around each stale response. Swift asserts both returned stale results and the complete session triple; its response guard returns before all writes. Existing unrelated tests remain present.

Exact frozen insertion snippets and preserved guard/marker fragments matched the sources exactly, each at its intended existing location. Static inspection command: `python3 - <<'PY'` using `re.findall(r'<!-- fixture:([^>]+) -->\n```(swift|kotlin)\n(.*?)\n```', doc, re.S)` over `native-anchors.md`, requiring `source.count(fragment) == 1`; the Kotlin guard/marker fixture was split into its documented independent fragments. Raw output:

```text
EXACT_ANCHOR_MATCH ios/Sources/AsyncNativeContract/AsyncSession.swift swift
EXACT_ANCHOR_MATCH ios/Sources/AsyncNativeContract/AsyncSession.swift swift
EXACT_ANCHOR_MATCH android/async-library/src/main/kotlin/nativecontract/async/AsyncSession.kt kotlin
EXACT_ANCHOR_MATCH android/async-library/src/main/kotlin/nativecontract/async/AsyncSession.kt kotlin
STATIC_ANCHOR_REVIEW_OK
```

I inspected the existing author RED/GREEN logs with:

```sh
tail -n 10 reports/evolution/task3a/red.log reports/evolution/task3a/green.log reports/evolution/task4a/red.log reports/evolution/task4a/green.log
```

Those tails support the author reports' focused failing-before/passing-after evidence. No native suites or full verifier were rerun in this review, and no new test totals are claimed. No source, spec, evaluator, staging or commit changes were made. The frozen evaluator remains outside this review's edit scope.

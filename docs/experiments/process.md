# AI development experiment record

## Intent and separation
Sol orchestrates and owns the contract; Luna workers implement Swift, Kotlin, and verification in parallel. Each worker received isolated context (`fork_turns=none`) and explicit ownership boundaries. Swift/Kotlin workers were forbidden to read the other native tree; this is an instruction boundary, not an OS-enforced access-control sandbox. No human source comparison is required.

## Fixed baseline
Contract version 1 was fixed on disk before delegation and committed while independent implementation began. Baseline specification snapshot is historical evidence; `contract/specification.json` is the only current authority.

## Rulings
- User supplied complete purpose, behavior, execution method, and instruction to proceed with reasonable assumptions. Execute directly rather than repeat approval gates in generic workflow skills. Risk: an assumption could require later rework.
- JSON runner accepts batch scenarios and rejects unknown events, malformed shapes and duplicate scenario IDs. Risk: consumers expecting tolerant input must adapt.
- Fresh dedicated project directory provides isolation from unrelated mobile projects; no extra worktree needed for initial implementation. Mutations and control experiment use isolated copies.
- Phase 6 changes only the effect trace; session identity or credential replacement is absent and cannot be claimed as verified.
- User subsequently authorized public repository ohioshirt/native-contract-poc creation and publishing; local success cannot substitute for a hosted CI run.

## Evidence policy
Raw command logs are retained under reports/ (gitignored). Evidence documents link to logs and transcribe only actual output. Test counts are not aggregated manually. Git commit and dirty status identify source provenance; contract SHA-256 pins behavior. Compiler/interpreter/runtime versions are recorded by verification.

## Measurement limitations
This harness exposes model selection and messages but no billable-token/currency usage API. Record elapsed wall time and repair dispatches; do not invent token or monetary costs. One trial per configuration is exploratory and cannot establish model superiority; shared infrastructure and order effects are confounders.

## Correction ledger

`team-review-repairs.tsv` records explicit post-submission review correction waves, not all draft feedback or compilation/environment retries. `phase6-team-repairs.tsv` and `phase6-control-repairs.tsv` record additional bug-repair requests after the first implementation candidate; both are empty. Intentional RED phases demonstrate the new effect requirement and are not implementation repair failures. The first root script trial overlapped a script edit and was abandoned/retried; it is not counted as a native semantic fix. GPG commits and compiler/build execution needed sandbox escalation but required no manual code intervention.

Human intervention was limited to the supplied purpose/specification/constraints and GitHub owner/visibility/destination. User changed initial private repository constraint to public. No human native source comparison or implementation change was requested.

Parent session's exact model ID is not independently exposed; it fulfilled the Sol orchestration role. Workers explicitly selected `gpt-6-luna`, and AI quality reviewers explicitly selected `gpt-6.1-sol`. Model switching of the active parent session was not available. No provider usage/currency metrics were available; monetary cost comparison could not be completed.

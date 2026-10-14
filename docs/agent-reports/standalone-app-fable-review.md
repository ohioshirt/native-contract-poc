# Standalone app design — Fable review record

Requested reviewer: Claude (Fable). Both CLI reviews resolved modelUsage to `claude-fable-5-1`. Astra authored design/plan via requested `gpt-6-astra` worker. No implementation or application/model/build test was executed. Baseline is `d2ce1847cb2644252f7c4d069ef9e36142bb327b`.

MCP Agent review request timed out after 300 seconds and returned no usable review. It is not an approval. CLI fallback disabled built-in tools and MCP servers and received complete source bundles over stdin.

## Review 01

Source hashes:

```json
{
  "docs/experiments/standalone-app-design.md": "88f64c731923fc1a573322dab25bbe06bc38ef347b89cad92d1d99412a2bff48",
  "docs/experiments/standalone-app-plan.md": "da84c3dbf433e756959d781810c5dc718a0751be6c4548c4773ff5d07a97da63",
  "ios/Sources/AsyncNativeContract/ManagedAsyncSession.swift": "a618462d4ec6939b0b2fc23b73f41973a42f5e4d9825c17b035748021f7ba079"
}
```

Actual command:

```json
["claude", "-p", "--model", "fable", "--tools", "", "--strict-mcp-config", "--mcp-config", "{\"mcpServers\":{}}", "--permission-mode", "plan", "--no-session-persistence", "--output-format", "json"]
```

Process record: exitCode `0`, timedOut `false`; this is reviewer execution evidence, not test PASS.

**結論:** 良性設計そのものに I1〜I9 を破る反例スケジュールは見つからなかった。FIFO 消費者、slot/epoch 参照同一性、store 検証後の公開、fail-closed の障害処理は整合している。ただし受け入れゲートを構成する**負のコントロールの定義に 2 件の致命的欠陥**があり、このまま Task 3 で凍結すると `integration-controls` と native controls が通らない。Task 0〜2 は着手可、Task 3 の凍結前に以下を直す必要がある。

## Critical

**C1. モデルの N1 相当ミュータント「current-slot guard を外す」は空振りする（design §6 負のコントロール、plan Task 1 `test_stale_commit_mutant_has_I2_or_I4_witness`）。**
§4.3 の適格性は `slot === activeSlot` と `pre.state == Refreshing ∧ pre.pendingRequestId == slot.request.requestId` の連言で、さらに成功コミットは managed post-state Authenticated を要求する。slot guard だけ外しても、APP-02 では Logout 後の pre が Unauthenticated/pending nil なので managed 判定で止まる。APP-04/05 でも pending は B の request ID か nil で、旧 slot の ID と一致しない。owner を跨ぐ場合（RetryCleanup 後の新 owner は `ManagedAsyncSession(nextRequestId: 1)` 既定で ID 1 を再発行する）でも、`handle` が `foreignRequest` を返すので `acceptedSuccess` が偽になる。つまり slot/epoch guard はライブラリの stale/foreign 判定に対する多重防御で、単独で除去しても到達可能な反例が無い。設計自身が「反例欠如は INCONCLUSIVE」と定めているので、ゲートが止まる。
最小修正: モデルの負のコントロールを native N1 と同形の「`admittedSuccess := outcome is Success`（適格性連言と managed 結果の両方を迂回）」に定義し直す。slot guard 単独除去は「冗長 guard の記録実験」と明記し受け入れ条件から外す。§4.3 に「slot/epoch 同一性は managed guard の上位の多重防御」と書く。

**C2. N2/N4 ネイティブ・ミュータントは「名指しの不変量違反」でなく「受領欠落の逸脱ラン」になる可能性が高い（plan Task 6 Frozen native mutation contract、design §3 Login 許可条件、§8 評価分類）。**
N2 ヘルパは「Login B の receipt を待ってから旧 clear を実行」するが、Login は「verified absent storage」でしか許可されないため、APP-05/11 の Login B は未削除の A 資格情報を読んで RejectedBusy/Fault になる。N4 も同様に、APP-10 で Logout が Completed を返すとアプリは FaultLocked に入らず、「FaultLocked でのみ許可」の RetryCleanup が拒否される。どちらも後続の必須 receipt が欠け、§8 の規則で INVALID_HISTORY/INCONCLUSIVE 側に分類されうる。設計は「ミュータント結果を見てから patch 位置を変えない」と凍結しているので、凍結後に気づくと RED からやり直しになる。
最小修正: `scenarios.json` で APP-02/03/04/05/10/11 の**各 Logout receipt 直後に evaluator 所有の store probe 観測を必須化**し、I5 判定を「Completed receipt の observation.store と直後の probe の不一致」として checker に実装する（完全性判定より前に評価する）。N2 ヘルパは Login B receipt 待ちをやめ、`afterLogoutReceipt` フック解放で旧 clear を実行する定義に変える。これで N2 は probe Present(A) による I5 と、Login B 後の clear による I4 を、N4 は probe Present/Unknown による I5/I8 を、受領欠落に依存せず示せる。

## Important

**I-1. stale/foreign Deliver の完了をテストが待てる in-band バリアが未定義（design §4.3、plan Task 6 APP-02 手順）。**
§4.3 は stale 配送を「認証 UI 変更なしで return」と書くだけで、XCUITest/Compose から `completionProcessed` を観測する手段が無い。audit JSONL の実行中読み取りは iOS の test runner からは不安定。修正: 全コマンド（IgnoredStale/IgnoredForeign 含む）が phase 不変のまま `lastCompletedCommandId` と status を含む新 revision を公開すると §4.3 に明記し、I3/I6 がそれを許すことを書く。accessibility id に `last-command-status` を追加する。

**I-2. StorageProbe が候補所有になっている（plan Task 4/5 の Create 一覧、design §5）。**
「独立観測」の根拠である probe が candidate 側 `Debug/StorageProbe.*` に置かれている。修正: 両プラットフォームの probe ソースを File ownership の凍結リストへ移す。iOS probe は `KeychainCredentialStore` を再利用せず自前の `SecItemCopyMatching` クエリを持つ。Android は `run-as cat` によるホスト側読み取りを正本とし、アプリ内 probe は補助に格下げする。

**I-3. 同一性不一致時にも managed `handle` を呼ぶ方針を凍結前に確定する（design §4.3）。**
slot/epoch 不一致でも `handle` を呼ぶため、ライブラリの該当行（例: Authenticated × refreshFailed(stale ID)）が no-op でなければ、良性 stale 配送が FaultLocked に変換され APP-04/05 が落ちる。この挙動は `AsyncSession` の行に依存し、本レビューでは `AsyncSession` 本体を読んでいないので判断を保留する。修正: 同一性不一致時は managed を触らず pre-snapshot のみで IgnoredStale とするか、現方針を維持するなら `contract.json` 凍結前に該当 3 行（Unauthenticated/Authenticated/Refreshing × stale success/failure）が no-op であることを既存 oracle で確認し記録する。

**I-4. Android の `:contract-async` 取り込みはビルド可否未検証で、プリフライト手順が無い（design §2、plan Task 3）。**
別ルートの Gradle 8.13 配下に `projectDir` で既存モジュールを include する場合、流用する build script が `plugins {}` にバージョンを持つ、version catalog や root 側の `allprojects` 規約を参照する、のいずれかなら解決に失敗する。Gradle は classpath 上に既にある plugin へのバージョン付き要求を拒否する。`android/async-library` の build script は本レビューに添付されていないため 未検証。修正: Task 3 に `./gradlew -p apps/android-demo :contract-async:jar` の単独プリフライトを明記し、失敗時の代替（`includeBuild("../../android")` 置換か、元ルートで生成した jar をハッシュ記録して消費）を設計判断として先に書く。新 owner の `nextRequestId` は前 owner の値を引き継ぎ、run 内で wire `requestId` が再利用されないようにする（C1 で触れた再発行への対処）。

**I-5. Xcode プロジェクト形式と時間予算の実現性（design §9、plan Task 3）。**
ローカル Xcode 27.1 で作成した `project.pbxproj` は CI の Xcode 16.2 で開けない可能性がある（objectVersion / synchronized group）。修正: objectVersion を Xcode 16 互換に固定し、CI 相当 Xcode での `xcodebuild -list` をプリフライトに入れる。`ios/Package.swift` の tools-version も Xcode 16.2 で解決できることを記録する。予算面では、device scenario 1200 秒 × 14 シナリオ × 2 プラットフォームの最悪値だけで `maxTotalSeconds=21600` を超える。per-stage 上限をシナリオ数から再計算するか、総予算を見直す。

## 準備状況の判定

- **設計の中核（§1, §4, §5）は健全。** 良性モデルに対する反例スケジュールは発見できなかった。FIFO/再入、store 検証、epoch/slot 権限、fail-closed、再起動時の bootstrap 削除は要求どおり。
- **Task 0〜2（baseline 記録、モデル/checker、サーバ）は着手可。** ただし Task 1 のモデル・ミュータント定義は C1 を反映した形で書く。
- **Task 3 の凍結は C1/C2 を反映するまで不可。** I-1/I-2 は `scenarios.json`、accessibility id、file ownership に影響するので凍結前に同時に直す。I-3 は `contract.json` 凍結前に決める。
- **I-4/I-5 は凍結を止めないが、Task 3 のプリフライトとして明文化しないと Luna が実行時に判断を迫られる。**

## Review 02

Source hashes:

```json
{
  "docs/experiments/standalone-app-design.md": "0b8c69213ad73100885b7c573e3ab430596ac8f8dc75c509f03f48622288e59e",
  "docs/experiments/standalone-app-plan.md": "f01938c80f2c3fd4287fdb38f3c5e2b6239f2b53de5bf2159e4d5811b5312e4d",
  "ios/Sources/AsyncNativeContract/ManagedAsyncSession.swift": "a618462d4ec6939b0b2fc23b73f41973a42f5e4d9825c17b035748021f7ba079",
  "ios/Sources/AsyncNativeContract/AsyncSession.swift": "8f768d7b518b8364974f25babb2ba7379ecc33015ca10b185ee9de01c22b1d55",
  "android/async-library/src/main/kotlin/nativecontract/async/ManagedAsyncSession.kt": "7751ea376170acd2ce9c9d153676d7632bb7ce7959af823590c33d9bea838c8f",
  "android/async-library/src/main/kotlin/nativecontract/async/AsyncSession.kt": "c6d32c173b4e4edf776b2a62509ca57366c1bbb1f16b71b7a72945b2e51170b4",
  "verification/async_contract.py": "bbe906b78ed77d5d23963918d4493135ab3cd9021eed226008c5636077d8fe9c",
  "android/async-library/build.gradle.kts": "1790b1f1cbe894959b3d13c533b541f54afc13c62171fec98906b6ecc14d4c36",
  "reports/standalone-app-design/review-01/review-result.md": "00eaa9969ee3641dfc15c54574859d2da77b23e4622f27bdd720b0327b3737d0"
}
```

Actual command:

```json
["claude", "-p", "--model", "fable", "--tools", "", "--strict-mcp-config", "--mcp-config", "{\"mcpServers\":{}}", "--permission-mode", "plan", "--no-session-persistence", "--output-format", "json"]
```

Process record: exitCode `0`, timedOut `false`; this is reviewer execution evidence, not test PASS.

再レビューを行います。review-01 の C1/C2・I-1〜I-5 の解消状況を添付ソースで裏取りし、改訂で新たに入った阻害要因だけを挙げます。

**結論:** review-01 の Critical 2 件・Important 5 件はすべて解消。良性設計を破る新しい反例スケジュールは見つからなかった。残るのは Task 3 凍結前に埋めるべきインターフェース／実行手順の欠落 3 件（Important）で、設計の正しさには影響しない。

## review-01 指摘の解消状況

- **C1（モデル N1 の空振り）: 解消。** design §6 がモデル負のコントロールを `admittedSuccess := outcome is Success`（適格性連言と managed 結果の双方を迂回）に置き換え、slot guard 単独除去を「任意の冗長性実験」と明記。plan Task 1 のテスト名も `test_unconditional_success_commit_mutant_has_I2_or_I4_witness` に揃っている。
- **C2（N2/N4 が受領欠落ランになる）: 解消。** N2 ヘルパは正規の検証付き clear と SignedOut 公開を先に行い、重複 clear を `beforeDeferredControlClear` で待機する分離効果にしたため Login B が許可される。N4 は `CTRL-N4-FALSE-LOGOUT` の inventory を偽 Completed 受領と直後の独立 probe で終了させ、RetryCleanup を含めない。design §5 で APP-02/03/04/05/10/11 の各 Logout 受領直後の独立 probe を必須化し、checker が完全性判定の後に I5/I8 を評価する構成になっている。
- **I-1（stale 完了の in-band バリア）: 解消。** design §4.3 で IgnoredStale/IgnoredForeign を含む全コマンドが authProjection 不変のまま `lastCompletedCommandId`/`lastCommandStatus` 付き revision を公開すると明記、I3/I6 がそれを許容し、accessibility id `last-command-id`/`last-command-status` が Task 4 に列挙されている。
- **I-2（probe の所有）: 解消。** plan File ownership が両 `StorageProbe` を evaluator 所有に移し、iOS は独自 `SecItemCopyMatching`、Android はホスト側 `run-as cat` を正本、アプリ内 probe を補助に格下げしている。
- **I-3（不一致時も managed `handle` を呼ぶ方針）: 解消。** 添付ソースで確認した。`ios/Sources/AsyncNativeContract/AsyncSession.swift` の応答分岐は `guard state == .refreshing, pendingRequestId == requestId else { return result(effects: []) }` で三つ組を保存し rejection は nil。`android/async-library/.../AsyncSession.kt` も `PATCH_SITE_STALE_RESPONSE_GUARD` で同じ early return。`ManagedAsyncSession` は Swift/Kotlin とも foreign request を `snapshot()`/`currentSnapshot()` 不変・effects 空・`foreignRequest`/`ForeignRequest` で返す。`verification/async_contract.py` の `policy_errors` が「stale response preserves full triple」を独立に強制。design §4.3 の「`rejection == nil` だけでは成功と見なさない」も正しい。
- **I-4（Gradle 流用）: 解消。** 添付 `android/async-library/build.gradle.kts` はバージョン無し `kotlin("jvm")` + `application`、`jvmToolchain(17)`、version catalog／root 規約への参照なし。ルート app build の `kotlin("jvm") version "2.3.20" apply false` で解決する構成は成立する。`kotlinx-serialization-json:1.8.1` が app の推移依存に入る点は lockfile 凍結で扱われている。build root 外の `projectDir` に対する Gradle 8.13 の警告有無は未検証だが、`:contract-async:jar` プリフライトが明示されているので凍結を止めない。allocator ID の owner 跨ぎ引き継ぎは却下で妥当。添付ソースの `belongs(to:)`/`belongsTo` が同番号 foreign request を拒否するので、run 内の数値一意性は安全性に不要。
- **I-5（Xcode 形式・予算）: 解消。** `objectVersion = 56`／`compatibilityVersion "Xcode 14.0"`／synchronized group 不使用／Xcode 16.2 プリフライトが明記。予算は 1200 秒を「プラットフォーム stage 全体」と定義し直し、超過を NOT_RUN と宣言しているので整合する（Android は cold build + emulator 起動を含むため余裕は薄いが、fail-safe 側に倒れる）。

## 残る Important

**I-6. デバッグフック／replay／probe の test 側操作インターフェースが未定義（design §4.1・§8、plan Task 3「Freeze runner interfaces」・Task 6 Interfaces）。**
`ScenarioHooks.pauseIfArmed` と hook 名は定義されているが、凍結対象の `ScenarioUITests.swift`／`ScenarioInstrumentedTest.kt` が呼ぶ arm／arrival 待ち／release、replay、store fault 注入、iOS 内蔵 probe の起動と結果取得の API が無い。XCUITest はアプリ外プロセスなので、Task 4 の accessibility id 一覧（`login-A` ほか）だけでは APP-06/08/09/10/11、CTRL-N2/N3/N4 を記述できず、Luna が凍結前に独自設計を迫られる。
最小修正: plan Task 3 に `DebugScenarioControl { arm(point), awaitArrival(point, timeout), release(point), replayLastCompletion(), injectStoreFault(kind), probeStore() }` を両言語で定義し、iOS は起動引数 `--arm <point>` と panel の accessibility id（例 `hook-release-<point>`、`replay-last`、`probe-store`、結果ラベル `store-probe-result`）を列挙する。Android は同 API を instrumentation から直接呼ぶと明記する。

**I-7. Android の APP-12 を `connectedDebugAndroidTest` 一回で表現できない（plan Task 5 最終項・Task 6 APP-12）。**
instrumentation はアプリプロセス内で走るため、p1 の終了＝プロセス終了であり、`launchOrdinal=2` の起動は別の `am instrument` 呼び出しになる。Task 5 は単一 Gradle タスクで「APP-01–14 を満たす」と書いており、controller の多重起動プロトコル、`-e processInstanceId/launchOrdinal/scenarioId` の渡し方、p1 の end marker と「controller 確認済み終了」の対応が未定義。
最小修正: controller が scenario ごと・launch ごとに `adb -s "$ANDROID_SERIAL" shell am instrument -w -e ...` を argv 配列で起動し、Gradle タスクは APK ビルドと install に限る、と Task 3/5 に書く。APP-12 の p1 は SignedIn A（または Logout 後）で正常終了し、instrumentation runner による終了を termination 確認として記録する。

**I-8. Xcode 16.2 プリフライトを凍結前に実行する手段がローカルに無い（design §2・§9、plan Task 3）。**
ローカル在庫は Xcode 27.1 のみで、plan は「27.1 での実行は互換プリフライトを満たさない」と凍結条件にしている。commit/push が未承認のため CI でも走らせられず、Task 3 の Gate が満たせない。
最小修正: 凍結時は `project.pbxproj` の `objectVersion`/`compatibilityVersion`/synchronized group 不在をテキスト検査で確認し、Xcode 16.2 での `xcodebuild -list`／`-resolvePackageDependencies` は `integration.yml` の preflight stage として CI 初回実行時に満たす（失敗は infra）と書き直す。あわせて macos-15 ランナーに Xcode 16.2 が残っているかは未検証なので、pin 改訂手順をそのまま適用対象にする。

## 判定

- 設計の中核（FIFO/再入、slot・epoch 参照同一性、store 検証後の公開、fail-closed、process namespace、bootstrap 削除）に阻害要因はない。
- **Task 0〜2 は Luna(Max) で着手可。**
- **Task 3 の凍結は I-6〜I-8 を plan に追記してから。** いずれも設計変更ではなく手順・インターフェースの明文化で、再レビューは不要。

## Final disposition

Review-02 confirms review-01 C1/C2 and I1–I5 resolved, including justified rejection of allocator carryover across different owners. Review-02 requires I6 (debug-control interface), I7 (Android process-restart launch protocol) and I8 (local vs CI Xcode compatibility preflight) to be explicit before freeze. It states these clarifications do not require another review. Astra applied those changes. Parent source inspection confirms I6 in design §5.1 and plan Task 3 (exact control API, independent synchronization, panel IDs/startup arguments); I7 in design §5 and plan Task 3 (per-launch instrumentation, force-stop/PID disappearance, persisted-store probe before bootstrap clear); I8 in design §2 and plan Task 3 (local static/Xcode 27.1 preflight before freeze, mandatory Xcode 16.2 preflight in new integration CI). These final clarifications were not sent for a third review, following the explicit review-02 disposition. Final design SHA-256: `0f80a69869c29ca06757c48da73764bbf9aaf0231021d42f19fdc4f8940cddd3`; final plan SHA-256: `c3c0bba4e891de76432d55d982da5b98fb9ac97280de94ec23a4430b610a7cd4`.

The review establishes design inspection only. Dependency resolution, project buildability, finite-model execution, unsafe/control witnesses, native HTTP/store/UI scenarios, and hosted app integration all remain planned work for the implementation session. No reviewer opinion substitutes for their evidence.

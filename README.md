# Native Cross-Platform Contract Verification

SwiftとKotlinの独立したネイティブライブラリを、共通の有限状態機械仕様に対して自動検証するPoCです。KMP、JNI、トランスパイル、ネイティブ実装コードの共有、仕様からの本体コード生成は使いません。人間によるソース比較を受け入れ条件にしません。

## 構成

```text
contract/       唯一の現行仕様 specification.json、JSON Schema、共通テスト入力
ios/           SwiftPMライブラリ、TraceRunner、ユニットテスト
android/        Kotlin/JVM Gradleライブラリ、JSON Runner、ユニットテスト
verification/   Python標準ライブラリによる仕様チェック、oracle、比較器
scripts/        ローカル検証、隔離Mutation実験
.github/        macOS GitHub Actions
docs/          設計、実行計画、エージェント報告、変更実験の証拠
```

Android OS APIに依存しないKotlin/JVMライブラリです。端末アプリ、ネットワーク、暗号、配布は対象外です。

## 仕様と検証の関係

`contract/specification.json` は状態×イベントの全組を明示する決定的Mealy機械です。Schemaと意味検証で、全域性、決定性、宣言された集合内への閉包、Effect上限、到達可能性、テスト列が全遷移組を通ることを確認します。Pythonが仕様から期待Traceを生成します。Swift/Kotlinの出力を期待値の生成元にしません。

初期状態はUnauthenticated。既知イベントの表外の組は自己遷移・Effectなしです。Runnerの未知イベントや不正JSONはstderr診断と非ゼロ終了になります。各シナリオに新しいセッションを使います。Libraryの初期状態はユニットテストでも確認します。空イベント列のTraceは空のstepsです。

Contract Conformanceは各実装を仕様と比較し、Differentialは両実装を独立に比較します。各ステップのevent/state/effectsとEffect順序を比較し、実行時間や内部メタデータは含めません。長さ0〜4の全イベント列を再生成します。ケース削除や期待値の実装追従で成功扱いにしません。

## ローカル実行

Swift 6以降、Java 17、Python 3.9以降が必要です。Gradleは同梱wrapperの9.8.0（distribution SHA-256付き）、Kotlin pluginは2.3.20、JSON dependencyはkotlinx.serialization 1.8.1に固定しています。初回はGradle distribution/Maven依存のネットワーク取得が必要です。Runner stdoutにはJSONのみ、ビルドと診断は別ログへ保存します。

```sh
bash scripts/verify.sh                 # build/unit/contract/differential/mutationの全ゲート
bash scripts/verify.sh "$PWD/reports/run"  # 出力先を指定
bash scripts/mutation-test.sh          # Mutationだけ実行
python3 -m unittest discover -s verification -p 'test_*.py' -v
```

`SKIP_MUTATIONS=1 bash scripts/verify.sh` は変更実験用の短いゲートです。この実行だけではMutationの成功を主張できません。ビルドキャッシュは`.gradle-home/`と`.swift-cache/`へ保存し、検証Artifactに混入させません。

例として、Runnerはstdinの`{"scenarios":[{"scenario":"example","events":["LoginSucceeded","TokenExpired"]}]}`を読み、stdoutへ`{"traces":[...]}`を返します。Swift Runnerは`ios/.build/debug/TraceRunner`、Kotlin Runnerは`android/library/build/install/library/bin/library`です。

Schema validatorは付属Schemaで使うJSON Schemaの部分集合を実装し、未知の検証keywordを拒否します。汎用JSON Schemaエンジンではありません。仕様・Schema・検証Traceの重複JSON keyも拒否します。

## Mutation Testing

A: SwiftのTokenExpiredをUnauthenticatedへ誤遷移 → Swift FAIL / Kotlin PASS / Differential FAIL。

B: KotlinのRefreshFailedからClearCredentialsを除去 → Swift PASS / Kotlin FAIL / Differential FAIL。

C: 両実装のLogoutからClearCredentialsを除去 → Swift FAIL / Kotlin FAIL / Differential PASS。

Cは両実装の一致だけでは共通の誤りを検出できないことを実証します。コピーした隔離ソースを変更して再ビルドし、通常のソースには変更を加えません。コンパイル失敗はMutation検出成功として扱いません。

## 自律仕様変更

最初にversion 1を検証し、その後SolがAuthenticated×LoginSucceededを「Authenticated維持、ClearCredentials発生」へ変更します。古い実装でContractが失敗することを確認してから、両Lunaへ別々に変更を委譲します。既存テストを維持し、変更ケースを追加して同じ全域検証を再実行します。

ここで検証するのはEffectの発生だけです。セッションIDや認証情報の実体がないため、実際に既存セッションが置換される性質は検証しません。

## 保証できる範囲と限界

検証が示すのは、実行したツールチェーンと入力領域における、長さ0〜4のイベント列・各中間状態・順序付きEffectの仕様適合性と実装間一致です。有限テストは任意の長さに対するプログラムの完全な等価性証明ではありません。仕様の有限モデルについての全域性等のチェックも、実装の形式的な証明とは別です。

呼び出し側がイベントを逐次処理することを前提にします。同時呼び出しの線形化可能性、キャンセル、非同期refreshの競合、永続化、メモリや性能上限、実機OS統合、通信や暗号の安全性、資格情報削除の実Effect、任意の不正入力への頑健性は保証対象外です。仕様・oracle・比較器が共通に誤るリスクは残ります。Mutationは指定された誤りの検出力を示すもので、全ての誤りに対する検出保証ではありません。

Swift/Kotlin担当の独立性は別コンテキストと指示で確保しました。OS権限で互いのソース読取を禁止するアクセス制御は導入していません。エージェントの自己申告や人間のレビューをテストの代替にしません。

## 実測結果と受け入れ証拠

[GitHub Actions](https://github.com/ohioshirt/native-contract-poc/actions/workflows/verify.yml) はPull RequestおよびmainへのPushで同じ全ゲートを実行します。macOS 15 / Xcode 16.2、Python 3.12.8、Temurin Java 17.0.13を指定し、Kotlin/Gradleは上記の固定版を使います。Job SummaryとArtifactに判定、各実行コマンド・ログ末尾、Commit SHAとdirty状態、Contract SHA-256、ツールバージョン、シナリオ数、失敗ステップ、Mutation manifestを保存します。ツールのバージョン指定はありますが、CI Action tagやrunner imageは可変です。

![CI](https://github.com/ohioshirt/native-contract-poc/actions/workflows/verify.yml/badge.svg?branch=main)

| 受け入れ項目 | 記録 |
|---|---|
| SwiftPM / Gradle build・unit test | [v1ローカル](docs/experiments/v1-evidence.md)、[v2ローカル](docs/experiments/v2-evidence.md) |
| 全781シナリオ、両ContractとDifferential | 両版の実測ログにPASSとシナリオ数を記録 |
| Mutation A/B/C | 両版で期待行列を実測。CはContract FAIL/FAIL、Differential PASS |
| hosted CI | [v1成功Run](https://github.com/ohioshirt/native-contract-poc/actions/runs/37883044062)、[実Artifact証拠](docs/experiments/v1-ci-evidence.md)。現行mainの結果は上記workflow/badge参照 |
| 仕様変更自動追従 | [Phase6の変更・比較記録](docs/experiments/change-comparison.md) |
| 人間によるソース比較なし | 独立Luna実装、AI品質確認、仕様oracleを使用。人間は目的・制約・GitHub接続先のみ提示 |

v1 Contract SHA-256は`9fec360d43f7f730867a6d5819e9065d629f55c107a6172a81f7016e2bdfee34`、v2は`fe82d03428bcd33b7101aaf24ff717d3bc59035f10ec22c2719147ca9602ec11`です。履歴用のbaseline snapshotは現行の振る舞い基準ではありません。現行基準は常に`contract/specification.json`です。

Luna単独との追加比較では、同じEffect変更を隔離コピーで実施し、Sol側の独立期待値でも評価しました。モデルの費用・トークン情報は取得できず、単発で条件にも差があるため優劣や費用対効果は結論しません。親セッションの正確なモデルIDは取得できずSolの役割を担い、Luna workerには`gpt-6-luna`、AI reviewerには`gpt-6.1-sol`を明示指定しました。

[プロセスと前提](docs/experiments/process.md)、[最終AIレビュー](docs/agent-reports/final-review.md)に委譲境界・修正記録・残存リスクを記載しています。完全な実装等価性、非同期・実機・認証情報の置換は保証しません。

## 次のステップ

TLA+またはQuintで状態遷移・安全性・活性をモデル化し、仕様の性質をモデル検査できます。実装との対応には別の精緻化関係または抽象化が必要です。非同期refreshを追加する場合はrequest/session ID、遅延応答、Logoutとの競合、イベントの順序と公平性を仕様化します。SwiftPM/Maven配布前には公開API互換性、実機統合、バージョン管理、署名と依存供給網を検討します。

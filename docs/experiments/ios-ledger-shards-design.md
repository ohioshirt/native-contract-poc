# iOS ledger のシナリオ分割設計

状態: 設計・実装レビュー済み。ローカル回帰検証済み。シャード版 CI は未実行。

## 目的と時間の扱い

hosted macOS 上で candidate-ios の全シナリオを実行すると、凍結された
1800 秒のステージ制限を超える。ユーザー指定の方式2として、シナリオを
4 シャードに分割して並列実行する。作業と CI を合わせて3時間以内を目標にする。
controls / legacy-full の所要時間、ランナー待ち、初回修正の有無が未確定なので、
これは完了保証ではない。未完走の結果を acceptance として扱わない。

## 実行構成

既存の5論理ステージと、ローカルの一括実行は残す。
`candidate-ios-shard-1` から `candidate-ios-shard-4` を追加し、それぞれ
integration-comparator、ios のみ、timeoutSeconds=1800 として freeze する。

| ledger | 実行ステージ |
|---|---|
| ios-shard-1 | candidate-ios-shard-1 |
| ios-shard-2 | candidate-ios-shard-2 |
| ios-shard-3 | candidate-ios-shard-3 |
| ios-shard-4 | candidate-ios-shard-4 |
| ios-auxiliary | integration-red → integration-controls（ios）→ legacy-full |
| android | candidate-android → integration-controls（android） |

iOS は既存ジョブを matrix 化し、fail-fast=false とする。各ジョブが独立した
所有シミュレータと ledger を持つ。全ジョブは同じ上流の freeze をダウンロードする。
artifact 名に matrix の ledger 名を含め、集計時にも別ディレクトリへ展開する。
controls と legacy-full の制限は維持し、candidate の30分制限を各シャードに適用する。
macOS の同時実行枠や通常 verify による待ち時間はあり得る。

集計入力は排他的な2モードとする。従来モードは旧 iOS 全体 ledger
（RED、candidate-ios、controls、legacy-full）と Android ledger。
シャードモードは iOS 補助 ledger（RED、controls、legacy-full）と全4シャード、
Android ledger。補助 ledger に candidate-ios が含まれる混在、部分シャード、
同じシャード ledger の重複指定を拒否する。実 candidate-ios と派生 candidate-ios を
同時採用・二重計上しない。

## シナリオの分配

シナリオを分割単位とし、同じシナリオのバリアントは同じシャードへ置く。
重みは `max(1, len(launches)) * max(1, len(variants))`。
重みの降順、同重みは inventory 順で、累積重みが最小のシャードへ割り当てる。
同負荷の場合は小さい番号を選ぶ。シャード内の実行順は元の inventory 順に戻す。

| shard | requiredScenarioIds | 起動回数による重み |
|---|---|---|
| 1 | APP-06, APP-13, APP-14 | 7 |
| 2 | APP-03, APP-07, APP-09, APP-12-SAVED | 6 |
| 3 | APP-04, APP-08, APP-10, APP-12-LOGGED-OUT | 6 |
| 4 | APP-01, APP-02, APP-05, APP-10-RECOVER-OLD, APP-11 | 6 |

freeze は各シャードの requiredScenarioIds と全 expectedTraceBindings を含む。
controller はシャード経路に限り明示的な subset を受け付け、元の protected inventory
から対象行を選び、その inventory コピーとダイジェストを証跡に保存する。
従来の全体実行では inventory の完全一致検査を維持する。

## 検証条件

全 iOS シナリオ集合を S、各シャードの集合を S_i とする。

1. 各 S_i は空ではない。異なる i, j に対して S_i ∩ S_j = ∅。
2. ∪ S_i = S。全バリアント集合についても同じ条件を満たす。
3. シャードは4個すべて宣言するか、ひとつも宣言しない。未知のシャード名を拒否する。
4. 各 ledger の manifestDigest と candidateDigest は同じ凍結ソースに一致する。
   コマンド、成果物ハッシュ、所有情報、attempt の一致検査を各 ledger に適用する。
5. 各シャードの実履歴を元の protected inventory と独立 checker で再検証する。
   シャード間の build hash 一致は要求せず、各履歴が自分の実ビルドへ結び付くことを要求する。
6. 派生 candidate-ios は、全シャードが binding PASS かつ complete native PASS の場合だけ PASS。
   シャードの欠落は INFRA_FAILURE。存在する非 PASS は既存分類の優先順に従って伝播する。
7. 全 ledger の実 attempt 数、ステージ別 attempt 数、実 durationSeconds をまとめて
   既存の maxAttempts / maxAttemptsPerStage / maxTotalSeconds と照合する。
   派生行は新しい実 attempt として数えない。
8. 最終出力は従来の5論理ステージを維持する。シャード別 build/device identity と
   検証結果を追加し、全 iOS ケースの論理結果と区別して記録する。

controls の PASS 条件には引き続き両 candidate の PASS、両プラットフォームの
全 named witness、有限モデルと mutant 証跡の一致を要求する。
checker の意味論、APP/CTRL inventory、ネイティブ候補実装は変更対象にしない。

## 変更範囲と検証

- verification/change_protocol.py: 固定シャード名、trace binding、分配の完全性検証。
- integration/protocol_config.py: 決定的分配とシャード stage 定義。
- integration/reproduce.py / controller.py: 指定シャード実行と明示 subset。
- integration/aggregate.py: 従来 ledger 入力を保ち、4つのシャード入力を追加。
- integration workflow: iOS matrix、個別 artifact、集計入力。
- 対応するテスト: 重複・欠落・未知 ID・バリアント欠落・所有不一致・予算超過・
  非 PASS 伝播・従来方式の回帰を確認する。

実装後は Python の integration / verification ゲート、workflow 検証、fresh freeze と
bound RED を実行する。変更結果と生ログを確認してから commit / push / CI 起動を扱う。
現在走っている main CI の結果を、新しい shard 実装の証拠として流用しない。

## 実施順序

設計レビュー → 実装計画 → 失敗する回帰テスト → 実装 → ローカル検証 →
レビュー可能な差分とログ → commit / push → hosted CI → 生証跡の再検証。
所要時間の見込みが3時間を超えた時点で、完了済みと未完了を分けて報告する。

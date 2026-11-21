# 0006：群れ真値・Tracker・Evaluatorの分離

- **Status**：accepted
- **Context**：確定ルート上の群れ，実農場でも再利用するTracker，真値評価を追加する必要がある．

## Decision

確定ルート型群れは`field-sim`でGround Truthとして生成する．Trackerは`ObservationFrame`だけを入力にし，真値対応付けは`field-benchmark`だけが行う．Tracker内部の`TENTATIVE`，`TRACKED`，`LOST`，`AMBIGUOUS`，`RETIRED`はContractsへ追加せずRun診断情報として保存する．

## Alternatives

TrackerへGround TruthまたはSimulator objectを渡す案は，実農場で再利用できず情報漏洩になるため採用しない．内部状態をContractsへ追加する案は既存APIを不必要に拡張するため採用しない．

## Consequences

`04_simulation.ipynb`は群れDatasetを作り，`05_benchmark.ipynb`はObservationからRunを作成した後にEvaluatorを実行する．探索・採食行動，複数仮説追跡，最終的な群れ評価式は後続拡張とする．

## Compatibility

既存Contractsと単独個体`simulate()`は変更せず，追加APIとして提供する．

## Validation

Observation入力だけのRunner，状態遷移，重複統合，群れ真値再現性，Evaluator対応付けを自動テストする．

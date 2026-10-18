# 拡張ポイント

## 追跡手法

研究用Trackerは`workspace/tracking/`に置き，`field-tracker`の共通APIを実装または構成して実行する．Kalman Filter，Stone Soup，世界モデルなどは観測契約だけを入力とし，Simulator内部や評価用Ground Truthへアクセスしない．非観測stepでも予測処理を呼び出せる必要がある．

## カメラ配置

配置手法は`workspace/placement/`に置き，`field-campost`の共通APIを使う．Caseの公開環境情報，候補領域，カメラ制約を入力し，`PlacementProposal`を返す．配置評価ロジックは`field-benchmark`に残し，手法側へ複製しない．

## 行動モデル

行動モデルは`workspace/behavior/`に置き，現在の状態，公開された環境view，時間刻み，明示的な乱数源から次状態を返す．標準はリーダー主導の群れ行動とするが，Scenario設定で交換可能にする．真の群れ・リーダー情報はSimulator内部に留める．

## Simulator backend

`AnalyticBackend`と`GenesisBackend`は同一契約を実装する．backend固有のSceneやTensor型を境界外へ出さず，共通Schemaへ変換する．Genesisはoptional extraまたは環境固有Docker layerとして扱い，共通`requirements.txt`の必須依存にしない．

## 可視化

`field-visualizer`は保存済みDatasetやRun，または公開イベントstreamを読み，Rerun Webへ2D表示する．可視化の都合でSimulator，Tracker，Evaluatorの状態を変更しない．Ground Truthを表示するときは推定と明確に区別する．

## Notebook

`workspace/00_environment.ipynb`から`06_results.ipynb`は環境確認，設定，実行，結果確認の入口とする．アルゴリズム本体はPython moduleへ置き，Notebookへ重複実装しない．Phase 0では実験内容が未確定のためNotebookを作成しない．

## 拡張追加時の確認事項

新規実装は契約version，seedの伝播，単位・座標系，Ground Truth分離，serialization，Jetson/x86依存，テスト，Case/Run成果物への影響を明示する．公開APIやSchemaを変える場合は`docs/decisions/`にDecision Recordを追加してから実装する．


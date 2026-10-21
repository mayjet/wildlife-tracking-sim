# 拡張ポイント

## 追跡手法

研究用Trackerは`workspace/tracking/`に置き，`field-tracker`の共通APIを実装または構成して実行する．Kalman Filter，Stone Soup，世界モデルなどは観測契約だけを入力とし，Simulator内部や評価用Ground Truthへアクセスしない．非観測stepでも予測処理を呼び出せる必要がある．

## カメラ配置

配置手法は`workspace/placement/`に置き，`field-campost`の共通APIを使う．Caseの公開環境情報，候補領域，カメラ制約を入力し，`PlacementProposal`を返す．配置評価ロジックは`field-benchmark`に残し，手法側へ複製しない．

Phase 3の`create_fixed_camera_layout()`は手動固定配置の基準実装であり，探索器ではない．後続の配置手法は最終結果を既存`CameraLayout`へ変換し，`save_case_scene()`で同じ`camera_layout.json`と`environment.usd`を生成する．地表基準入力を使う場合は`FixedCameraPlacement`と同じ高さ規則を使う．

## 行動モデル

行動モデルは`workspace/behavior/`に置き，現在の状態，公開された環境view，時間刻み，明示的な乱数源から次状態を返す．標準はリーダー主導の群れ行動とするが，Scenario設定で交換可能にする．真の群れ・リーダー情報はSimulator内部に留める．

## Simulator backend

`AnalyticBackend`と`GenesisBackend`は同一契約を実装する．backend固有のSceneやTensor型を境界外へ出さず，共通Schemaへ変換する．Genesisはoptional extraまたは環境固有Docker layerとして扱い，共通`requirements.txt`の必須依存にしない．

Phase 3の`load_usd_scene()`は描画・読込確認用の薄いoptional adapterであり，Simulator backendではない．Phase 6以降で`GenesisBackend`を追加するときも，このadapterやUSDを再利用しつつGenesis objectをContractsへ露出させない．

## 可視化

`field-visualizer`は保存済みDatasetやRun，または公開イベントstreamを読み，Rerun Webへ2D表示する．可視化の都合でSimulator，Tracker，Evaluatorの状態を変更しない．Ground Truthを表示するときは推定と明確に区別する．

## Notebook

`workspace/00_environment.ipynb`から`06_results.ipynb`は環境確認，設定，実行，結果確認の入口とする．アルゴリズム本体はPython moduleへ置き，Notebookへ重複実装しない．Phase 0では実験内容が未確定のためNotebookを作成しない．

`00_environment.ipynb`は人工地形・JAXA AW3D30・国土地理院tile・GeoTIFFの共通入口である．利用者が変更する値は先頭の`CONFIG_FILE`だけとし，取得方式と`create/load/edit`はYAMLで指定する．新しいterrain sourceは`TerrainSourceResult`へ変換するadapterとして`field-environment`へ追加し，NotebookにHTTP・座標変換・保存ロジックを置かない．

`04_simulation.ipynb`はPhase 6の薄い入口であり，`SimulationConfig`読込，実行，Matplotlib確認，Dataset round tripだけを行う．新しい単純motionは`MotionConfig` discriminatorへ追加できるが，群れ・行動判断はPhase 10の`DeerBehaviorModel`で拡張し，Phase 6 motionへ混在させない．

地物adapterを追加する場合は，`unavailable`（未取得），`empty`（確認済み0件），`available`を保持し，取得失敗を空集合へ変換しない．GeoJSONはCase local座標または明示したEPSG:4326から変換する．

## 拡張追加時の確認事項

新規実装は契約version，seedの伝播，単位・座標系，Ground Truth分離，serialization，Jetson/x86依存，テスト，Case/Run成果物への影響を明示する．公開APIやSchemaを変える場合は`docs/decisions/`にDecision Recordを追加してから実装する．

# 拡張ポイント

## 追跡手法

研究用Trackerは`workspace/tracking/`に置き，`field-tracker`の共通APIを実装または構成して実行する．Kalman Filter，Stone Soup，世界モデルなどは観測契約だけを入力とし，Simulator内部や評価用Ground Truthへアクセスしない．非観測stepでも予測処理を呼び出せる必要がある．

標準実装は`last_observation`と`constant_velocity`である．研究用方式は`workspace/tracking/<method>.py`へ引数なしの`create_tracker()`を定義し，`05_benchmark.ipynb`の`tracker_methods`へ方式名を追加する．

## カメラ配置

配置手法は`workspace/placement/`に置き，`field-campost`の共通APIを使う．Caseの公開環境情報，候補領域，カメラ制約を入力し，`PlacementProposal`を返す．配置評価ロジックは`field-benchmark`に残し，手法側へ複製しない．

Phase 3の`create_fixed_camera_layout()`は手動固定配置の基準実装であり，探索器ではない．後続の配置手法は最終結果を既存`CameraLayout`へ変換し，`save_case_scene()`で同じ`camera_layout.json`と`environment.usd`を生成する．地表基準入力を使う場合は`FixedCameraPlacement`と同じ高さ規則を使う．

Phase 7のNotebookでは`("grid", 間隔m)`と`("uniform", 観測点数)`を標準宣言とする．研究用手法は`workspace/placement/<method>.py`へ`generate(environment_case, definition)`を定義し，`("<method>", 値)`から自動解決する．値は`definition.parameters["value"]`で受け取り，返り値は共通`ObservationPointLayout`とする．既存IDを上書きしない．

## 行動モデル

行動モデルは`workspace/behavior/`に置き，現在の状態，公開された環境view，時間刻み，明示的な乱数源から次状態を返す．標準はリーダー主導の群れ行動とするが，Scenario設定で交換可能にする．真の群れ・リーダー情報はSimulator内部に留める．

Phase 7の事前確定経路は群れ行動モデルとは分離する．複数のWaypoint Setを入力として，`route_methods`へ書いた`smooth`と`meandering`を全て生成する．研究用生成器は`workspace/behavior/routes/<method>.py`へ`generate(environment_case, definition, waypoint_set)`を定義し，方式名から自動解決する．牧場外のWaypointは許容する．標準生成器では，移動禁止地点のWaypointを設定距離内の移動可能セルへ補正し，Waypoint間の建物・禁止セルをA*で迂回する．補正不能，地形外，標高欠損は拒否する．将来の探索・状態依存行動はWaypoint生成器へ混在させず，別のルート入力方式として接続する．

## Simulator backend

`AnalyticBackend`と`GenesisBackend`は同一契約を実装する．backend固有のSceneやTensor型を境界外へ出さず，共通Schemaへ変換する．Genesisはoptional extraまたは環境固有Docker layerとして扱い，共通`requirements.txt`の必須依存にしない．

Phase 3の`load_usd_scene()`は描画・読込確認用の薄いoptional adapterであり，Simulator backendではない．Phase 6以降で`GenesisBackend`を追加するときも，このadapterやUSDを再利用しつつGenesis objectをContractsへ露出させない．

## 可視化

`field-visualizer`は保存済みDatasetやRun，または公開イベントstreamを読み，Rerun Webへ2D表示する．可視化の都合でSimulator，Tracker，Evaluatorの状態を変更しない．Ground Truthを表示するときは推定と明確に区別する．

## Notebook

`workspace/00_environment.ipynb`から`06_results.ipynb`は環境確認，設定，実行，結果確認の入口とする．アルゴリズム本体はPython moduleへ置き，Notebookへ重複実装しない．Phase 0では実験内容が未確定のためNotebookを作成しない．

`00_environment.ipynb`は人工地形・JAXA AW3D30・国土地理院tile・GeoTIFFの共通入口である．利用者が変更する値は先頭の`CONFIG_FILE`だけとし，取得方式と`create/load/edit`はYAMLで指定する．新しいterrain sourceは`TerrainSourceResult`へ変換するadapterとして`field-environment`へ追加し，NotebookにHTTP・座標変換・保存ロジックを置かない．

`04_simulation.ipynb`はPythonによる実験宣言，Waypoint編集，コメント付きYAML生成，標準観測点配置，確定ルート，群れProfile，Ground Truth，2D可視範囲，Perfect Observation Datasetの確認を行う．`05_benchmark.ipynb`は保存済みObservationからTrackerを実行し，Run保存後にEvaluatorを呼ぶ．新しい探索・採食は確定ルート群れへ混在させず，別の`DeerBehaviorModel`として追加する．

地物adapterを追加する場合は，`unavailable`（未取得），`empty`（確認済み0件），`available`を保持し，取得失敗を空集合へ変換しない．GeoJSONはCase local座標または明示したEPSG:4326から変換する．

## 拡張追加時の確認事項

新規実装は契約version，seedの伝播，単位・座標系，Ground Truth分離，serialization，Jetson/x86依存，テスト，Case/Run成果物への影響を明示する．公開APIやSchemaを変える場合は`docs/decisions/`にDecision Recordを追加してから実装する．
## Phase 7 観測点・観測条件

- 観測点配置は`ObservationPointPlacement`集合を作り，`create_observation_point_layout()`へ渡すことで追加できる．標準40 m gridと等分散配置を上書きしない．
- 取付構成は`CameraMountProfile`でポール高，Camera台数，FOV，距離，間隔，pitchを変更する．解決後の全`CameraSpec`を保存し，再実行時に比較する．
- 可視条件は`VisibilityConfig`で鹿高，sample高，完全/上半身/一部可視，ray stepを変更する．Noisy Observationは追加しない．
- 別raycast実装を追加する場合も，Case形状，閉立体，遮蔽理由，失敗時非可視の規則を維持する．Genesis表示状態へ依存させない．
- ROS用URDF/Xacro出力はPhase 7の正本ではなく将来adapterとする．現時点では`ObservationPointLayout`と`CameraLayout`が再現性のある共通形式である．

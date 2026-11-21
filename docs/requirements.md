# 要件定義

## 目的と範囲

本システムは，3次元農場環境で鹿の追跡手法とカメラ配置手法を再現可能に比較するシミュレーション・ベンチマーク基盤である．主対象はJetson Orin Nano（JetPack 6系，ARM64）であり，x86_64 NVIDIA GPU搭載Linuxも対象とする．

開発はPhase 0〜12で進める．Phase 0〜7の環境・観測基盤に加え，確定ルート型の群れ真値，Observation専用Tracker Runner，初期Benchmark，Rerun 2D記録APIを実装する．探索・採食行動，配置最適化，Noisy Observationは対象外とする．

## 機能要件

- 鹿の移動，追跡，評価の基本座標は2Dとする．地形と遮蔽判定は3Dで扱う．
- Simulator backendは`AnalyticBackend`と`GenesisBackend`を分離する．Genesisは任意拡張であり，初期環境の必須依存にしない．
- カメラの位置，向き，視認距離，FOV，遮蔽条件を設定可能にする．視認距離の初期値は42 mとする．
- 森林は地面から設定可能な高さまでの完全遮蔽領域とし，標準値を10 mとする．牧場内の森林も追跡対象領域に含める．
- 建物は簡易3D形状と鹿の移動不可領域を表現する．
- 観測はPerfect Observationのみとし，可視な鹿の真の2D位置を観測値として生成する．Noisy Observationは実装しない．
- Trackerは非観測期間も個体および群れの状態予測を継続する．牧場境界による追跡終了判定にはTrackerの推定値を使う．
- 大人・子供属性は`UNKNOWN`を許容する．
- 確率分布は1 m，5 m，10 mなど設定可能なグリッド解像度で評価できるようにする．
- 鹿の基本行動はリーダー主導の群れ行動とするが，具体的条件は実験ごとに定義する．
- Datasetを生成・保存・再利用し，同一設定とseedから再現可能な結果を得る．
- 人工地形はFlat，Hills，Valley，Ridgeを生成でき，生成条件とseedをCaseへ記録する．
- Heightmapは`heightmap[y_index, x_index]`とし，最初のcell中心をlocal ENU上のoriginとして管理する．
- Case保存は既存Caseを暗黙に上書きせず，Case IDと相対pathから保存root外へアクセスさせない．
- Terrain meshの各頂点はHeightmapのcell中心`(x, y, elevation)`に対応し，面は南西から北東へ一貫した反時計回りで三角形化する．
- 固定Cameraは地表面からの設置高を指定し，永続化時は共通`CameraLayout`の絶対ENU 3D位置へ変換する．
- USDはm単位・Z-upで`cases/<case_id>/environment.usd`へ保存し，`camera_layout.json`の観測用CameraとUSDの可視化用Cameraを区別する．
- `terrain.source`は`synthetic`，`alos`，`gsi`，`file`を区別し，すべて同じ`EnvironmentCase`へ変換する．入力条件は`workspace/experiments/*.yaml`，確定結果はCaseの`case.yaml`へ分離する．
- ALOS AW3D30をDSMとして記録し，国土地理院tileをDEMとして記録する．出力cell sizeを元データの実効解像度と同一視しない．NoDataを0 mへ置換しない．
- 建物・森林は`unavailable`，`empty`，`available`を区別する．建物は移動禁止，森林は移動可能を原則とし，森林のUSD表示高は標準10 mとする．
- 取得した3 km地形は原本として保持し，3D出力は確定牧場を囲む矩形または正方形へクロップできるようにする．標準では牧場外接矩形の1.5倍かつ100 m以上の余白を確保する．
- 森林・建物の3D形状は全側面・上面・下面を持つ閉立体とし，USDを交換形式，Genesis用OBJを同じ形状から生成する派生形式とする．
- 実地形CaseではRGB画像，土地被覆，森林，開放地，建物，牧場候補，監視範囲を個別に表示・保存し，使用データ，判定条件，集計値を処理記録へ残す．
- 建物外周は国土地理院ベクトルタイルを主入力とし，OSMで名称・高さを補完できるようにする．実高さがない場合は設定した仮定高を明示して3D Meshへ押し出す．
- 最小SimulatorはCase取得元を知らず，静止・等速直線・時刻付きWaypointを同じAPIで実行する．牧場境界外は許容し，地形mesh外，欠損標高，建物・禁止cellは拒否する．
- Phase 6 Datasetは`manifest.json`と`ground_truth.parquet`を保存する．ObservationはPhase 7まで生成せず，manifestに未生成状態を記録する．
- Phase 7 Datasetは`observations.parquet`，使用した観測点配置，Visibility設定を追加し，Observationへ真値IDを保存しない．
- 観測点は地表から5 mの固定ポールを標準とし，1観測点の固定Camera台数は変更可能とする．標準比較は3〜6台，水平FOV 60°，最大視認距離42 mを使用する．
- 標準配置はPythonで`("grid", 間隔m)`または`("uniform", 観測点数)`と宣言する．事前確定ルートは地図GUIで複数のWaypoint Setを作り，各Setへ`smooth`と`meandering`を適用する．配置・ルート・seedの全組合せを再現可能にし，YAMLはコメント付きの実験記録として自動生成する．Waypointは地形取得範囲全体へ指定でき，禁止地点は設定範囲内の移動可能セルへ補正し，Waypoint間の建物・禁止セルは自動迂回する．確定配置と確定ルートは既存IDを上書きしない．
- 可視範囲の40 m gridは高速previewとし，正式な配置評価は1 m gridで足元・胴・頭を判定する．正式評価は分割実行，途中保存，再開，Case・配置単位の再利用を可能にする．
- 2D可視範囲は地表，0.75 m，1.5 mの高さを3D判定して地面上へ投影する．地形cellや可視範囲gridは鹿の連続2D移動を制限しない．
- 群れは確定ルート上のリーダーを基準に成獣・幼獣を配置し，seed付き個体差，最低間隔，建物・禁止セル回避を適用する．真の群れIDとリーダー属性はGround Truthだけへ保存する．
- TrackerはObservationだけを入力とし，重複観測統合，定速度予測，一対一対応，曖昧状態，見失い，再観測，終了，推定群れを管理する．
- Runは公開Track，内部状態，ライフサイクル，対応履歴を保存し，Evaluatorが別処理でGround Truthと比較する．

## Ground Truth分離

Ground Truthを参照できるのはSimulatorとEvaluatorだけである．Trackerへ真の個体ID，群れID，リーダー情報，未来位置を渡してはならない．観測間の関連付けに使う識別子は観測上の識別子であり，Simulator内部の真値識別子と同一であることを要求しない．

## データ配置

Caseの入力，派生地形，USD，Dataset，Runはすべて`cases/<case_id>/`に置く．`data/raw/`，`data/cases/`，ルートの`runs/`，独立した`notebooks/`は設けない．Phase 0では架空のCaseや実験データを作成しない．

## 非機能要件

- Python 3.10をJetsonとx86の共通基準とする．
- 共通Python依存はルートの`requirements.txt`に集約し，GPU固有依存はDockerfileで管理する．
- 交換可能な実装は共通契約に依存し，SimulatorやEvaluatorの内部実装へ依存しない．
- 重要な計算式，座標変換，評価処理にはテストを用意する．
- 既存Schemaと公開APIの後方互換性を維持する．互換性を破る変更はDecision Recordと移行方針を必要とする．

## 現時点の非対象

PLATEAUの自動取得，衛星画像からの独自建物画像認識，鹿の探索・採食意思決定，複数仮説Tracker，配置探索は未実装とする．観測位置誤差は将来の頑健性確認用フックだけを提供し，標準実験では無効にする．GenesisとRerunはoptional依存とし，共通計算をViewer availabilityへ依存させない．

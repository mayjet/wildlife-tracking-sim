# アーキテクチャ

## レイヤ構成

```text
workspace/                 研究者が通常操作する実験層
  tracking/                追跡手法
  placement/               カメラ配置手法
  behavior/                鹿の行動モデル
  experiments/             実験設定
packages/                  共通実装
  field-environment/        地形・環境生成
  field-sim/                シミュレーション
  field-tracker/            追跡共通処理
  field-campost/            配置共通処理
  field-benchmark/          Dataset・評価
  field-visualizer/         Rerun Web 2D表示
libs/
  shepherd-contracts/      共通Schema・データ型
cases/<case_id>/           Case単位の入力・生成物・結果
```

## パッケージ責務

| パッケージ | 責務 | 責務外 |
|---|---|---|
| `field-environment` | 地形取得，人工地形，森林・建物・牧場領域の生成 | 鹿の行動，追跡評価 |
| `field-sim` | 鹿の移動，群れ行動，可視判定，Perfect Observation，backend選択 | Trackerの推定，評価集計 |
| `field-tracker` | 観測入力，共通API，Track管理，再利用可能な追跡処理 | Ground Truth参照，研究手法の固定 |
| `field-campost` | 固定Camera配置，terrain mesh，Layout I/O，USD出力，Genesis optional adapter | 配置最適化，可視・遮蔽判定 |
| `field-benchmark` | Dataset生成・保存・再利用，追跡評価，配置評価 | Tracker内部状態の改変 |
| `field-visualizer` | Rerun Webによる2D表示 | シミュレーション・評価ロジック |
| `shepherd-contracts` | Case，観測，推定，配置，Dataset，Runの共通型 | 実行ロジック |

## 実行時データフロー

Phase 7以降の実験条件は`04_simulation.ipynb`のPython宣言を正本とする．authoring層がコメント付きYAMLを`workspace/experiments/generated/<experiment_id>/`へ生成し，配置・ルート・群れProfile・seedの直積をbatch APIへ渡す．標準配置は`grid`と`uniform`である．事前確定ルートでは複数のWaypoint Setを地図GUIで保存し，各Setから標準の`smooth`と`meandering`を生成する．Waypointはルート入力方式の一つであり，将来の探索・行動モデルとは分離する．研究用拡張は`workspace/placement/`と`workspace/behavior/routes/`に置き，方式名と同名moduleを明示的に読み込む．

Waypointは研究者が必ず通過させたい地点，Resolved Routeは約1 m間隔の確定経路，Trajectoryは速度と時刻を与えたGround Truthであり，別々の成果物として扱う．標準ルート生成はCaseのTraversabilityを参照し，禁止Waypointの近傍補正，区間ごとのA*迂回，曲線・蛇行幅の安全側調整を順に行う．元Waypointと補正後座標，迂回区間，最終パラメータはResolved Routeへ記録する．配置と確定ルートはIDで不変とし，変更時は親IDを記録できる新しいIDを作る．

```text
Case -> Environment -> Simulation Backend -> Ground Truth
                                      |          |
                                      v          v
                            Perfect Observation  Evaluator
                                      |
                                      v
                             Tracker / Placement
                                      |
                                      v
                                  Estimate
                                      |
                                      v
                                   Evaluator -> Run
```

Ground TruthからTrackerへの経路は存在しない．Evaluatorは観測・推定とGround Truthを別入力として受け取る．DatasetにはTracker入力用の観測と評価用の真値を論理的または物理的に分離して保存する．

`field-tracker`のRunnerは`ObservationFrame`だけを引数に取り，複数Cameraの同位置観測を統合してから個体Trackへ対応付ける．内部状態はRun成果物へ保存するが，公開出力はContractsの`TrackingFrame`へ変換する．`field-benchmark`だけが保存済みGround TruthとTrackを対応付ける．これらの長時間処理は`workspace/run_experiments.py`が実行し，`05_benchmark.ipynb`は保存済み結果だけを分析する．

## Backend境界

`AnalyticBackend`は幾何・運動モデルで動作する標準backendとする．`GenesisBackend`は同一のSimulator契約を実装する任意backendとし，Genesis固有型を共通契約へ露出させない．両backendは同じseed，時間刻み，Case入力，Observation出力の意味論を共有する．数値結果の完全一致は要求せず，再現性の範囲をRunメタデータに記録する．

## Case構造

```text
cases/<case_id>/
  case.yaml
  source/
  terrain.tif
  landcover.tif
  traversability.tif
  farm_boundary.geojson
  camera_layout.json
  environment.usd
  datasets/
  runs/
```

`source/`は取得元データと入力設定のarchive，GeoTIFFとGeoJSONは正規化・派生データ，`camera_layout.json`は観測計算用の共通`CameraLayout`，`environment.usd`は3D表示・backend連携用環境，`datasets/`は再利用可能な観測・真値，`runs/`は設定・推定・評価結果を保持する．必須資産は`case.yaml`，`terrain.tif`，`farm_boundary.geojson`，`datasets/`，`runs/`である．未使用sourceや未取得地物の空directoryは作らない．

## 依存方向

`workspace`は`packages`と`shepherd-contracts`へ依存できる．各`packages`は`shepherd-contracts`へ依存できるが，`workspace`へ依存してはならない．Trackerと配置手法はSimulatorやEvaluatorの内部実装へ依存してはならない．循環依存を作らない．

Phase 1ではAPI Protocolも`shepherd-contracts`に置く．これは未実装の`field-tracker`や`field-campost`との二重定義を避け，`workspace`と将来の共通パッケージが同じ型だけに依存できるようにするためである．依存方向は次のとおりである．

```text
workspace/* --------------------------+
packages/field-* ---------------------+--> shepherd-contracts
                                             |
                                             +--> Pydantic

shepherd-contracts -X-> workspace, field-*, Simulator実装, Evaluator実装
```

### Contractsモジュール

| モジュール | 内容 |
|---|---|
| `coordinates` | 2D/3D位置，速度，座標系，姿勢，bounds |
| `environment` | Case，環境参照，牧場境界，Camera，Layout |
| `animals` | 観測・真値で共有する年齢区分 |
| `ground_truth` | Simulator/Evaluator専用の真値 |
| `observations` | Trackerへ渡せるPerfect Observation |
| `distributions` | Gaussian，Particle，Gridの表現 |
| `tracking` | 個体Track，群れTrack，TrackingFrame |
| `manifests` | DatasetとRunのmanifest |
| `protocols` | Tracker，配置，行動モデルの拡張API |

`ground_truth`をTrackerや配置APIの入力経路へ接続しない．例外はSimulator内部で使う`DeerBehaviorModel`だけであり，その入力環境は`LocalEnvironmentView`に制限する．

## Phase 2環境層

`field-environment`は次の依存方向を持つ．

```text
workspace/00_environment.ipynb
              |
              v
      field-environment ----> shepherd-contracts
         |      |   |
         |      |   +-------> Matplotlib（2D表示のみ）
         |      +-----------> Rasterio / Shapely（I/O・Polygon）
         +------------------> NumPy（Heightmap）
```

Notebookは設定とAPI呼び出しだけを行う．Heightmap生成，検証，GeoTIFF/GeoJSON/YAML保存，読み込みは`field-environment`が担当する．`field-environment`はSimulator，Tracker，Benchmark，Genesisへ依存しない．

### Phase 2 Case文書

`case.yaml`は既存`CaseSpec`を`case`fieldに保持し，Phase 2固有の`terrain` metadataと`generation` metadataを併記する．これによりContractsを破壊的に変更せず，セルサイズ，配列shape，origin，生成手法・parameter・seedを保存する．`CaseSpec.environment.terrain`と`CaseSpec.farm_boundary.data_ref`は各成果物の相対pathを示す．

memory上のHeightmapは`values[y, x]`で，`values[0, 0]`は南西側の最初のcell中心である．GeoTIFFは標準的なnorth-up row順へ上下反転して保存し，読み込み時にmemory規則へ戻す．

## Phase 3 3D・Camera層

```text
workspace/00_environment.ipynb
              |
              v
       field-campost ----------------> shepherd-contracts
          |        |                         CameraSpec / CameraLayout
          |        +----------------> field-environment
          |                                  Heightmap / Case I/O
          +--------------------------> NumPy / Matplotlib
          |
          +---- optional -----------> genesis-world + usd-core
```

`heightmap_to_mesh()`はHeightmapの各cell中心を1頂点として，`values[y, x]`と同じrow-major順で頂点を生成する．隣接する4頂点から2三角形を作り，+Z側から見て反時計回りになる面順序とvertex normalを保存する．このPhaseではcell境界の補間やmesh decimationを行わない．

`FixedCameraPlacement`は`(x, y)`と地表面からの高さを受け，Terrain Meshと同じ区分平面補間から`CameraSpec.position.z_m`を求める．鹿，Camera，森林，建物は同じ地表面参照を使用する．保存後は`CameraSpec`の絶対ENU座標を正とする．`camera_layout.json`はContracts JSONそのもので，`environment.usd`内のCamera primは表示用である．観測計算はUSD Cameraではなく`camera_layout.json`を読む．

USD stageは`metersPerUnit=1`，`upAxis=Z`，default prim `/World`とする．Terrain Meshはcell中心座標を内包する．ContractsのCamera body frameは+Xを視線方向，+Yを左，+Zを上とし，USD Cameraの-X/+Y/-Z規則へ表示transformで変換する．元のyaw/pitch/roll，FOV，距離，観測間隔もcustom attributeとして保持し，再読み込み時に`CameraLayout`と照合する．

ASCII USDA writerはNumPyだけで動作し，Jetson上のCase生成を`usd-core`に依存させない．`pxr`がある環境では追加validationを行える．Genesis連携はlazy importし，現行APIの`gs.morphs.USD`と`scene.add_stage()`を使う．`genesis-world`または`usd-core`が無い環境ではCase生成を失敗させず，利用不可理由を返す．

## Phase 4〜5 地理情報・共通Case層

`EnvironmentConfig`はYAMLの`terrain.source`をdiscriminatorとして`synthetic`，`alos`，`gsi`，`file`へ分岐する．adapterは`TerrainSourceResult`へ正規化され，`create_case_from_terrain_source()`以降は取得元に分岐しない．地理Caseは中心緯度経度を原点とするWGS84 local azimuthal equidistant投影を使用し，`LocalCoordinateSystem`へEPSG:4326，投影定義，基準点，鉛直基準を保存する．

AW3D30 adapterはJAXA Earth API `JAXA.EORC_ALOS.PRISM_AW3D30.v3.2_global`の`DSM` bandを取得する．GSI adapterは公式PNG tileの符号付き0.01 m encodingを復号し，優先datasetから欠損cellを補う．GeoTIFF adapterは入力CRSを必須とする．取得元はnorth-up，memory上は南西cell中心を`values[0,0]`とするため，共通reprojection境界で1回だけrowを反転する．

Case操作は`create`，`load`，`edit`を区別する．`create`は既存Caseを拒否し，`load`は通信しない．`edit`はCase全体を一時directoryへcopyしてから置換し，対象外のsource，Camera，USD，Dataset，Runを保持する．`FeatureLayerStatus`は未取得と空集合を区別し，`traversability.tif`は`0=unknown, 1=traversable, 2=difficult, 3=prohibited`とする．

環境判定は，国土地理院RGBタイル，JAXA土地被覆，傾斜，国土地理院ベクトルタイルの建物外周をCase座標へ揃える．建物の名称・高さは取得できる場合だけOSMで補完し，取得失敗と地物なしを区別する．開放地の連続性，細い森林帯，囲まれた領域，指定座標，建物との距離から牧場候補の塊を選び，研究者の明示設定後に監視範囲として確定する．入力，閾値，面積，件数は`case.yaml`の処理記録へ保存する．

USD森林と建物は取得した2D外周を地表から高さ方向へ押し出し，上面・下面・全側面を持つ閉立体Meshで表現する．森林は地形へ追従し，標準高を10 mとする．実高さがない建物には設定値を使い，仮定値であることを地物属性へ残す．元の3 km地形と地物はCaseへ保持し，3D生成時だけ確定牧場を囲む`scene_crop.geojson`で切り出す．USDを将来のSimulatorを含む交換形式とし，Genesis用OBJは同じCase形状から生成するadapterである．`field_summary.json`にはクロップ寸法，面積，高低差，傾斜，地物面積，Mesh規模を保存する．Phase 7の遮蔽計算はUSDを解析せず，同じCase外周・高さ・平滑化条件を直接使用する．

## Phase 6 最小Simulator層

```text
workspace/04_simulation.ipynb
              |
              v
         field-sim ----------> field-environment ----------> shepherd-contracts
          motion/time             Case/Heightmap              GroundTruth/Manifest
              |
              +-------------> cases/<case_id>/datasets/<dataset_id>/
```

`SimulationConfig`はCase ID，Dataset ID，seed，duration，step，個体属性とmotionを保持する．`simulate()`はmeshの三角形分割と同じ面上線形補間でzを算出し，時刻0から終了時刻まで`GroundTruthFrame`を生成する．Ground Truthは`ground_truth.parquet`へ保存し，`DatasetManifest`にはCase hash，motion，地表補間法，Observation未生成状態を記録する．Phase 6は観測ファイルを生成せず，Trackerへの経路を持たない．

移動処理は，XY経路決定，個体間分離，建物・禁止領域回避，最終XY検証，地表投影の順に実行する．地表投影はXYを変更せず，Terrain Meshと同じ区分三角形補間からGround TruthのZを決める．Genesis等のSimulator adapterはGround Truthを変更せず，モデルの足元Anchorと表示用clearanceだけを適用する．確定経路は物理衝突で変更せず，キネマティックな表示物体として再生する．

Genesisの経路UIはXYを0.25 m以下へ細分化し，各点を地表から1 m上へ再投影する．鹿の初期代理物体は高さ1.5 mの不透明な閉立体で，足元を地表から3 cm上に置く．これらはViewer用表現であり，Tracker入力，観測判定，Ground Truthの正本ではない．将来のIsaac Sim・Unity adapterも同じGround Truth位置を入力とし，座標軸，モデル原点，足元Anchorだけを変換する．

長時間の一括実験は`workspace/run_experiments.py`を入口とする．Parquetを数値結果の正本，Genesisを任意の3D再生Adapter，Rerunを2Dライブ表示と再生記録として分離する．Tracker Runnerは`ObservationFrame`だけを受け取り，各時刻の結果を購読Callbackへ通知する．Callbackは同時刻のGround TruthをRerunとGenesisへ表示できるが，Trackerへ戻さない．実験状態は`execution_manifest.json`へ条件単位で保存し，中断時の`RUNNING`を次回起動時に`PENDING`へ戻す．

数値結果の時刻刻みはDatasetの`simulation_step_s`を維持する．今回の実験RunnerはGenesisのキネマティックActorへGround Truthを反映してSimulatorを進め，GUIが利用可能な場合は同じSceneを表示する．鹿のXYは行動モデルの結果から変更せず，Zだけ地表へ追従させる．表示だけはGround Truth間を線形補間して最大10 FPSとし，補間値を評価やParquetへ混入させない．Rerun Web Viewerは実験Runnerと別プロセスで動かし，Runごとに`recording.rrd`も保存する．表示系の停止・切断は，保存済みDatasetやRunを変更しない．

## Phase 7 観測層

```text
Case + ObservationPointLayout + GroundTruthFrame
                    |
                    v
        field-sim AnalyticRaycastBackend
          distance / horizontal+vertical FOV
          terrain / forest / building occlusion
                    |
                    +--> ObservationFrame
                    +--> 2D VisibilityMap
                    +--> observations.parquet
```

観測点配置は`field-campost`が生成する．標準は40 m正方gridの中心と，同じ観測点数の決定的な最大最小距離配置である．森林・建物内と牧場外を除外し，5 mポール上へ3〜6台のCameraを等角度で取り付ける．6台・水平FOV 60°は理論上360°を覆うが，境界重複は観測点内で1件へ集約する．

遮蔽判定はGenesis sceneやUSD Cameraを状態の正本にせず，CaseのHeightmapと森林・建物PolygonからCPU上で解析的なrayを評価する．森林はUSD/Genesisと同じ平滑化済み外周，地表追従，高さ10 mを用い，建物は取得外周と記録高または仮定高を用いる．raycast失敗を可視扱いへfallbackしない．鹿の地表，0.75 m，1.5 mを個別判定し，`full_body`，`upper_body`，`any_part`を実験条件として区別する．

2D可視範囲は3D判定を設定可能なgridへ投影した確認・配置評価用cacheである．鹿の運動と本番観測は連続座標で直接判定し，可視gridやTerrain cellへ位置を丸めない．

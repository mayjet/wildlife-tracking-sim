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
| `field-campost` | カメラ配置の共通APIと配置結果の表現 | 特定の最適化手法の固定 |
| `field-benchmark` | Dataset生成・保存・再利用，追跡評価，配置評価 | Tracker内部状態の改変 |
| `field-visualizer` | Rerun Webによる2D表示 | シミュレーション・評価ロジック |
| `shepherd-contracts` | Case，観測，推定，配置，Dataset，Runの共通型 | 実行ロジック |

## 実行時データフロー

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
  environment.usd
  datasets/
  runs/
```

`source/`は取得元データ，GeoTIFFとGeoJSONは正規化・派生データ，`environment.usd`は3D環境，`datasets/`は再利用可能な観測・真値，`runs/`は設定・推定・評価結果を保持する．個々の成果物の必須・任意区分はCase Schemaで定義する．

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

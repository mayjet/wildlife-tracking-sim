# 開発計画

本計画はPhase 0〜12を順番に実施する．各Phase完了後は研究者のレビューを受け，承認なしに次Phaseへ進まない．共通処理は`packages/`と`libs/`，研究者が日常操作する入口は`workspace/`に置く．

## Phase一覧

| Phase | 開発対象 | 主な内容 | 状態 |
|---:|---|---|---|
| 0 | 開発環境 | Docker・AGENTS.md・開発規約 | 完了 |
| 1 | 共通Contracts | Schema・共通データ型・Protocol | 完了 |
| 2 | 人工地形生成・Case管理 | Heightmap・人工地形・Case保存・読み込み | 完了 |
| 3 | カメラ配置・Genesis描画 | field-campost・固定配置・簡易3D表示・USD | 完了 |
| 4 | ALOS実地形取得 | Notebookで範囲指定・データ取得・座標変換 | 完了 |
| 5 | 実地形Case完成 | 地形メッシュ・森林・建物・牧場境界・USD | 完了 |
| 6 | シミュレーション基盤 | 鹿の2D真位置・時刻・単純な移動軌跡 | 完了 |
| 7 | カメラ観測 | FOV・距離・3D遮蔽・Perfect Observation | 未着手 |
| 8 | Web 2D可視化 | Rerunで地形・カメラ・真位置・観測位置を表示 | 未着手 |
| 9 | Tracker API | workspaceから追跡・予測手法を実行 | 未着手 |
| 10 | 鹿の群れ行動 | リーダー・子供・探索・採食・追従 | 未着手 |
| 11 | Benchmark | Dataset保存・再利用・追跡評価・手法比較 | 未着手 |
| 12 | 配置探索基盤 | 全探索・最適化・強化学習向け反復評価 | 未着手 |

## Phase 0：開発環境

- **目的**：Jetsonとx86で再現可能な共通開発環境を用意する．
- **編集対象**：`docker/`，`requirements.txt`，基礎文書．
- **依存関係**：なし．
- **完了条件**：Jetson imageのbuild・起動・GPU・Python・bind mountを検証する．
- **引き渡し**：Python 3.10，L4T/CUDA環境，共通依存，開発規約．

## Phase 1：共通Contracts

- **目的**：全componentが共有するSchemaと交換可能APIを確定する．
- **編集対象**：`libs/shepherd-contracts/`，Contracts文書・テスト．
- **依存関係**：Phase 0．
- **完了条件**：Ground Truth分離，座標・時刻・分布・Manifest・Protocolを検証する．
- **引き渡し**：`CaseSpec`，環境・観測・真値・追跡型，拡張Protocol．

## Phase 2：人工地形生成・Case管理

- **目的**：ALOS非依存の人工Heightmapと牧場境界をCaseとして保存・再利用可能にする．
- **編集対象**：`packages/field-environment/`，`workspace/00_environment.ipynb`，関連文書．
- **依存関係**：Phase 1の`CaseSpec`，local ENU，Phase 0のNumPy・Rasterio・Shapely・Matplotlib．
- **完了条件**：Flat/Hills/Valley/Ridge，座標参照，Polygon検証，GeoTIFF/GeoJSON/YAML round trip，Notebook，Jetson pytestが成功する．
- **引き渡し**：検証済み`EnvironmentCase`，Heightmap，Case loader/writer，2D可視化API．

## Phase 3：カメラ配置・Genesis描画

- **目的**：Caseへ固定カメラを配置し，簡易3D環境とUSDを生成・表示する．配置最適化は行わない．
- **編集対象**：`packages/field-campost/`，必要な環境・描画adapter，環境Notebook．
- **依存関係**：Phase 2のHeightmap・Boundary・Case I/O，Phase 1の`CameraSpec`．
- **完了条件**：固定配置，Heightmap cell中心terrain mesh，USD保存・再読込，Notebook実行，Jetson回帰testを確認する．Genesis描画はoptional依存が存在する環境で確認し，存在しない場合は理由を記録する．
- **引き渡し**：`TerrainMesh`，地表基準固定Camera API，`camera_layout.json`，`environment.usd`，Genesis optional adapter．

## Phase 4：公開標高・GeoTIFF取得

- **目的**：単一NotebookからJAXA AW3D30，国土地理院標高tile，既存GeoTIFFを取得・読込しlocal ENUへ変換する．
- **編集対象**：`field-environment`のdata source/transform層，`00_environment.ipynb`．
- **依存関係**：Phase 2のHeightmap契約・Case I/O．
- **完了条件**：取得元，CRS，水平・鉛直基準，変換，cache，欠損処理，実効解像度を記録し，JAXA/GSI経路を個別検証する．
- **引き渡し**：出典付き実地形Heightmapとsource data．

## Phase 5：実地形Case完成

- **目的**：実地形，森林，建物，牧場境界，USDを統合したCaseを完成させる．
- **編集対象**：`field-environment`，Case資産，環境Notebook．
- **依存関係**：Phase 3の3D/USD，Phase 4のALOS Heightmap．
- **完了条件**：人工・実地形を共通Caseへ保存し，森林・建物の取得状態，traversability，境界，terrain mesh，USDの整合性を検証する．森林・建物の自動公開データ取得は後続拡張とする．
- **引き渡し**：Simulatorが消費できる実地形Case．

## Phase 6：シミュレーション基盤

- **目的**：時刻，seed，鹿の2D真位置，単純な再現可能軌跡を扱うSimulatorを構築する．
- **編集対象**：`packages/field-sim/`とsimulation用workspace入口．
- **依存関係**：Phase 1 Ground Truth，Phase 5 Case．
- **完了条件**：静止・直線・Waypoint軌跡を時間発展させ，地表高と禁止領域を検証し，GroundTruthFrameとParquet Datasetをround tripできる．
- **引き渡し**：Phase 7観測処理が利用する真値stream，`SimulationConfig`，保存済みDataset．

## Phase 7：カメラ観測

- **目的**：FOV，距離，terrain/森林/建物遮蔽からPerfect Observationを生成する．
- **編集対象**：`field-sim`観測層と幾何テスト．
- **依存関係**：Phase 3 CameraLayout，Phase 5 3D環境，Phase 6真値．
- **完了条件**：可視な鹿の2D位置だけをObservationへ変換し，真値専用情報を漏らさない．
- **引き渡し**：時刻ごとのObservationFrame．

## Phase 8：Web 2D可視化

- **目的**：Rerun Webで地形，カメラ，真位置，観測位置を検証可能にする．
- **編集対象**：`packages/field-visualizer/`と結果確認Notebook．
- **依存関係**：Phase 2 Heightmap，Phase 3 Camera，Phase 6〜7 frame．
- **完了条件**：Trackerなしで真値と観測の時間変化を2D表示できる．
- **引き渡し**：公開eventから描画する非侵襲visualizer API．

## Phase 9：Tracker API

- **目的**：`workspace/tracking/`の追跡・予測手法を共通Protocolから実行する．
- **編集対象**：`packages/field-tracker/`，`workspace/tracking/`，追跡Notebook．
- **依存関係**：Phase 1 Tracker Protocol，Phase 7 ObservationFrame．
- **完了条件**：空観測stepを含めTrack/GroupTrackを継続生成できる．
- **引き渡し**：交換可能Tracker runnerとTrackingFrame．

## Phase 10：鹿の群れ行動

- **目的**：リーダー，成獣・幼獣，探索，採食，追従を交換可能な行動モデルとして実装する．
- **編集対象**：`field-sim`行動境界，`workspace/behavior/`．
- **依存関係**：Phase 5環境，Phase 6 Simulator，Phase 1 Behavior Protocol．
- **完了条件**：seed再現性，局所環境制限，障害物条件，群れ状態を検証する．
- **引き渡し**：複数Scenarioで利用可能な行動model群．

## Phase 11：Benchmark

- **目的**：Datasetを保存・再利用し，追跡・配置結果を公平に比較する．
- **編集対象**：`packages/field-benchmark/`，benchmark/results Notebook．
- **依存関係**：Phase 6〜10の真値・観測・推定，Phase 1 Manifest．
- **完了条件**：Ground Truth隔離，Dataset round trip，確定済み評価式，再現可能Runを検証する．
- **引き渡し**：Dataset/Run成果物と評価API．

## Phase 12：配置探索基盤

- **目的**：配置案を反復評価する全探索・最適化・強化学習向け共通基盤を提供する．
- **編集対象**：`field-campost`，`workspace/placement/`，benchmark連携．
- **依存関係**：Phase 3配置契約，Phase 7観測，Phase 11評価．
- **完了条件**：同一Case/Scenario/seed群で複数配置を反復評価し，中断・再開できる．
- **引き渡し**：研究用配置探索の安定したrunnerと結果形式．

## 計画変更方針

人工地形，固定カメラ配置，Genesis簡易描画を先行し，Phase 5までにALOS由来の実地形Caseを完成させる．Phase 8まではTrackerに依存せず，真位置と観測の妥当性を確認可能にする．Tracker，群れ行動，Benchmark，配置探索は環境と観測の完成後に実装する．

## 各Phase共通の完了報告

変更ファイル，実装・未実装機能，実行したテスト，既存APIへの影響，残課題，後続Phaseへの引き渡しを報告する．仕様変更は実装前に理由・影響・移行方針を提示する．

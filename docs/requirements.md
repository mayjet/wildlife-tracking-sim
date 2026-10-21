# 要件定義

## 目的と範囲

本システムは，3次元農場環境で鹿の追跡手法とカメラ配置手法を再現可能に比較するシミュレーション・ベンチマーク基盤である．主対象はJetson Orin Nano（JetPack 6系，ARM64）であり，x86_64 NVIDIA GPU搭載Linuxも対象とする．

開発はPhase 0〜12で進める．Phase 0〜6では，開発環境，共通Contracts，人工・公開標高・GeoTIFFの共通Case，固定Camera・terrain mesh・USD，最小Ground Truth Simulatorまでを完成させた．Phase 7以降の観測，Tracker，Benchmark，群れ行動，配置最適化には進まない．

## 機能要件

- 鹿の移動，追跡，評価の基本座標は2Dとする．地形と遮蔽判定は3Dで扱う．
- Simulator backendは`AnalyticBackend`と`GenesisBackend`を分離する．Genesisは任意拡張であり，初期環境の必須依存にしない．
- カメラの位置，向き，視認距離，FOV，遮蔽条件を設定可能にする．視認距離の初期値は42 mとする．
- 森林は地面から5 mまでの完全遮蔽領域とし，牧場内の森林も追跡対象領域に含める．
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
- 建物・森林は`unavailable`，`empty`，`available`を区別する．建物は移動禁止，森林は移動可能を原則とし，森林のUSD表示高は5 mとする．
- 最小SimulatorはCase取得元を知らず，静止・等速直線・時刻付きWaypointを同じAPIで実行する．牧場境界外は許容し，地形mesh外，欠損標高，建物・禁止cellは拒否する．
- Phase 6 Datasetは`manifest.json`と`ground_truth.parquet`を保存する．ObservationはPhase 7まで生成せず，manifestに未生成状態を記録する．

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

## Phase 6完了時点の非対象

OSM/PLATEAU/JAXA土地被覆の自動取得，鹿の群れ・意思決定，Camera観測・遮蔽・ray tracing，Tracker，評価計算，Rerun，配置探索，Noisy Observationは未実装とする．Genesis描画adapterは実装済みだが，`genesis-world`と`usd-core`を共通必須依存にはせず，利用可能な環境だけで実行する．

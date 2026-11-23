# 実験環境の作成と確認

## 1．Case条件をPythonで設定する

`00_environment_python.ipynb`の先頭で，Case ID，取得地点，範囲，解像度，牧場判定，3Dクロップ条件を設定する．YAMLは再現用に自動生成されるため，通常は直接編集しない．

主な項目は次のとおりである．

- `case_id`：保存するCase名
- `terrain`：中心座標，取得範囲，標高セルサイズ
- `detection`：衛星画像，森林，建物，牧場候補の取得・判定条件
- `scene.crop`：3D化する矩形範囲の倍率と余白
- `scene.forest_height_m`：森林遮蔽領域の高さ
- `cameras`：固定カメラ設定

`mode="create"`は同名Caseを上書きしない．作り直す場合は対象Caseを先に削除する．

```bash
rm -rf cases/MiyotaMtBase_gsi_3km_v1
```

## 2．NotebookでCaseを作成する

DockerコンテナへCursorからAttachし，`/workspace/workspace/00_environment.ipynb`を開く．先頭の`CONFIG_FILE`を確認してから，全セルを順番に実行する．

Notebookでは，衛星画像，標高，傾斜，森林，建物，牧場候補，監視範囲，3Dクロップ範囲を確認できる．結果は`cases/<case_id>/`へ保存される．

主な生成物は次のとおりである．

- `case.yaml`，`terrain.tif`：Case情報と標高
- `forest.geojson`，`buildings.geojson`：森林と建物
- `farm_boundary.geojson`，`scene_crop.geojson`：牧場と3D生成範囲
- `environment.usd`，`camera_layout.json`：3D環境とカメラ
- `field_summary.json`，`previews/`：研究用集計と確認画像

## 3．Genesisで閲覧する

`04_simulation.ipynb`を最後まで実行すると，Rerun Web Viewerと実験Runnerのコマンドが表示される．Genesisによる保存済みDatasetの再生には`run_experiments.py replay-genesis`を使用する．

- `environment`：地形，森林，建物だけを表示する．
- `observation-points`：実物層のポールとカメラ筐体を追加する．
- `camera`：全CameraSpecの40 m FOVを半透明表示し，選択観測点を赤で強調する．
- `visibility`：1 m可視結果を疎な緑・赤の点で重ねる．
- `route`：Waypointと確定ルートを表示する．
- `validation`：代表的な可視・不可視視線を追加する．
- `all`：すべてを表示する．情報量が多いため最終確認用とする．

FOV，可視点，ルート，検証線はViewer専用UIであり，物理衝突やセンサー視線を遮らない．再現用USD層と検証JSONはCase内へ保存する．

## 4．観測実験を作成する

`04_simulation.ipynb`の先頭でCase，カメラ配置，カメラ台数，ルート方式，群れProfile，seedをPythonで宣言する．Waypoint GUIセルまで実行して必要なSetを保存した後，残りのセルを実行する．YAMLはNotebookが再現用に自動生成するため，通常は編集しない．

```python
case_id = "MiyotaMtBase_gsi_3km_v1"
camera_placements = [("grid", 40.0), ("uniform", 100)]
camera_counts = [6]
route_methods = ["smooth", "meandering"]
herd_profiles = [{"profile_id": "herd-small", "deer_count": 5, ...}]
seeds = [42]
```

`grid`の値は間隔m，`uniform`の値は観測点数を意味する．リストへ書いた配置，カメラ台数，ルート，seedを全て直積で実験する．宣言例と自作手法の置き場所はNotebook内に記載している．地図クリック式Waypoint Managerでは複数のWaypoint Setを作成・保存・再読込でき，各Setから`smooth`と`meandering`を生成する．赤い移動禁止セル上のWaypointは近い移動可能セルへ補正し，Waypoint間の建物・禁止セルはA*で迂回する．補正と迂回条件は生成YAMLと確定ルートへ記録する．

Notebookはコメント付きYAMLを`workspace/experiments/generated/<experiment_id>/`へ生成し，観測点，確定ルート，足元・胴・頭の1 m正式可視判定と二値化結果を表示・保存する．Ground Truth，Perfect Observation，Tracker，評価はNotebookで実行せず，Python Runnerが生成する．

表示先，コンテナ名，BackendはNotebook末尾の設定で変更できる．FOVの40 mはPhase 7の配置確認用表示距離であり，Perfect Observationの判定条件は保存済みCameraSpecを使用する．

## 5．Trackerと評価を実行する

`05_benchmark.ipynb`でCaseとBenchmark IDを指定し，Runnerが保存した実行状態，スコア，表，グラフを確認する．NotebookはTrackerやEvaluatorを実行せず，`datasets/`と`runs/`を変更しない．

標準Trackerは`last_observation`と`constant_velocity`である．研究用Trackerは[`tracking/README.md`](tracking/README.md)に従って`workspace/tracking/`へ追加する．結果は`cases/<case_id>/runs/<run_id>/`へ保存され，群れ中心位置誤差，非観測時間，5 m・10 m・20 m以内の予測成功率を比較できる．条件別集計は`cases/<case_id>/benchmarks/<benchmark_id>/`へ保存する．評価式と妥当性は[`field-benchmark/README.md`](../packages/field-benchmark/README.md)に記録している．

Rerunを導入した環境では`field_visualizer.log_tracking_replay()`からCase，真値，Observation，Trackを同じ2D時間軸へ記録できる．Rerunは可視化だけを担当し，シミュレーションやTrackerの計算には使用しない．
# 一括追跡実験

長時間の実験はNotebookではなく，`run_experiments.py`で実行する．数値結果はParquetを正本とし，GenesisとRerunは表示に失敗しても数値結果を変更しない．

x86_64 + NVIDIA GPU環境のuv，Genesis，任意noVNC GUIを含む構築手順は
[`docs/x86-experiment-environment.md`](../docs/x86-experiment-environment.md)を参照する．

## 1．Rerun Web Viewerを起動する

実験用コンテナ内で次を実行する．Web Viewerは実験Runnerと別プロセスで動かすため，実験終了後も停止するまで閲覧できる．

```bash
python3 workspace/run_experiments.py serve-rerun
```

Jetsonのブラウザから `http://127.0.0.1:9090` を開く．

## 2．全条件を実行する

別のコンテナ端末で実行する．`CASE_ID`は作成したCaseへ変更する．

```bash
python3 workspace/run_experiments.py run \
  --plan workspace/experiments/generated/miyota-v3-phase7/experiment.yaml \
  --benchmark-id benchmark-v1 \
  --rerun-url 127.0.0.1:9876 \
  --genesis --genesis-viewer \
  --simulation-speed 10
```

- 保存済み実験計画からDatasetと配置別Perfect Observationを生成し，`last_observation`・`constant_velocity`を順番に実行する．
- 完了済み条件は再実行時にスキップし，失敗・未完了条件から再開する．
- TrackerのLOST保持期限は実験Runnerでは180秒とする．
- Ground Truth，Observation，Tracking，評価結果，Rerun記録をRunごとに保存する．
- `05_benchmark.ipynb`は実験完了後の比較・グラフ作成に使用する．

主な保存先は次である．

```text
cases/<case_id>/
├── runs/<run_id>/
│   ├── tracking.parquet
│   ├── group_tracking.parquet
│   ├── group_truth.parquet
│   ├── group_benchmark_assignments.parquet
│   ├── recording.rrd
│   └── live_execution.json
└── benchmarks/<benchmark_id>/
    ├── execution_manifest.json
    ├── condition_results.parquet
    └── summary.csv
```

## 3．Genesisで1条件を確認する

Genesis GUIは描画確認用であるため，Dataset・配置・Trackerを1条件に絞る．Jetsonデスクトップからコンテナへ`DISPLAY`を渡した状態で実行する．
既存Runがある場合は数値結果を上書きせず，保存済みGround Truthを再生する．

```bash
python3 workspace/run_experiments.py replay-genesis \
  --case-id MiyotaMtBase_gsi_3km_v3 \
  --dataset-id <dataset_id> \
  --layout-id <layout_id> \
  --genesis-fov \
  --genesis-backend cpu \
  --simulation-speed 10
```

鹿は不透明な直方体で表示する．保存済みGround TruthのXYを変更せず，地表高へ強制追従させる．数値計算は1秒刻みを正本とし，Genesis表示だけを最大10 FPSへ補間する．

## 4．再実行と修正

- 通常は同じコマンドを再実行し，完了済みRunを再利用する．
- 完了済み結果は上書きしない．実験条件を変更する場合は新しい`benchmark-id`を使用する．
- 途中状態は`execution_manifest.json`へ`PENDING`・`RUNNING`・`COMPLETED`・`FAILED`として保存する．
- 実験条件を変更する場合は，既存結果を上書きせず新しい`benchmark-id`を使用する．

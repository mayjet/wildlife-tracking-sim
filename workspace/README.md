# 実験環境の作成と確認

## 1．YAMLを編集する

`experiments/terrain_miyota_mt_base_gsi.yaml`で，Case ID，取得地点，範囲，解像度，牧場判定，3Dクロップ条件を設定する．

主な項目は次のとおりである．

- `case_id`：保存するCase名
- `terrain`：中心座標，取得範囲，標高セルサイズ
- `detection`：衛星画像，森林，建物，牧場候補の取得・判定条件
- `scene.crop`：3D化する矩形範囲の倍率と余白
- `scene.forest_height_m`：森林遮蔽領域の高さ
- `cameras`：固定カメラ設定

`mode: create`は同名Caseを上書きしない．作り直す場合は対象Caseを先に削除する．

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

`04_simulation.ipynb`を最後まで実行すると，Case，配置，ルートの実データを埋め込んだ`docker exec`コマンドが一覧表示される．Jetsonデスクトップのターミナルへ上から順にコピーして確認する．Shell Scriptの編集は不要である．

- `environment`：地形，森林，建物だけを表示する．
- `observation-points`：実物層のポールとカメラ筐体を追加する．
- `camera`：全CameraSpecの40 m FOVを半透明表示し，選択観測点を赤で強調する．
- `visibility`：1 m可視結果を疎な緑・赤の点で重ねる．
- `route`：Waypointと確定ルートを表示する．
- `validation`：代表的な可視・不可視視線を追加する．
- `all`：すべてを表示する．情報量が多いため最終確認用とする．

FOV，可視点，ルート，検証線はViewer専用UIであり，物理衝突やセンサー視線を遮らない．再現用USD層と検証JSONはCase内へ保存する．

## 4．観測実験を作成する

`04_simulation.ipynb`の先頭でCase，カメラ配置，カメラ台数，ルート方式，seedをPythonで宣言する．Waypoint GUIセルまで実行して必要なSetを保存した後，残りのセルを実行する．YAMLはNotebookが再現用に自動生成するため，通常は編集しない．

```python
case_id = "MiyotaMtBase_gsi_3km_v1"
camera_placements = [("grid", 40.0), ("uniform", 100)]
camera_counts = [6]
route_methods = ["smooth", "meandering"]
seeds = [42]
```

`grid`の値は間隔m，`uniform`の値は観測点数を意味する．リストへ書いた配置，カメラ台数，ルート，seedを全て直積で実験する．宣言例と自作手法の置き場所はNotebook内に記載している．地図クリック式Waypoint Managerでは複数のWaypoint Setを作成・保存・再読込でき，各Setから`smooth`と`meandering`を生成する．赤い移動禁止セル上のWaypointは近い移動可能セルへ補正し，Waypoint間の建物・禁止セルはA*で迂回する．補正と迂回条件は生成YAMLと確定ルートへ記録する．

Notebookはコメント付きYAMLを`workspace/experiments/generated/<experiment_id>/`へ生成し，観測点，鹿の詳細ルート，足元・胴・頭の2D可視範囲を表示する．確定配置は`cases/<case_id>/observation_point_layouts/`，確定ルートは`routes/`，真値と配置別Perfect Observationは`datasets/`へ保存する．既存結果は明示しない限り上書きしない．

表示先，コンテナ名，BackendはNotebook末尾の設定で変更できる．FOVの40 mはPhase 7の配置確認用表示距離であり，Perfect Observationの判定条件は保存済みCameraSpecを使用する．

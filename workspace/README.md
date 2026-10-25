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

Jetsonデスクトップのターミナルから実行する．標準ではX11画面`:1`，コンテナ`wildlife-miyota-dev`，御代田Caseを使用する．終了時はX11許可を自動的に戻す．

```bash
cd ~/Documents/wildlife-management/wildlife-tracking-sim
./workspace/view_environment.sh
```

別の値を使う場合は環境変数で指定する．

```bash
GENESIS_DISPLAY=:1 \
CONTAINER_NAME=wildlife-miyota-dev \
CASE_ID=MiyotaMtBase_gsi_3km_v1 \
./workspace/view_environment.sh
```

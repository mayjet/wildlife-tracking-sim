**Phase 1〜6 研究開発状況**

## 1．Phase 1〜6で実装した内容

- 農場環境の作成，保存，3Dデータ出力から，鹿の正解位置をDatasetとして保存するまでの基本的な実験基盤を実装した．
- 人工地形，JAXA・国土地理院の公開標高，手元のGeoTIFFを，同じ農場Caseとして扱えるようにした．
- Caseの作成とシミュレーションは，Jupyter Notebookから設定ファイルを選んで実行できる構成とした．
- カメラ観測，追跡手法，群れ行動，評価，配置最適化は未実装である．

## 2．農場Caseの作成方法

農場Caseは`workspace/00_environment.ipynb`から作成する．Notebookの先頭では，使用するYAML設定ファイルを指定する．

```python
CONFIG_FILE = "workspace/experiments/terrain_synthetic.yaml"
```

人工地形の設定例は次のとおりである．

```yaml
case_id: synthetic_hills_001
mode: create

terrain:
  source: synthetic
  type: hills
  size_m: 3000
  cell_size_m: 10
  relief_m: 120
  seed: 42

farm:
  boundary_type: rectangle
  size_m: 2000
```

主な設定項目は次のとおりである．

| 設定項目 | 内容 |
|---|---|
| `case_id` | 保存する農場Caseの識別名である． |
| `mode` | 新規作成，読込，編集を指定する． |
| `terrain.source` | 人工地形，JAXA，国土地理院，GeoTIFFを選択する． |
| `terrain.type` | 人工地形の種類を指定する． |
| `terrain.size_m` | 作成する地形の幅と奥行きをm単位で指定する． |
| `terrain.cell_size_m` | 標高を記録する間隔をm単位で指定する． |
| `terrain.relief_m` | 人工地形の標高差を指定する． |
| `terrain.seed` | 同じ地形を再生成するための乱数seedである． |
| `farm.size_m` | 牧場境界の大きさを指定する． |

Caseの操作方法は`mode`で切り替える．

### 新しいCaseを作成する場合

```yaml
mode: create
```

新しいCaseを作成する．同じCase IDが存在する場合は上書きしない．

### 保存済みCaseを読み込む場合

```yaml
case_id: synthetic_hills_001
mode: load
```

保存済みCaseを読み込む．標高データの再取得や地形の再生成は行わない．

### 保存済みCaseを編集する場合

```yaml
case_id: synthetic_hills_001
mode: edit

farm:
  boundary_type: rectangle
  size_m: 1800
```

保存済みCaseの指定項目を編集する．変更対象外の地形，カメラ，Datasetなどは保持する．

## 3．生成物と鹿シミュレーション

Caseを作成すると，`cases/<case_id>/`へ次のファイルが出力される．

```text
cases/<case_id>/
├── case.yaml
├── source/
├── terrain.tif
├── farm_boundary.geojson
├── buildings.geojson
├── forest.geojson
├── traversability.tif
├── camera_layout.json
├── environment.usd
├── previews/
├── datasets/
└── runs/
```

主な出力内容は次のとおりである．

| 出力 | 内容 |
|---|---|
| `case.yaml` | Case ID，地形条件，座標，取得元，生成履歴を保存する． |
| `source/` | 入力した設定ファイルや取得元の標高データを保存する． |
| `terrain.tif` | シミュレーションで使用する標高データである． |
| `farm_boundary.geojson` | 追跡対象とする牧場境界である． |
| `buildings.geojson` | 建物の範囲を保存する．設定されていない場合は生成しない． |
| `forest.geojson` | 森林の範囲を保存する．設定されていない場合は生成しない． |
| `traversability.tif` | 移動可能，移動困難，移動禁止，情報不足を区分したデータである． |
| `camera_layout.json` | カメラの位置，高さ，向き，画角，視認距離を保存する． |
| `environment.usd` | 地形とカメラを3D空間で確認するためのファイルである． |
| `previews/` | 標高，陰影，傾斜，牧場境界などの確認画像を保存する． |

鹿シミュレーションは`workspace/04_simulation.ipynb`から実行する．Notebookの先頭で設定ファイルを指定する．

```python
CONFIG_FILE = "workspace/experiments/simulation_simple.yaml"
```

シミュレーション設定では，使用するCase，保存するDataset名，seed，実験時間，時間間隔，個体ID，個体属性を指定する．

設定ファイルの共通項目は次のとおりである．

```yaml
case_id: synthetic_hills_001
dataset_id: deer_dataset_001
seed: 42
duration_s: 60
step_s: 1
truth_id: deer-001
age_class: UNKNOWN
```

| 設定項目 | 内容 |
|---|---|
| `case_id` | シミュレーションで使用する農場Caseである． |
| `dataset_id` | 保存するDatasetの識別名である． |
| `seed` | シミュレーションを再現するための乱数seedである． |
| `duration_s` | シミュレーション時間を秒単位で指定する． |
| `step_s` | 鹿の状態を更新・保存する時間間隔である． |
| `truth_id` | シミュレーション内部で使用する鹿の個体IDである． |
| `age_class` | 成獣，幼獣，不明の個体属性を指定する． |

実行結果は次の場所へ保存される．

```text
cases/<case_id>/datasets/<dataset_id>/
├── manifest.json
├── simulation_config.json
└── ground_truth.parquet
```

- `manifest.json`には，使用したCase，seed，時間間隔，保存データの参照先を記録する．
- `simulation_config.json`には，実行時のシミュレーション設定を保存する．
- `ground_truth.parquet`には，時刻ごとの鹿の正しい位置，高さ，速度，個体属性を保存する．
- Phase 6では正解位置までを生成し，カメラ観測データや追跡結果はまだ生成しない．

## 4．現在の検証状況と今後の実装

- 人工地形の作成，Case保存・読込，地形の3D化，固定カメラ配置，USD出力，鹿の正解位置保存までを実装した．
- JAXAと国土地理院については，Jetson上で300 m範囲の実データ取得を個別に確認した．
- JAXA実データでは，Case作成，3Dデータ出力，Case再読込，鹿Dataset保存までNotebookから連続実行した．
- Jetson L4Tコンテナでは，Phase 1〜6の回帰テスト98件が成功した．
- Genesisによる描画は，必要なソフトウェアが未導入のため未検証である．
- 今後は，カメラ観測と遮蔽判定，Web可視化，追跡手法，群れ行動，評価，カメラ配置最適化を順に実装する．

参考資料：

- [JAXA Earth API Pythonチュートリアル](https://data.earth.jaxa.jp/api/python/v0.1.6/ja/tutorials/python/)
- [国土地理院の標高タイル仕様](https://maps.gsi.go.jp/development/demtile.html)

# 0004: Unified terrain sources and Phase 6 datasets

## Status

accepted

## Context

人工地形，JAXA AW3D30，国土地理院標高tile，利用者GeoTIFFを同じ後続処理へ渡し，取得元固有処理をSimulatorから隔離する必要がある．Phase 1 Contractsは地形取得metadataやPhase 6実行設定を直接表現しないが，既存APIを破壊してはならない．

## Decision

- YAMLの`terrain.source`をdiscriminatorとし，全adapterを`TerrainSourceResult`から既存`EnvironmentCase`へ正規化する．
- 地理Caseの水平座標は中心点を原点とするWGS84 local azimuthal equidistant投影とし，元CRS・基準点・鉛直基準をCase metadataへ記録する．出力cell sizeと元データの実効解像度は別fieldとする．
- `case.yaml`のoptional metadataとしてprovenance，quality，feature status，config digest，historyを追加し，Phase 2文書を読み込めるdefaultを維持する．Contractsは変更しない．
- `create/load/edit`を明示し，editは一時directoryを経由して対象外資産を保持する．
- Phase 6は既存Ground TruthとDatasetManifestを使用し，実行設定は`field-sim`の`SimulationConfig`，真値はParquetへ保存する．Observationは生成せず，manifestへ未生成状態を明記する．

## Alternatives

取得方式ごとにCase型を分ける案はSimulatorとCamera処理に分岐を漏らすため採用しない．緯度経度を直接simulation座標にする案はm単位の距離・速度と矛盾するため採用しない．Phase 6用にGround Truth型を再定義する案はContracts重複になるため採用しない．

## Consequences

`field-environment`はRasterio，PyProj，Requests，Pillow，SciPyへ依存し，JAXA adapterは`jaxa-earth`を利用する．`field-sim`はParquet用にPandasとPyArrowへ依存するが，GPU・Genesisへ依存しない．AW3D30はDSMであり，地面DEMと同一視できない．地物取得が未実装のCaseは`unavailable`を保持する．

## Compatibility

`shepherd-contracts`は無変更である．Case文書への追加fieldはoptionalであり，Phase 2〜3 APIと資産名を維持する．`field-environment`は上位packageへ依存せず，`field-sim`と`field-campost`が`field-environment`を利用する一方向依存とする．

## Validation

source分岐，設定不正，JAXA/GSI公式取得，GeoTIFF row方向，欠損処理，Case create/load/edit，地物status，Mesh/USD，静止・直線・Waypoint，禁止領域，Ground Truth Parquet，両Notebook，Phase 1〜3回帰をJetson L4T containerで検証する．

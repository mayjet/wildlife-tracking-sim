# ADR 0003: Portable USD and Camera artifacts

- **Status**: Accepted
- **Date**: 2026-10-19

## Context

Phase 3ではJetson ARM64とx86の両方で，Heightmap terrain，固定Camera，USDを同じCaseへ保存する必要がある．旧`field-campost`は`trimesh`でPLY/OBJを扱い，`usd-core`がある場合だけ`pxr`でUSDを生成し，GenesisにはOBJを読み込ませていた．現行Genesisは`gs.morphs.USD`を提供するが，USD importには`usd-core`が必要である．調査したJetson L4T containerには`genesis-world`と`pxr`のどちらも存在しなかった．

## Decision

1. `field-campost`はNumPyだけでHeightmap cell中心から`TerrainMesh`を生成する．旧実装のPLY近傍平均やPoisson再構成は使わない．現行Heightmapは規則gridなので直接変換した方が座標を厳密に検証できる．
2. `environment.usd`はOpenUSD ASCII形式で直接出力し，m単位・Z-up・ENU座標を明示する．これによりJetsonのCase生成を`usd-core` wheelの有無から分離する．`pxr`が利用可能なら追加validatorを実行できる．
3. 観測計算の正規Camera情報はContractsの`CameraLayout`を`camera_layout.json`へ保存する．USD Cameraは表示用とし，元のCamera値をcustom attributeにも保持してround tripを検証する．
4. Genesisはoptional adapterとし，共通`requirements.txt`や標準Docker imageへ強制導入しない．利用可能な環境では`gs.morphs.USD`と`scene.add_stage()`を使用する．
5. 旧実装の配置最適化，近傍地表推定，ray casting，tree/building処理は再利用しない．ray castingと遮蔽はPhase 7，配置探索はPhase 12で扱う．

## Consequences

- Phase 3のCase生成・testはGPU，Genesis，`usd-core`なしで実行できる．
- Terrain meshの外周は最外cell中心までであり，GeoTIFFのcell境界より半cell内側になる．Phase 5で実地形meshの境界要件を再確認する．
- Genesis描画の実機検証には，Jetson対応を確認した`genesis-world`と`usd-core`の別途導入が必要である．未導入環境ではUSD自体の内部readerによる座標round tripまでを完了条件とする．
- `shepherd-contracts`は変更しないため，Phase 1 API互換性を維持する．

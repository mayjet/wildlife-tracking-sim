# 0002: Phase plan and Phase 2 case document

## Status

accepted

## Context

実装経験のある人工地形，固定カメラ，Genesis描画を先行し，TrackerやBenchmarkより前に環境と観測を検証できる計画へ変更する必要がある．Phase 1の`CaseSpec`は環境資産への参照を持つが，Heightmap shape，cell size，生成条件は持たない．

## Decision

- 開発計画をPhase 0〜12へ再編し，Phase 2を人工地形生成・Case管理とする．
- Phase 2の`case.yaml`は`CaseSpec`を変更せず，`case`，`terrain`，`generation`の合成文書とする．
- memory上のHeightmapは南西cell中心をoriginとする`values[y, x]`とし，xは東，yは北へ増加する．
- 標高はGeoTIFF，牧場境界はGeoJSON，metadataはYAMLへ保存する．
- Phase 2は2D生成・表示に限定し，mesh，USD，GenesisはPhase 3へ渡す．

## Alternatives

`CaseSpec`へPhase 2固有fieldを追加する案は，Contractsを環境実装詳細へ結合し，既存Schema versionへの影響が大きいため採用しない．metadataをGeoTIFF tagだけへ格納する案は生成parameterとCase全体の可読性が低いため採用しない．

## Consequences

Case loaderは合成文書を読み，内包する`CaseSpec`とterrain/boundary成果物の整合性を検証する必要がある．将来のALOS sourceも同じHeightmapとCase文書へ変換できる．

## Compatibility

Phase 1 Contractsは変更しない．既存Caseは存在しないためCase file migrationは不要である．

## Validation

生成再現性，coordinate lookup，範囲外，Polygon，path containment，既存Case保護，GeoTIFF/GeoJSON/YAML round trip，Notebook実行を自動テストする．


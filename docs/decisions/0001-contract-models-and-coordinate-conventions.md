# 0001: Contract models and coordinate conventions

## Status

accepted

## Context

Simulator，Tracker，配置法，Behavior，Evaluator間で型を共有しつつ，TrackerへのGround Truth漏洩を防ぎ，Python 3.10のJetsonとx86で同じvalidationとJSON serializationを使う必要がある．座標軸，姿勢，Grid配列の意味が曖昧だと後続実装で互換性を失う．

## Decision

- Pydantic v2の不変modelを使い，未知fieldとNaN/Infを拒否する．
- 標準座標を右手系local ENU（x east，y north，z up），単位をm，m/s，s，radとする．Caseは原点・vertical datum・地理座標変換方法を明示できる．
- カメラ姿勢はintrinsic Z-Y-Xのyaw，pitch，rollとする．
- 真値と観測を別moduleに置き，Observation Schemaに真値fieldを定義しない．
- Gridは`values[y][x]`，originを最初のcell中心とし，軸方向と値の意味を明示する．
- 拡張APIは継承を要求しない`typing.Protocol`とする．

## Alternatives

dataclassだけを使う案はvalidationとJSON Schemaを各consumerが再実装するため採用しない．ABCは研究用実装へ不要な継承を要求するため採用しない．緯度経度を直接追跡座標にする案は距離評価とsimulationを複雑にするため採用しない．

## Consequences

全consumerは`shepherd-contracts`とPydanticに依存する．Caseごとの地理変換はmetadataに記録するが，変換計算は後続Phaseで実装する．Protocolは呼び出し形を定めるだけで，実行時のアルゴリズム動作を提供しない．

## Compatibility

既存SchemaとAPIは存在しないため破壊的変更はない．Phase 1のpackage versionを`0.1.0`，永続化Schemaの初期versionを`1.0`とする．

## Validation

正常・異常値，Ground Truth混入拒否，空観測frame，個体・群れTrack分離，3種分布，Grid整合性，JSON round trip，Protocol適合をpytestで検証する．


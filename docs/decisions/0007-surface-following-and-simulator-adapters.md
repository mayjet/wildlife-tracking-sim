# 0007：地表追従とSimulator adapterの責務

## Status

accepted

## Context

保存済み経路をGenesisへ一定のZ加算だけで描画すると，斜面で経路線や鹿代理物体がTerrain Meshへ埋まる．一方，Genesisの物理衝突で位置を補正すると，既存の建物・禁止領域回避が決めたXYを変え，将来のIsaac Sim・Unity実行とGround Truthが一致しなくなる．

## Decision

- XYは行動モデルと障害物回避で確定し，その後に共通地表投影でZだけを求める．
- 地表高はHeightmapからTerrain Meshと同じ区分三角形補間で算出する．
- Ground TruthのZは地表高そのものとし，表示用clearanceを含めない．
- Simulator adapterはモデル原点，足元Anchor，座標軸，表示用clearanceだけを変換する．
- 現在の鹿代理物体はキネマティックに配置し，物理衝突で経路を変更しない．
- 経路UIは0.25 m以下へ細分化し，各点を地表から1 m上へ再投影する．
- Simulator側Raycastは整合性検証にだけ使用し，Ground Truthを変更しない．

## Alternatives

- 物理Solverへ自由落下させる方式は，経路探索との二重制御になるため採用しない．
- Genesis固有の地表補正をUSDへ焼き込む方式は，他Simulatorとの交換性を損なうため採用しない．
- 経路全体へ一定のZを加える方式は，斜面で線分が地形へ交差するため採用しない．

## Consequences

建物回避結果と地表追従を独立して検証できる．Genesis，Isaac Sim，Unityは同じGround Truthを再生できる．動的な接触応答や歩容は本決定の対象外であり，将来必要になった場合は確定経路を変更しない検証モードと分離する．

## Compatibility

Contracts Schemaは変更しない．既存の2D Ground Truthも読み込める．新規の3D Ground Truthは従来どおりENU，Z-up，m単位で保存する．

## Validation

- 地表投影前後でXYが一致すること．
- Ground TruthのZがTerrain Mesh補間高と一致すること．
- 投影後も建物・禁止領域へ侵入しないこと．
- 経路UIの全点が地表から1 m上にあること．
- 鹿代理物体が不透明な閉立体で，足元が地表から3 cm上にあること．

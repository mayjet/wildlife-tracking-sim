# 0005 観測点と解析可視判定

## Status

accepted

## Context

5 mポールに複数の固定広角Cameraを設置する実農場想定を，2D中心の追跡実験と3D遮蔽確認へ共通利用する必要がある．Camera台数を変えるたびに姿勢やURDFを手作業すると再現性がなく，距離円だけではポール直下の死角，傾斜，森林，建物を表現できない．

## Decision

- Camera単体ではなく，固定ポールの観測点を配置単位とする．
- 標準配置は40 m grid中心と，同数の等分散配置とする．
- 1観測点のCamera台数，FOV，pitchはprofileから自動解決し，要求値と解決済みCameraLayoutを保存する．
- Perfect Observationは距離，水平・垂直FOV，terrain，森林10 m，建物のray遮蔽から生成する．
- 鹿の高さは地表，0.75 m，1.5 mを判定し，3D結果を2D可視範囲へ投影できるようにする．
- USDとGenesisは交換・確認用であり，観測計算の正本はCase形状とContractsとする．

## Alternatives

2D距離円だけで可視範囲を決める案は垂直FOVと遮蔽を扱えないため採用しない．Genesis sceneを観測状態の正本にする案は別Simulator・headless実行・再現性を損なうため採用しない．Camera台数ごとの手書きURDFは現段階で実機frame仕様が未確定なため採用しない．

## Consequences

共通Caseから3D判定し，結果だけを2Dへ投影することで，追跡・配置評価と将来の別Simulatorを同じデータへ接続できる．CPU上で再現可能だが，高解像度の2D可視mapはcell数に応じて処理時間が増える．

## Compatibility

既存`CameraLayout`，`Observation`，`ObservationFrame`は変更しない．`ObservationPointSpec`と`ObservationPointLayout`を加算し，既存Camera APIを維持する．`field-sim`は`field-environment`とContractsへ依存し，`field-campost`やGenesisへ逆依存しない．

## Validation

FOV，ポール直下死角，森林・建物遮蔽，空観測，観測点内重複排除，JSON/Parquet round trip，真値field非混入，40 m grid・等分散配置を単体テストする．Jetson L4T containerで全CPU回帰とNotebook全セルを実行し，御代田Caseで330観測点・1,980 Cameraおよび2D可視mapを確認する．

## Deferred

- ROS用URDF/Xacro自動出力は実機frame・Camera optical frame仕様が確定してからadapterとして追加する．
- Open3D/Embree等の高速backendはJetson ARM64での配布・メモリ条件を確認してから追加する．現在はGPU非依存の解析backendを標準とする．
- 複数の鹿移動Scenario定義と全Scenario直積runnerは，Phase 6のScenario契約を拡張する際に実装する．Phase 7 Notebookは1つの`SimulationConfig`に対して全標準観測配置を比較する．

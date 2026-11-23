# 0008：実験Runnerと表示処理を分離する

## 状態

採用済み．

## 背景

全Dataset・カメラ配置・Trackerを一括実行しながら，Genesisで3D状態，Rerun Web Viewerで2Dの真値・観測・予測を確認する必要がある．Notebook内で長時間処理とViewerを同時起動すると，ブラウザやKernelの終了によって数値結果まで失われる．

## 決定

- `workspace/run_experiments.py`を一括実験の入口とする．
- `workspace/04_simulation.ipynb`は実験計画と1 m正式可視判定・二値化までを担当し，Dataset・Trackerは実行しない．
- Parquetを真値・観測・追跡・評価結果の正本とする．
- GenesisとRerunはRunnerの逐次結果を購読する表示Adapterとする．
- Rerunサーバーは別プロセスで起動し，Runごとの`.rrd`も保存する．
- Genesisは実験RunnerのSimulator adapterとしてGround Truthをキネマティックな不透明Actorへ反映し，物理演算でXY経路を変更しない．GUIは任意とする．
- 数値結果はDatasetの時刻刻みを維持し，Genesisだけを最大10 FPSへ補間する．
- 条件ごとの`PENDING`・`RUNNING`・`COMPLETED`・`FAILED`を保存し，中断後に再開する．
- Trackerへ渡す入力はObservationだけとし，表示Callbackが参照するGround TruthをTrackerへ渡さない．

## 理由

数値結果と表示を分離すれば，Viewerの障害や描画速度が評価結果を変えない．また，同じParquetをGenesis，Rerun，将来のIsaac Sim・Unity adapterで再生できる．

## 代替案

Notebook内で全処理とViewerを起動する案は，中断再開と長時間運用が不安定になるため採用しない．Genesisの物理状態をGround Truthにする案は，既存の経路・建物回避結果と他Simulatorでの再現性を損なうため採用しない．

## 影響

Rerun 0.23以降はNumPy 2を要求し，Jetson上のGenesis 1.4.5・Numba 0.60と競合するため，Rerun SDKは0.22系へ固定する．実験の正式結果はNotebookではなくRunnerが保存し，`05_benchmark.ipynb`は完了後の分析専用とする．

## 互換性

既存の`run_benchmark_matrix()`は低水準APIとして維持する．`04_simulation.ipynb`は計画作成，`05_benchmark.ipynb`は読取専用分析へ変更する．Tracker・Evaluator・Dataset Schemaは変更せず，逐次通知APIと実行Manifestを追加する．

## 検証

Docker内でTracker通知，再開Manifest，Rerun RRD生成，Genesisの地形Meshと動的Actorを検証する．全条件の実験結果は実Dataset生成後に確認する．

# 群れ追跡Benchmark

## 目的

本パッケージは，カメラ観測だけを使って推定された群れ位置を，Simulatorが保持する非公開のGround Truthと比較する．初期研究では，実環境での追跡精度ではなく，観測欠損を含む追跡結果を再現可能かつ一貫して評価できることを検証する．

TrackerはGround Truthを受け取らない．真値との対応付けは，全ての追跡処理が終了した後にEvaluatorだけが行う．実装は[`field_tracker.runner`](../field-tracker/src/field_tracker/runner.py)と[`field_benchmark.evaluator`](src/field_benchmark/evaluator.py)を参照する．

## 評価単位

- **Case**：地形，森林，建物，農場境界を固定した環境である．
- **Dataset**：群れの真値と，カメラ配置ごとのObservationである．
- **Run**：固定Datasetへ一つのTracker設定を適用した結果である．
- **Benchmark**：複数Dataset・配置・TrackerのRunを同じ評価条件で集計した結果である．

## 群れの正解位置

時刻`t`の群れを構成する`N_t`頭の真位置を`x_{i,t}`とし，群れ中心`g_t`を算術平均で定義する．リーダー位置は移動生成に使用するが，群れ中心の正解には使用しない．

```math
g_t = \frac{1}{N_t}\sum_{i=1}^{N_t}x_{i,t}
```

ここで，各記号は次を表す．

- $g_t$：時刻 $t$ における群れ中心の2次元座標である．
- $N_t$：時刻 $t$ に群れを構成するシカの頭数である．
- $x_{i,t}$：時刻 $t$ における群れ内の個体 $i$ の真の2次元位置である．
- $i$：群れを構成する個体を識別する添字であり，$1$から$N_t$までを取る．
- $t$：シミュレーション開始からの経過時刻である．

群れ中心，構成頭数，構成個体ID，中心から最遠個体までの距離は[`group_truth.py`](src/field_benchmark/group_truth.py)が生成する．個体真値を保存するSimulatorは[`herd_simulator.py`](../field-sim/src/field_sim/herd_simulator.py)を参照する．

## 群れ判定

Trackerは個体Track間の距離と速度差から群れを推定する．加入距離と離脱距離を分け，一定時間条件が続いた後にだけ所属を変更する．これにより，閾値付近で群れ判定が毎時刻反転することを防ぐ．群れIDは構成員が一部変化しても維持し，分裂・統合はイベントとして保存する．

実装と設定は[`group_inference.py`](../field-tracker/src/field_tracker/group_inference.py)と[`config.py`](../field-tracker/src/field_tracker/config.py)を参照する．

## 主評価指標

### 群れ中心位置誤差

Trackerの推定群れ中心を`ĝ_t`とし，2D距離を計算する．

```math
e_t = \lVert \hat{g}_t - g_t \rVert_2
```

### 非観測時間

群れのObservationが消失してから，再びObservationが得られるまでの秒数である．非観測区間の抽出は[`events.py`](src/field_benchmark/events.py)が行う．

### 予測成功率

非観測時刻集合を`T_hidden`，許容距離を`r`とする．予測が存在しない時刻も失敗として分母へ含める．

```math
S(r) =
\frac{\#\{t \in T_{hidden} \mid e_t \leq r\}}
{|T_{hidden}|}
```

主結果は`r = 10 m`とし，閾値依存性を確認するため`5 m`と`20 m`も保存する．さらに`0–5秒`，`5–15秒`，`15–30秒`，`30秒以上`へ分け，非観測時間に対する性能低下を確認する．実装は[`group_metrics.py`](src/field_benchmark/group_metrics.py)を参照する．

## カメラ配置との比較

カメラ台数自体は初期評価の順位付けに使用しない．農場内を1 m間隔で評価した2D可視率を観測条件として記録し，次の関係を比較する．

```text
2D可視率 → 観測欠損時間 → 群れ位置の予測成功率
```

異なる可視率の配置を，同じ群れルート・速度・seed・Tracker設定で比較する．

## 任意の観測位置誤差

標準実験はPerfect Observationであり，位置誤差を加えない．将来の頑健性確認用として，`uniform_disk`または`gaussian`の誤差をObservation座標だけへ適用できる．既定値は`enabled=False`である．Ground Truthと可視判定は変更しない．実装は[`observations.py`](../field-sim/src/field_sim/observations.py)を参照する．

## 妥当性の確認

評価基盤の妥当性は，既知の入力に対して指標が次の順序を満たすことで確認する．

1. 正解位置と一致する予測は，位置誤差`0 m`，予測成功率`100%`となる．
2. 既知の位置ずれを加えると，同じ量だけ位置誤差が増加する．
3. 許容距離を超えるずれや予測欠落を増やすと，予測成功率が低下する．
4. 非観測時間を延長すると，該当する時間帯別集計へ反映される．
5. 同一条件とseedでは，同じ評価結果が得られる．
6. Tracker入力へ真の個体ID・群れID・未来位置が含まれない．

これにより，既知の劣化を再現可能かつ単調に計量できることを示す．ただし，この確認だけで実機カメラや現実のシカ行動に対する外的妥当性を保証しない．テストは[`test_evaluator.py`](tests/test_evaluator.py)と[`field-tracker`のテスト](../field-tracker/tests/)を参照する．

## 保存物

各Runへ次を保存する．

```text
runs/<run_id>/
├── tracking.parquet
├── group_tracking.parquet
├── group_events.parquet
├── group_truth.parquet
├── group_benchmark_assignments.parquet
├── group_observation_events.parquet
├── group_duration_summary.parquet
└── group_benchmark_metrics.json
```

一括実験は[`workspace/run_experiments.py`](../../workspace/run_experiments.py)がDataset生成から評価まで実行し，`cases/<case_id>/benchmarks/<benchmark_id>/`へ条件別比較表を保存する．[`05_benchmark.ipynb`](../../workspace/05_benchmark.ipynb)は保存済み結果だけを分析する．全体仕様は[`docs/benchmark-spec.md`](../../docs/benchmark-spec.md)を参照する．

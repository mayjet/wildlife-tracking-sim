# 共通契約

## 実装方針

共通Schemaと拡張APIは`libs/shepherd-contracts`の`shepherd_contracts`パッケージに集約する．Python 3.10以上とPydantic v2を使用し，全Schemaは未知フィールド，NaN，Infを拒否する不変モデルとする．永続化対象には`schema_version`を持たせ，JSON互換形式へ変換できる．

真値型は`ground_truth`，Tracker入力は`observations`へ分離する．`Observation`は`extra="forbid"`により`truth_id`，真の群れ・リーダー情報，未来状態などを受け取れない．Ground TruthへアクセスできるのはSimulator，Behavior，Evaluatorだけである．

## 座標・単位・時間

- 鹿の移動，観測，追跡，評価はCaseローカルの2D世界座標`Position2D(x_m, y_m)`を使う．
- 地形，遮蔽，カメラ位置は`Position3D(x_m, y_m, z_m)`を使う．距離はm，速度はm/s，時間はsである．
- 標準軸は右手系のlocal ENUとし，`+x`を東，`+y`を北，`+z`を上とする．Caseが別方向を使う場合は`LocalCoordinateSystem`に明記し，水平軸は直交させる．
- `z=0`の基準は`vertical_datum`，原点は`origin_description`に記す．地理座標を使うCaseは`geodetic_origin`，地理・投影CRS，`geographic_conversion`に変換方法を記す．変換計算自体はPhase 1では実装しない．
- カメラ姿勢はradで表す．右手系のintrinsic Z-Y-X順とし，yawは`+z`回りで`+x`から`+y`を正，pitchは回転後の`+y`回り，rollは回転後の`+x`回りとする．
- シミュレーション開始を`timestamp_s=0`とする単調増加秒で表す．時間刻みは`DatasetManifest.simulation_step_s`，観測間隔は`CameraSpec.observation_interval_s`に保持し，固定値にしない．

## 環境・カメラ

`CaseSpec`はCase ID，座標系，環境データ参照，牧場境界参照とboundsを持つ．参照先は`cases/<case_id>/`からの相対pathで，絶対pathと`..`を拒否する．`CameraSpec`は3D位置，姿勢，水平・垂直FOV，最大観測距離，観測間隔を持つ．42 mは`DEFAULT_MAX_OBSERVATION_DISTANCE_M`という標準設定であり，Schema fieldの暗黙defaultではない．`CameraLayout`は一意なcamera IDを持つカメラ集合である．

`ObservationPointSpec`は5 mポール等の共通取付点と所属Camera IDを表す．`ObservationPointLayout`は観測点集合，解決済み`CameraLayout`，生成条件metadataを保持し，全Cameraがちょうど1つの観測点へ所属することを検証する．ユーザー指定はCamera台数を中心とし，等間隔yaw，pitch，Camera IDは配置層で解決して保存する．

```python
point = ObservationPointSpec(
    point_id="grid40-r001c002",
    position=Position3D(x_m=20.0, y_m=60.0, z_m=905.0),
    camera_ids=("grid40-r001c002-cam-01", "grid40-r001c002-cam-02"),
)
layout = ObservationPointLayout(
    layout_id="default-grid40-cam2",
    points=(point,),
    camera_layout=camera_layout,
)
```

Phase 3では`FixedCameraPlacement`が地表基準の設置条件を`CameraSpec`へ変換する．永続化形式`camera_layout.json`は`CameraLayout.model_dump_json()`のJSONであり，独自のCamera Schemaを追加しない．`CaseSpec.environment.environment_usd`は`environment.usd`を参照する．Camera Layout pathはCase内の固定規約`camera_layout.json`とし，Phase 1 Contractsにはfieldを追加しない．

```python
camera = CameraSpec(
    camera_id="cam-01",
    position=Position3D(x_m=20.0, y_m=10.0, z_m=3.0),
    orientation=CameraOrientation(yaw_rad=0.0, pitch_rad=-0.2, roll_rad=0.0),
    horizontal_fov_rad=1.57,
    vertical_fov_rad=1.05,
    max_observation_distance_m=DEFAULT_MAX_OBSERVATION_DISTANCE_M,
    observation_interval_s=2.0,
)
layout = CameraLayout(layout_id="layout-a", cameras=(camera,))
```

```python
placement = FixedCameraPlacement(
    camera_id="cam-01",
    x_m=20.0,
    y_m=10.0,
    height_above_ground_m=3.0,
    orientation=CameraOrientation(yaw_rad=0.0, pitch_rad=0.2, roll_rad=0.0),
    horizontal_fov_rad=1.57,
    vertical_fov_rad=1.05,
)
layout = create_fixed_camera_layout(heightmap, [placement], layout_id="layout-a")
```

`CaseSpec`は次のように構成する．

```python
case = CaseSpec(
    schema_version="1.0",
    case_id="farm-a",
    coordinate_system=LocalCoordinateSystem(
        name="farm-a-local",
        origin_description="south-west survey marker",
        vertical_datum="local ground datum",
    ),
    environment=EnvironmentDataRefs(terrain="terrain.tif"),
    farm_boundary=FarmBoundarySpec(
        data_ref="farm_boundary.geojson",
        bounds=AxisAlignedBounds2D(
            min_x_m=0.0, min_y_m=0.0, max_x_m=500.0, max_y_m=300.0
        ),
    ),
)
```

## 真値と観測

`GroundTruthState`は時刻，Simulator専用個体ID，任意の真の群れID・リーダー属性，2Dまたは3D位置，任意速度，年齢区分を持つ．`GroundTruthFrame`は同時刻の真値集合であり，frame内の真値IDを一意にする．

```python
truth = GroundTruthState(
    timestamp_s=1.0,
    truth_id="deer-001",
    group_truth_id="herd-01",
    is_group_leader=True,
    position=Position2D(x_m=8.0, y_m=12.0),
    age_class=AgeClass.ADULT,
)
truth_frame = GroundTruthFrame(timestamp_s=1.0, states=(truth,))
```

`Observation`は時刻，camera ID，観測上のID，Perfect Observationとして得た2D位置，観測可能な年齢区分だけを持つ．位置ノイズ，共分散，真値IDは持たない．観測がないstepは空の`ObservationFrame`で表す．

Phase 7では，同じ観測点のFOV境界で複数Cameraが同じ鹿を捉えた場合，光軸に近い1台へ決定的に集約する．異なる観測点からの観測は別Observationとして保持する．既定では年齢区分を`UNKNOWN`とし，真値の個体ID・群れIDを出力しない．

```python
observation = Observation(
    timestamp_s=1.0,
    camera_id="cam-01",
    observation_id="obs-0001",
    position=Position2D(x_m=8.0, y_m=12.0),
    age_class=AgeClass.UNKNOWN,
)
empty_frame = ObservationFrame(timestamp_s=2.0)
```

## 追跡出力

`TrackEstimate`はTracker自身のtrack ID，時刻，推定2D位置，任意速度，`OBSERVED`，`PREDICTED`，`EXIT_CANDIDATE`，`TERMINATED`の状態，任意の位置分布を持つ．`GroupTrackEstimate`は独立型で，群れ中心，推定・観測構成員数，所属track ID，任意の中心分布を持つ．群れ中心を観測個体位置から自動生成する処理はない．`TrackingFrame`は両者を別collectionに保持する．

```python
track = TrackEstimate(
    track_id="track-01",
    timestamp_s=4.0,
    position=Position2D(x_m=10.0, y_m=11.0),
    status=TrackStatus.PREDICTED,
)
group = GroupTrackEstimate(
    group_track_id="group-track-01",
    timestamp_s=4.0,
    center=Position2D(x_m=15.0, y_m=14.0),
    estimated_member_count=4,
    observed_member_count=1,
    member_track_ids=("track-01",),
    status=TrackStatus.OBSERVED,
)
tracking_frame = TrackingFrame(timestamp_s=4.0, tracks=(track,), groups=(group,))
```

## 位置分布

`PositionDistribution`は`kind`をdiscriminatorとするGaussian，Particle，Gridのunionである．分布の計算・相互変換は実装しない．

```python
gaussian = GaussianPositionDistribution(
    mean=Position2D(x_m=10.0, y_m=11.0),
    covariance_m2=((4.0, 0.5), (0.5, 2.0)),
)
particles = ParticlePositionDistribution(
    particles=(
        Particle2D(position=Position2D(x_m=9.0, y_m=11.0), weight=0.4),
        Particle2D(position=Position2D(x_m=11.0, y_m=11.0), weight=0.6),
    )
)
grid = GridPositionDistribution(
    cell_size_m=5.0,
    origin=Position2D(x_m=2.5, y_m=2.5),
    value_semantics=GridValueSemantics.PROBABILITY_MASS,
    values=((0.25, 0.25), (0.25, 0.25)),
)
```

Gaussian共分散は`(x, y)`順のm²で，対称かつ半正定値とする．Particle weightは非負で合計1とする．Grid配列は`values[y][x]`の`YX`順で，`origin`は`values[0][0]`セル中心，既定では両軸とも正方向へ増加する．`PROBABILITY_MASS`は全セル合計1，`PROBABILITY_DENSITY_PER_M2`はm⁻²の密度値を意味する．`cell_size_m`は正数で，1 m，5 m，10 mなど任意解像度を指定できる．

## Dataset・Run

`DatasetManifest`はCase/Dataset ID，seed，期間，時間刻み，Scenario設定，分離した観測・真値参照を持つ．`RunManifest`はCase/Dataset/Run ID，seed，アルゴリズム名・version・parameter，入力参照，成果物参照，実行環境，状態を持つ．参照はCase directoryからの相対pathとする．

```python
dataset = DatasetManifest(
    schema_version="1.0",
    case_id="farm-a",
    dataset_id="dataset-001",
    seed=123,
    duration_s=600.0,
    simulation_step_s=0.5,
    scenario_config={"camera_observation_interval_s": 2.0},
    observation_data_ref="datasets/dataset-001/observations.parquet",
    ground_truth_data_ref="datasets/dataset-001/ground_truth.parquet",
)
run = RunManifest(
    schema_version="1.0",
    case_id="farm-a",
    dataset_id="dataset-001",
    run_id="run-001",
    seed=123,
    algorithm=AlgorithmSpec(name="my-tracker", version="0.1.0"),
    input_data_refs=("datasets/dataset-001/observations.parquet",),
)
restored = DatasetManifest.model_validate_json(dataset.model_dump_json())
```

Phase 6は既存`GroundTruthState`，`GroundTruthFrame`，`DatasetManifest`を変更せず使用する．`field-sim`の`SimulationConfig`は実行設定でありContracts Schemaではない．保存構造は次のとおりである．

```text
cases/<case_id>/datasets/<dataset_id>/
  manifest.json
  simulation_config.json
  ground_truth.parquet
```

`ground_truth.parquet`は時刻，真の個体ID，任意の真の群れID・leader属性，ENU 3D位置，2D速度，年齢区分を列として持つ．Phase 6ではObservationを生成しないため，`observation_data_ref`は将来の予約path，`scenario_config.observation_data_status`は`not_generated_phase6`とする．TrackerへmanifestのGround Truth参照を入力してはならない．

## Workspace API

`Tracker`，`CameraPlacementMethod`，`DeerBehaviorModel`は`typing.Protocol`による構造的interfaceで，継承を要求しない．

```python
class MyTracker:
    def reset(self, config, seed): ...
    def step(self, timestamp_s, observations) -> TrackingFrame: ...
    def finalize(self) -> TrackingFrame | None: ...

class MyPlacement:
    def generate(self, environment, constraints, seed) -> CameraLayout: ...

class MyBehavior:
    def reset(self, config, seed): ...
    def step(self, timestamp_s, step_s, deer_states, local_environment): ...
```

Trackerの`step()`は観測数0でも毎simulation step呼び出す．配置法は`PlacementEnvironment`と`PlacementConstraints`のみを見る．行動モデルは現在の`GroundTruthState`と半径を明示した`LocalEnvironmentView`を受け取り，未来軌跡や無制限な全域餌分布を契約に含めない．

## Versioning

Phase 1の初期公開versionはpackage `0.1.0`，永続化Schema例は`1.0`とする．optional fieldの追加は後方互換として扱えるが，field削除・改名・意味変更はmajor schema version変更，Decision Record，移行手順を必要とする．

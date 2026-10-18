# Phase 0 調査・検証記録

調査日：2026-10-17（Asia/Tokyo）

## 実機環境

| 項目 | 確認結果 |
|---|---|
| Architecture | `aarch64` |
| Kernel | `5.15.199-tegra` |
| OS | Ubuntu 22.04.5 LTS |
| L4T | R36.5.2 |
| JetPack対応 | JetPack 6.2.3相当 |
| CUDA toolkit | 12.6 (`nvcc` 12.6.68) |
| Python | 3.10.12 |
| Docker | 29.7.2 |
| Docker Compose | v5.5.0 |
| NVIDIA Container Toolkit | 1.16.2 |
| NVIDIA Container Runtime | 1.16.2 |

`nvidia-l4t-core`と`nvidia-l4t-cuda`は`36.5.2-20260716114719`である．`nvidia-jetpack`メタパッケージは未導入だが，NVIDIAのJetPack ArchiveではL4T 36.5.2をJetPack 6.2.3としている．

ホストの`nvidia-smi`はJetsonでGPU確認に適さず，本環境ではNvRm初期化エラーになった．GPU確認はNVIDIA Runtimeで起動したコンテナ内からCUDA Runtime APIを使って行った．

## 既存リポジトリ

調査開始時に存在した通常ファイルは`AGENTS.md`だけであり，`docs/`，`docker/`，`requirements.txt`，`pyproject.toml`，`packages/`，`libs/`，`workspace/`，`cases/`は存在しなかった．したがって`field-tracker`，`field-campost`，`shepherd-contracts`を含む既存実装やPythonパッケージ定義，既存Dockerfile，Compose，依存定義は調査対象として存在しなかった．

`.git/`は空ディレクトリであり，`git status`は「not a git repository」となった．そのためGit履歴，追跡ファイル，未コミット差分の有無は確認できない．既存ファイルの削除・移動・上書きは行っていない．

## Dockerイメージ選定

x86は`nvidia/cuda:12.6.3-runtime-ubuntu22.04`を採用した．Jetson実機とCUDA 12.6，Ubuntu 22.04，Python 3.10を揃えつつ，GPU driverをホスト側に任せるためruntime imageを使う．PyTorchなどのGPU依存は互換性を個別確認してから追加する．

JetsonはNVIDIA公式`nvcr.io/nvidia/l4t-jetpack:r36.4.0`を採用した．2026-10-17時点でNGCの`l4t-jetpack`最新公開tagはr36.4.0で，L4T 36.5.2と完全一致するtagはない．公式Forumではr36.4.0をL4T 36.5ホストで使用した事例が報告されているため，実機ビルドとCUDA Runtime検証を条件に採用した．これは完全一致ではないため，将来r36.5.2対応tagが公開された場合は再評価する．

参照：

- NVIDIA JetPack Archive: <https://developer.nvidia.com/embedded/jetpack-archive>
- NVIDIA L4T JetPack NGC: <https://catalog.ngc.nvidia.com/orgs/nvidia/containers/l4t-jetpack>
- NVIDIA Container Toolkit install guide: <https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html>
- NVIDIA Jetson Orin Nano Docker setup: <https://docs.nvidia.com/jetson/orin-nano-devkit/user-guide/latest/setup_docker.html>

## 検証結果

| 検証 | 結果 |
|---|---|
| `bash -n docker/run.sh docker/run_l4t.sh` | 成功 |
| x86 Composeの`config`展開 | 成功 |
| L4T Composeの`config`展開 | 成功 |
| `docker/run_l4t.sh` build | 成功 |
| `docker/run_l4t.sh` detached run | 成功 |
| Runtime / device node | `nvidia`，`/dev/nvhost-gpu`と`/dev/nvmap`を確認 |
| CUDA Runtime | `cudaGetDeviceCount`がresult 0，device 1 |
| コンテナPython | 3.10.12 |
| 共通依存import | 成功 |
| pytest | 実行済み，テスト0件，終了コード5 |
| repository bind mount | `/workspace`へのmountを確認 |
| Caseホスト保存 | コンテナから`cases/`へ一時ファイルを書き，ホストで内容確認後に削除 |

共通importではNumPy，SciPy，pandas，Matplotlib，PyYAML，Pydantic，Shapely，Rasterio，GeoPandas，JupyterLab，pytestを確認した．パッケージ本体が未実装のため，`field-*`と`shepherd-contracts`のimportは実施できない．

## 未検証・制約

- x86_64 NVIDIA GPU環境がないため，x86 imageのbuild，run，GPU，importは未検証である．
- Git管理情報がないため，差分と未コミット状態はGitでは検証できない．
- Docker socketは`nobody:nogroup`所有で通常ユーザーから直接接続できなかった．検証時は承認された昇格実行を使用した．ホスト設定としてsocket ownershipとDocker group反映を確認する必要がある．
- PyTorch，TensorRT，Genesis，Rerun SDKはPhase 0の共通依存へ追加していない．
- Notebook，Case内容，各Pythonパッケージ，テストは未実装である．

## Phase 1前の確認事項

1. 共通Schemaの具体的なフィールド，serialization形式，versioning方針を承認する．
2. 座標参照系，軸方向，原点，時刻表現をCase契約として確定する．
3. Dataset内のTracker viewとEvaluator viewの物理分離方式を確定する．
4. 追跡・配置評価の指標，対応付け，欠測，集計式を確定する．
5. Jetson向けPyTorch/TensorRTの必要versionと導入元を実機互換性に基づき決定する．
6. 正常なGit metadataを用意し，Phase 0成果物をレビュー可能にする．
7. Docker socket ownershipを修正し，非rootユーザーで再検証する．


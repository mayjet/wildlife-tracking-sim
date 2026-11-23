# Wildlife Tracking Simulation

鹿の群れ追跡手法とカメラ配置手法を比較するためのシミュレーション・ベンチマーク基盤である．
実験条件はNotebookで作成し，長時間処理はPython Runnerから実行する．

## x86実験環境を構築する

この手順はx86_64 LinuxとNVIDIA GPUを搭載した実験マシンを対象とする．ホスト側の
NVIDIA Driver，Docker Engine，NVIDIA Container Toolkitは，マシンのOSとDriverに
適合する方法で事前に導入する．

### 1．リポジトリをcloneする

```bash
git clone git@github.com:mayjet/wildlife-tracking-sim.git
cd wildlife-tracking-sim
```

使用するcommitを確認する．

```bash
git rev-parse HEAD
```

`cases/`はGit管理外である．Case，Dataset，Runはclone後に別途`cases/`へ転送する．

### 2．GUIありで構築・起動する

Genesis GUIをブラウザから確認する場合は，GUIパッケージを含むImageをbuildする．
`VNC_PASSWORD`には実際の十分に長いパスワードを設定する．

```bash
VNC_PASSWORD='replace-with-a-long-password' \
INSTALL_GUI=1 \
GUI_ENABLED=1 \
docker/run.sh
```

このコマンドは次を行う．

- CUDA，PyTorch，Genesis，Rerun，Embreeをuv lockfileから導入する
- Xvfb，Openbox，x11vnc，noVNCを導入・起動する
- `wildlife-tracking-sim-x86`コンテナをバックグラウンド起動する
- noVNC，Rerunのポートを標準では`127.0.0.1`だけへ公開する

同じマシンのブラウザから次を開く．

```text
http://127.0.0.1:6080/vnc.html
```

別マシンのブラウザから閲覧する場合は，実験マシンへSSH port forwardingする．

```bash
ssh \
  -L 6080:127.0.0.1:6080 \
  -L 9090:127.0.0.1:9090 \
  <user>@<x86-host>
```

### 3．GUIなしで構築・起動する

GUIパッケージをImageへ含めない最小構成は次のとおりである．

```bash
INSTALL_GUI=0 GUI_ENABLED=0 docker/run.sh
```

GUI入りImageをbuildするが，今回のコンテナ起動ではGUIを動かさない場合は次を使う．

```bash
INSTALL_GUI=1 GUI_ENABLED=0 docker/run.sh
```

### 4．コンテナを確認する

```bash
docker ps --filter name=wildlife-tracking-sim-x86
docker logs wildlife-tracking-sim-x86
docker exec wildlife-tracking-sim-x86 python3 -c \
  'import embreex, genesis, rerun, torch; print(torch.cuda.is_available())'
```

コンテナへShellで入る場合は次を使う．

```bash
docker exec -it wildlife-tracking-sim-x86 bash
```

同名コンテナがすでに存在する場合，`docker/run.sh`は暗黙に削除・置換せず失敗する．
既存コンテナと保存結果を確認してから，利用者が明示的に停止・削除する．

### 5．Rerun Web Viewerを起動する

Rerunは実験Runnerとは別プロセスで起動する．

```bash
docker exec -d wildlife-tracking-sim-x86 \
  python3 workspace/run_experiments.py serve-rerun
```

ブラウザから次を開く．リモート環境では前述のSSH port forwardingを使用する．

```text
http://127.0.0.1:9090
```

## 依存管理

x86コンテナのPython依存は`pyproject.toml`と`uv.lock`を正本とする．Docker buildは
`uv sync --locked --extra x86 --no-editable`を使用し，宣言とlockfileが一致しない場合は
失敗する．`requirements.txt`はJetsonを含む既存環境との互換用に残している．

主な固定依存は次のとおりである．

- Python 3.10
- CUDA 12.8
- PyTorch 2.8.0 cu128
- Genesis 1.4.5
- Rerun SDK 0.22.1
- Embree 4.4.0
- NumPy 1.26.4

詳細は[`docs/x86-experiment-environment.md`](docs/x86-experiment-environment.md)を参照する．

## 実験の入口

- `workspace/04_simulation.ipynb`：配置，Waypoint，ルート，群れ設定，実験計画の保存
- `workspace/run_experiments.py`：Dataset生成からTracker，評価，記録までの一括実行
- `workspace/05_benchmark.ipynb`：保存済み結果の読込，表，グラフ，スコア確認
- Rerun Web Viewer：2Dライブ表示と`.rrd`再生
- Genesis：保存済みGround Truthの3D表示

実験計画とRunnerの操作方法は[`workspace/README.md`](workspace/README.md)を参照する．

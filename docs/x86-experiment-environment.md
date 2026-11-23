# x86実験環境

RTX搭載x86_64マシンでは，`docker/Dockerfile`と`docker/run.sh`を使用する．
CaseはGit管理外であり，clone後に別途`cases/`へ転送する．

## 前提

- x86_64 Linux
- NVIDIA Driver
- Docker Engine
- NVIDIA Container Toolkit
- RTX 2080 SUPERまたは互換CUDA GPU

コンテナはGenesis 1.4.5の依存に合わせてCUDA 12.8とPyTorch 2.8.0 cu128を使用する．
ホストDriverがCUDA 12.8コンテナを起動できることを，build前に確認する．

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.8.1-runtime-ubuntu22.04 nvidia-smi
```

## GUIあり

noVNCを含むImageをbuildし，仮想デスクトップを起動する．標準ではWebポートを
`127.0.0.1`だけへ公開するため，リモートからはSSH port forwardingを使用する．

```bash
VNC_PASSWORD='replace-this-password' \
INSTALL_GUI=1 \
GUI_ENABLED=1 \
docker/run.sh
```

ローカルブラウザで`http://127.0.0.1:6080/vnc.html`を開く．別端末から接続する場合は，
ローカル側で次のように転送する．

```bash
ssh -L 6080:127.0.0.1:6080 -L 9090:127.0.0.1:9090 <user>@<x86-host>
```

## GUIなし

GUIパッケージをImageへ入れず，実験Runner用の最小構成にする．

```bash
INSTALL_GUI=0 GUI_ENABLED=0 docker/run.sh
```

同じGUI入りImageを利用し，起動時だけGUIを無効にすることもできる．

```bash
INSTALL_GUI=1 GUI_ENABLED=0 docker/run.sh
```

## uv依存管理

ルート`pyproject.toml`と`uv.lock`を正本とする．x86 Imageはuv本体も固定し，
`uv sync --locked --extra x86 --no-editable`で環境を作成する．lockfileと宣言が
一致しない場合はDocker buildを失敗させる．

依存を変更する場合だけ，リポジトリのルートで次を実行してlockfileを更新する．

```bash
uv lock
uv lock --check
```

`x86` extraにはGenesis，CUDA版PyTorch，Rerun，Embreeを固定している．Embreeは
x86で利用可能にするが，現時点の正式可視判定は`AnalyticRaycastBackend`のままであり，
Backendを暗黙に変更しない．

## 起動後の確認

```bash
docker exec wildlife-tracking-sim-x86 nvidia-smi
docker exec wildlife-tracking-sim-x86 python3 -c \
  'import embreex, genesis, rerun, torch; print(torch.cuda.is_available())'
docker exec wildlife-tracking-sim-x86 pytest -q
```

Rerun Web Viewerは実験Runnerとは別プロセスで起動する．

```bash
docker exec -d wildlife-tracking-sim-x86 \
  python3 workspace/run_experiments.py serve-rerun
```

Genesis GUIを使用するコマンドには`--genesis-viewer --genesis-backend cuda`を付ける．
数値結果はParquetを正本とし，GUIまたはRerunが停止しても既存結果を削除しない．

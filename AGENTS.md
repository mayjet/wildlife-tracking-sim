# AGENTS.md — Wildlife Tracking Simulation

## Project

本リポジトリは，鹿の追跡手法とカメラ配置手法を比較するためのシミュレーション・ベンチマーク基盤である．

研究者は主に `workspace/` で実験を操作し，研究用アルゴリズムを開発する．

## Architecture

- `workspace/`：Notebook，追跡・予測手法，カメラ配置手法，鹿の行動モデル，実験設定
- `packages/`：共通ライブラリ．通常のアルゴリズム開発では変更しない
- `libs/`：共有Schemaとデータ型
- `cases/`：Case，Dataset，Runの保存
- `docker/`：x86 NVIDIA GPUとJetson L4TのDocker環境
- `docs/`：要件，設計，評価仕様，開発計画

## Development rules

1. 作業前に関連する `docs/` を確認する．
2. 指定されたPhaseの範囲のみを実装する．
3. 既存ファイルや未コミット変更を無断で削除・上書きしない．
4. 共通API・Schemaの互換性を維持する．
5. 追跡・配置・行動モデルは交換可能にする．
6. `workspace/` の研究用手法からSimulator・Evaluatorの内部実装を変更しない．
7. Notebookにはアルゴリズム本体を重複実装しない．
8. 重要な計算式・座標変換・評価処理に対してテストを作成する．
9. 同一設定とseedで再現可能な結果を生成する．
10. 仕様変更が必要な場合は，実装前に変更理由と影響範囲を提示する．

## Ground Truth isolation

- Ground TruthはSimulatorとEvaluatorのみが使用する．
- Trackerへ真の個体ID・群れID・リーダー情報・未来位置を渡さない．
- Trackerは観測された個体の情報だけを使用する．
- 観測できない時刻も予測処理を継続できる設計とする．
- 観測モデルはPerfect Observationのみとする．Noisy Observationを追加しない．

## Docker

- `docker/Dockerfile`：x86 NVIDIA GPU
- `docker/Dockerfile.l4t`：Jetson Orin Nano
- `docker/run.sh`：x86のbuild・run
- `docker/run_l4t.sh`：Jetsonのbuild・run
- Compose YAMLは補助的な手段とする．
- 共通Python依存はルートの `requirements.txt` に集約する．
- 環境固有の依存は各Dockerfileで扱う．
- コンテナ内の作業ディレクトリは `/workspace` とする．
- 既存コンテナを自動的に停止・削除しない．

## Validation and reporting

各Phaseの完了時には，以下を報告する．

- 変更したファイル
- 実装した機能と未実装の機能
- 実行したテストと結果
- 既存APIへの影響
- 残る課題・未確定事項

Phase完了後は次のPhaseに自動的に進まない．研究者のレビューを受けること．
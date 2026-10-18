# 開発計画

## Phase 0：環境・設計基盤

Docker環境，共通Python依存，ディレクトリ責務，要求，契約，評価仕様，拡張点を整備する．パッケージ・Notebook・Caseの本実装は行わない．Jetson実機検証とx86検証は環境ごとに結果を記録する．本Phase完了後はレビューを待ち，自動的に次Phaseへ進まない．

## Phase 1：契約と最小骨格

`shepherd-contracts`にSchemaと交換可能APIを実装した．座標・時刻・serialization・Ground Truth分離をテストする．各`field-*`パッケージ，Notebook，アルゴリズムの本体は未実装であり，Phase 1レビュー後まで着手しない．

## Phase 2候補：環境と解析backend

Case loader，2D/3D座標変換，人工地形・森林・建物・牧場境界，`AnalyticBackend`の基礎を実装する．具体Caseは別途承認された実験条件に基づく．

## Phase 3候補：行動・観測・Dataset

リーダー主導の群れ行動，障害物制約，Perfect Observation，可視判定，Dataset生成・再利用を実装する．Noisy Observationは対象外とする．

## Phase 4候補：追跡・配置・評価

共通Trackerと配置API，基準手法，追跡評価，配置評価を実装する．研究手法は`workspace/`に置き，共通API経由で実行する．

## Phase 5候補：可視化と任意backend

Rerun Web 2D表示を実装し，必要性とJetson互換性を確認後に`GenesisBackend`を任意機能として検討する．Camera Geometryも別Decision Recordで扱う．

## 各Phaseの完了基準

変更ファイル，実装・未実装機能，実行したテストと結果，既存APIへの影響，未解決事項を報告する．仕様変更は実装前に理由・影響・移行方針を提示し，研究者のレビューを受ける．

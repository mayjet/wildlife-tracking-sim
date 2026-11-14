# 研究用鹿ルート

標準の`smooth`と`meandering`以外の詳細ルート生成器を置く．Waypointは事前確定ルートの入力方式であり，探索・状態依存行動とは分離する．

1. `<method>.py`へ`generate(environment_case, definition, waypoint_set)`を定義する．
2. 検証済みの`ResolvedRoute`を返す．
3. Notebookの`route_methods`へ`"<method>"`を追加する．
4. 固有設定はNotebookの`route_settings["<method>"]`へ書く．

方式名とPythonファイル名は一致させる．YAMLとmodule名はNotebookが自動生成する．Waypoint，詳細ルート，時刻付きTrajectoryは混在させず，変更時は新しい`configuration_version`を使う．

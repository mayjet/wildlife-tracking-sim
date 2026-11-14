# 研究用カメラ配置

標準の`grid40`と`uniform`以外の配置生成器を置く．

1. `<method>.py`へ`generate(environment_case, definition)`を定義する．
2. `ObservationPointLayout`を返し，`layout_id`は宣言値と一致させる．
3. Notebookの`camera_placements`へ`("<method>", 値)`を追加する．
4. 値は`definition.parameters["value"]`から取得する．

方式名とPythonファイル名は一致させる．YAMLとmodule名はNotebookが自動生成する．既存配置を変更する場合は上書きせず，新しい`configuration_version`を使う．

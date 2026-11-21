# 追跡手法の追加

標準手法は`last_observation`と`constant_velocity`である．研究用手法はこのフォルダへPython moduleとして追加する．

1. `workspace/tracking/my_tracker.py`を作る．
2. `shepherd_contracts.Tracker`の`reset`，`step`，`finalize`を実装する．
3. 引数なしの`create_tracker()`からTracker instanceを返す．
4. Notebookの`tracker_methods`へ`"my_tracker"`を追加する．

Trackerへ渡される入力は`ObservationFrame`だけであり，Ground Truthを参照してはならない．真値との比較は`field-benchmark`だけが行う．


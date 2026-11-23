from __future__ import annotations

from pathlib import Path

from field_visualizer import RerunLiveSession


class FakeRecording:
    def __init__(self, application_id, recording_id):
        self.application_id = application_id
        self.recording_id = recording_id
        self.saved_path = None
        self.grpc_url = None
        self.flushed = False
        self.disconnected = False

    def flush(self):
        self.flushed = True

    def disconnect(self):
        self.disconnected = True


class FakeRerun:
    recordings = []

    @classmethod
    def new_recording(cls, application_id, recording_id):
        recording = FakeRecording(application_id, recording_id)
        cls.recordings.append(recording)
        return recording

    @staticmethod
    def save(path, recording):
        recording.saved_path = str(path)

    @staticmethod
    def connect(url, recording):
        recording.grpc_url = url


def test_live_session_uses_file_and_grpc_sinks(tmp_path: Path) -> None:
    FakeRerun.recordings = []
    session = RerunLiveSession(
        run_id="run-1",
        recording_path=tmp_path / "recording.rrd",
        grpc_url="127.0.0.1:9876",
        rerun_module=FakeRerun,
    )
    assert len(session.recordings) == 2
    assert session.recordings[0].saved_path == str(tmp_path / "recording.rrd")
    assert session.recordings[1].grpc_url == "127.0.0.1:9876"
    session.close()
    assert all(recording.flushed for recording in session.recordings)
    assert all(recording.disconnected for recording in session.recordings)


def test_live_session_keeps_file_recording_when_web_server_is_down(tmp_path: Path) -> None:
    class FailingLiveRerun(FakeRerun):
        @staticmethod
        def connect(url, recording):
            raise ConnectionError("server unavailable")

    FailingLiveRerun.recordings = []
    session = RerunLiveSession(
        run_id="run-1",
        recording_path=tmp_path / "recording.rrd",
        grpc_url="127.0.0.1:9876",
        rerun_module=FailingLiveRerun,
    )
    assert len(session.recordings) == 1
    assert session.recordings[0].saved_path == str(tmp_path / "recording.rrd")
    assert "live connection failed" in session.warnings[0]

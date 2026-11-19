import pytest


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    for name in [
        "APP_PASSWORD_FILE",
        "SQL_HOST",
        "MQTT_HOST",
        "LANDING_DIR",
        "PROFILE_KEY_FILE",
        "FILE_ALLOWED_ROOTS",
        "SQLITE_ROOT",
    ]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("APP_PASSWORD", raising=False)


class Context:
    run_id = "test-job"
    outputs = []

    def __init__(self):
        self.stats = {}
        self.outputs = []

    def check(self):
        pass

    def wait(self, ms):
        pass

    def progress(self, **values):
        for k, v in values.items():
            self.stats[k] = self.stats.get(k, 0) + v

    def pace(self, completed):
        pass

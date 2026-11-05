import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fake_plex  # noqa: E402

fake_plex.install()

import app as plex_rename  # noqa: E402


@pytest.fixture
def app_module(tmp_path):
    """Приложение с чистым состоянием: планы и задачи между тестами не
    текут, а журнал пишется во временную папку вместо /app/logs."""
    plex_rename.LOG_DIR = str(tmp_path / "logs")
    plex_rename.PLANS.clear()
    plex_rename.JOBS.clear()
    fake_plex.SECTIONS.clear()
    yield plex_rename
    plex_rename.PLANS.clear()
    plex_rename.JOBS.clear()
    fake_plex.SECTIONS.clear()


@pytest.fixture
def client(app_module):
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


@pytest.fixture
def library(tmp_path):
    """Пустая библиотека в временной папке. Тест наполняет её сам."""
    def _make(movies, name="Кино"):
        fake_plex.SECTIONS[name] = fake_plex.FakeSection(movies)
        return fake_plex.SECTIONS[name]
    return _make


@pytest.fixture
def mkfile(tmp_path):
    def _make(name, content="video"):
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        return str(path)
    return _make

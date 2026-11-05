"""
Заглушка plexapi для тестов.

Приложение обращается к Plex только через `PlexServer`, поэтому тесты
подставляют вместо него этот модуль: ни сети, ни живого сервера, ни
токена не требуется. Объекты повторяют ровно те поля, которые читает
`app.py` — title, year, media[].parts[].file, guids, guid, originalTitle.
"""
import sys
import types

# Сюда тест кладёт библиотеку: SECTIONS["Кино"] = make_section([...])
SECTIONS = {}


class FakeGuid:
    def __init__(self, guid_id):
        self.id = guid_id


class FakePart:
    def __init__(self, path):
        self.file = path


class FakeMedia:
    def __init__(self, paths, video_codec="hevc", audio_codec="dts",
                 resolution="1080", audio_channels=6):
        self.parts = [FakePart(p) for p in paths]
        self.videoCodec = video_codec
        self.audioCodec = audio_codec
        self.videoResolution = resolution
        self.audioChannels = audio_channels


class FakeMovie:
    def __init__(self, title, year, paths, guids=(), original_title=None,
                 legacy_guid="", **media_kwargs):
        self.title = title
        self.year = year
        self.media = [FakeMedia(paths, **media_kwargs)]
        self.guids = [FakeGuid(g) for g in guids]
        self.guid = legacy_guid
        self.originalTitle = original_title
        self.reloaded = False

    def reload(self):
        self.reloaded = True


class FakeSection:
    """Библиотека Plex. `updated` показывает, запросили ли пересканирование."""

    def __init__(self, movies):
        self.movies = movies
        self.updated = False

    def all(self):
        return self.movies

    def search(self, title=None):
        return [m for m in self.movies if title and title in m.title]

    def update(self):
        self.updated = True


class FakePlexServer:
    def __init__(self, url, token):
        self.url = url
        self.token = token
        self.library = types.SimpleNamespace(section=lambda name: SECTIONS[name])


def install():
    """Регистрирует заглушку в sys.modules до импорта app.py."""
    plexapi = types.ModuleType("plexapi")
    server = types.ModuleType("plexapi.server")
    server.PlexServer = FakePlexServer
    plexapi.server = server
    sys.modules.setdefault("plexapi", plexapi)
    sys.modules.setdefault("plexapi.server", server)

# -*- coding: utf-8 -*-
"""
Тесты Plex Rename.

Главное, что они стерегут, — сохранность файлов. Каждая проверка ниже
соответствует ошибке, которая однажды уже могла стоить данных или
закрепить неверный ID в имени файла навсегда.
"""
import os
import time

from fake_plex import FakeMovie

TPL = "{title_full} ({year}) - {resolution} [{video_codec}][{audio_codec} {audio_channels}]{edition} {{{ext_ref}}}"


def _дождаться(задача, предел=10.0):
    """Переименование идёт в отдельном потоке — ждём его завершения."""
    крайний_срок = time.monotonic() + предел
    while задача["running"] and time.monotonic() < крайний_срок:
        time.sleep(0.02)
    return задача


# --- имя файла -------------------------------------------------------

def test_имя_укладывается_в_предел_файловой_системы(app_module):
    длинное = "Очень длинное название фильма " * 20
    имя = app_module.fit_name(длинное + " {tmdb-999}", ".mkv")
    assert len((имя + ".mkv").encode("utf-8")) <= app_module.MAX_NAME_BYTES


def test_при_обрезке_сохраняется_id(app_module):
    """ID в конце имени — то, по чему Plex принудительно сопоставляет
    файл с карточкой. Обрезать имя с конца нельзя."""
    имя = app_module.fit_name("Ы" * 300 + " {tmdb-12345}", ".mkv")
    assert имя.endswith("{tmdb-12345}")


def test_короткое_имя_не_трогается(app_module):
    assert app_module.fit_name("Фильм {tmdb-1}", ".mkv") == "Фильм {tmdb-1}"


def test_запрещённые_символы_вычищаются(app_module):
    assert app_module.safe_filename('Фильм: часть 2/3 <тест>') == "Фильм часть 23 тест"


def test_неизвестный_плейсхолдер_даёт_понятную_ошибку(app_module):
    movie = FakeMovie("Фильм", 2000, ["/нет.mkv"], ["tmdb://1"])
    try:
        app_module.build_new_name(movie, "{нет_такого}", "tmdb-1")
    except ValueError as e:
        assert "нет_такого" in str(e)
    else:
        raise AssertionError("ожидалась ValueError")


# --- внешние ID ------------------------------------------------------

def test_tmdb_предпочтительнее_imdb(app_module):
    movie = FakeMovie("Ф", 2000, ["/f.mkv"], ["imdb://tt1", "tmdb://278"])
    ref, спорные = app_module.get_external_ref(movie)
    assert ref == "tmdb-278" and спорные is None


def test_несколько_tmdb_считаются_спорными(app_module):
    """Plex не стирает прежний ID при пересопоставлении: после Fix Match
    старый tmdb:// остаётся рядом с новым. Брать первый попавшийся
    нельзя — он может указывать на другой фильм."""
    movie = FakeMovie("Ф", 2000, ["/f.mkv"], ["tmdb://111", "tmdb://222"])
    ref, спорные = app_module.get_external_ref(movie)
    assert ref == "tmdb-111"
    assert спорные == ["tmdb-111", "tmdb-222"]


def test_повтор_одного_id_не_считается_спорным(app_module):
    movie = FakeMovie("Ф", 2000, ["/f.mkv"], ["tmdb://111", "tmdb://111"])
    _, спорные = app_module.get_external_ref(movie)
    assert спорные is None


def test_основной_guid_важнее_накопившегося_списка(app_module):
    """Plex не стирает прежние номера из guids, зато основной guid
    всегда отражает текущее сопоставление — ему и верим."""
    movie = FakeMovie("Ф", 2000, ["/f.mkv"], ["tmdb://37724", "tmdb://700"],
                      legacy_guid="tv.plex.agents.custom.kinoplex.poiskkino://movie/tmdb-700")
    ref, спорные = app_module.get_external_ref(movie)
    assert ref == "tmdb-700"
    assert спорные is None


def test_номер_берётся_из_имени_файла(app_module):
    """Когда карточка номера не называет, его подсказывает имя файла —
    туда его записал тот, кто опознал саму раздачу."""
    movie = FakeMovie("Ф", 2000, ["/f.mkv"], ["tmdb://111", "tmdb://222"],
                      legacy_guid="poiskkino://movie/596489")
    ref, спорные = app_module.get_external_ref(
        movie, "Whiplash (2014) - 1080 [HEVC][AC3 5.1] {tmdb-244786}.mkv")
    assert ref == "tmdb-244786"
    assert спорные is None


def test_карточка_и_имя_файла_противоречат(app_module):
    """Вот это и есть настоящий спор: номер не выдаётся вовсе, файл
    переименовывать нельзя, пока человек не разберётся."""
    movie = FakeMovie("Ф", 2000, ["/f.mkv"], ["tmdb://176"],
                      legacy_guid="poiskkino://movie/tmdb-176")
    ref, спорные = app_module.get_external_ref(
        movie, "Saw (2003) - 2160 [HEVC][AC3 5.1] {tmdb-246355}.mkv")
    assert ref is None
    assert спорные == ["tmdb-176", "tmdb-246355"]


def test_совпадение_карточки_и_имени_не_спор(app_module):
    movie = FakeMovie("Ф", 2000, ["/f.mkv"], ["tmdb://31165", "tmdb://466272"],
                      legacy_guid="poiskkino://movie/tmdb-31165")
    ref, спорные = app_module.get_external_ref(movie, "кино {tmdb-31165}.mkv")
    assert ref == "tmdb-31165" and спорные is None


def test_спорная_карточка_не_уходит_в_без_tmdb(app_module, library, mkfile):
    """Проверка спора идёт раньше проверки «номера нет»: иначе такие
    карточки попадали бы не в ту вкладку."""
    f = mkfile("Saw (2003) {tmdb-246355}.mkv")
    library([FakeMovie("Пила", 2004, [f], ["tmdb://176"],
                       legacy_guid="poiskkino://movie/tmdb-176")])
    план, _, без_id, спорные, _ = app_module.compute_plan("u", "t", "Кино", TPL)
    assert план == []
    assert без_id == []
    assert len(спорные) == 1 and "tmdb-246355" in спорные[0]["ids"]


def test_кинопоиск_из_старого_guid(app_module):
    movie = FakeMovie("Ф", 2000, ["/f.mkv"], [],
                      legacy_guid="tv.plex.agents.custom.kinoplex.poiskkino://movie/326")
    ref, _ = app_module.get_external_ref(movie)
    assert ref == "kp-326"


def test_без_сопоставления_возвращается_пусто(app_module):
    movie = FakeMovie("Ф", 2000, ["/f.mkv"], [])
    assert app_module.get_external_ref(movie) == (None, None)


# --- план ------------------------------------------------------------

def test_занятое_целевое_имя_не_перезаписывается(app_module, library, mkfile, tmp_path):
    """os.rename на Linux затирает цель молча. Файл, которого нет в
    плане, прежде исчезал без следа и без строки в журнале."""
    источник = mkfile("случайное.имя.mkv")
    movie = FakeMovie("Занято", 1999, [источник], ["tmdb://777"])
    цель = os.path.join(str(tmp_path),
                        app_module.fit_name(app_module.build_new_name(movie, TPL, "tmdb-777"), ".mkv") + ".mkv")
    with open(цель, "w", encoding="utf-8") as f:
        f.write("важные данные")

    library([movie])
    план, конфликты, _, _, _ = app_module.compute_plan("u", "t", "Кино", TPL)

    assert план == []
    assert any("занято другим" in c["reason"] for c in конфликты)
    with open(цель, encoding="utf-8") as f:
        assert f.read() == "важные данные"


def test_два_файла_с_одним_именем_уходят_в_конфликты(app_module, library, mkfile):
    a, b = mkfile("a.mkv"), mkfile("b.mkv")
    library([FakeMovie("Двойник", 2000, [a], ["tmdb://501"]),
             FakeMovie("Двойник", 2000, [b], ["tmdb://501"])])
    план, конфликты, _, _, _ = app_module.compute_plan("u", "t", "Кино", TPL)
    assert план == []
    assert конфликты and конфликты[0]["reason"].startswith("несколько файлов")


def test_многочастевой_фильм_нумеруется(app_module, library, mkfile):
    части = [mkfile("серия1.mkv"), mkfile("серия2.mkv")]
    library([FakeMovie("Война и мир", 1967, части, ["tmdb://888"])])
    план, конфликты, _, _, _ = app_module.compute_plan("u", "t", "Кино", TPL)
    имена = sorted(os.path.basename(i["new_path"]) for i in план)
    assert конфликты == []
    assert имена[0].endswith(" - pt1.mkv") and имена[1].endswith(" - pt2.mkv")


def test_фильм_без_id_попадает_в_отдельный_список(app_module, library, mkfile):
    library([FakeMovie("Безымянный", 2011, [mkfile("нет.mkv")], [])])
    план, _, без_id, спорные, _ = app_module.compute_plan("u", "t", "Кино", TPL)
    assert план == [] and спорные == []
    assert без_id[0]["file"] == "нет.mkv"


def test_спорный_id_не_переименовывается(app_module, library, mkfile):
    library([FakeMovie("Спорный", 2010, [mkfile("спорный.mkv")], ["tmdb://111", "tmdb://222"])])
    план, _, без_id, спорные, _ = app_module.compute_plan("u", "t", "Кино", TPL)
    assert план == [] and без_id == []
    assert спорные[0]["ids"] == "tmdb-111, tmdb-222"


def test_повторный_запуск_ничего_не_делает(app_module, library, tmp_path):
    """Идемпотентность: файл с правильным именем попадает в «уже в
    порядке», а не переименовывается заново."""
    movie = FakeMovie("Фильм", 2000, ["заглушка"], ["tmdb://5"])
    правильное = app_module.fit_name(app_module.build_new_name(movie, TPL, "tmdb-5"), ".mkv") + ".mkv"
    путь = tmp_path / правильное
    путь.write_text("video", encoding="utf-8")
    movie.media[0].parts[0].file = str(путь)

    library([movie])
    план, _, _, _, уже_в_порядке = app_module.compute_plan("u", "t", "Кино", TPL)
    assert план == [] and уже_в_порядке == 1


# --- маршруты --------------------------------------------------------

def test_применение_без_номера_плана_отклоняется(client):
    ответ = client.post("/apply", data={})
    assert "устарел".encode() in ответ.data


def test_применение_с_чужим_номером_плана_отклоняется(client):
    ответ = client.post("/apply", data={"plan_id": "11111111-1111-1111-1111-111111111111"})
    assert "устарел".encode() in ответ.data


def test_имя_файла_не_выполняется_как_код(client, library, mkfile):
    """Имена приходят с торрентов. Раньше они выводились через |safe, и
    файл с именем-скриптом выполнялся на странице, где лежит токен."""
    опасное = "<img src=x onerror=alert(1)>.mkv"
    a, b = mkfile(опасное), mkfile("второй.mkv")
    library([FakeMovie("Двойник", 2000, [a], ["tmdb://501"]),
             FakeMovie("Двойник", 2000, [b], ["tmdb://501"])])
    ответ = client.post("/preview", data={"plex_url": "u", "plex_token": "t",
                                          "library_name": "Кино", "template": TPL})
    тело = ответ.data.decode()
    assert "<img src=x onerror=" not in тело
    assert "&lt;img src=x onerror=" in тело


def test_токен_не_дублируется_в_скрытые_поля(client, library, mkfile):
    library([FakeMovie("Фильм", 2000, [mkfile("ф.mkv")], ["tmdb://1"])])
    ответ = client.post("/preview", data={"plex_url": "u", "plex_token": "секретный-токен",
                                          "library_name": "Кино", "template": TPL})
    assert ответ.data.decode().count("секретный-токен") == 1


def test_полный_цикл_превью_и_применения(client, app_module, library, mkfile, tmp_path):
    старый = mkfile("мусорное.имя.1080p.mkv")
    секция = library([FakeMovie("Побег из Шоушенка", 1994, [старый], ["tmdb://278"],
                                original_title="The Shawshank Redemption")])

    ответ = client.post("/preview", data={"plex_url": "u", "plex_token": "t",
                                          "library_name": "Кино", "template": TPL})
    тело = ответ.data.decode()
    номер = тело.split('name="plan_id" value="')[1].split('"')[0]
    assert номер

    client.post("/apply", data={"plan_id": номер})
    _дождаться(next(iter(app_module.JOBS.values())))

    assert not os.path.exists(старый)
    новые = [f for f in os.listdir(str(tmp_path)) if f.endswith(".mkv")]
    assert новые == ["Побег из Шоушенка (The Shawshank Redemption) (1994) - 1080 [HEVC][DTS 5.1] {tmdb-278}.mkv"]
    assert секция.updated, "библиотека Plex не обновлена после переименования"


def test_недоступный_журнал_не_отменяет_переименование(client, app_module, library, mkfile, tmp_path):
    """Раньше ошибка на создании каталога журнала убивала поток целиком:
    файлы оставались нетронутыми, а прогресс-бар застывал навсегда."""
    # Каталог внутри обычного файла создать нельзя никакими правами —
    # это надёжнее, чем несуществующий путь, который root просто создаст.
    преграда = tmp_path / "это_файл_а_не_каталог"
    преграда.write_text("x", encoding="utf-8")
    app_module.LOG_DIR = str(преграда / "logs")
    старый = mkfile("мусор.mkv")
    library([FakeMovie("Фильм", 2000, [старый], ["tmdb://1"])])

    тело = client.post("/preview", data={"plex_url": "u", "plex_token": "t",
                                         "library_name": "Кино", "template": TPL}).data.decode()
    номер = тело.split('name="plan_id" value="')[1].split('"')[0]
    client.post("/apply", data={"plan_id": номер})

    задача = next(iter(app_module.JOBS.values()))
    _дождаться(задача)
    assert not задача["running"], "задача не завершилась"
    assert not os.path.exists(старый), "файл не переименован"
    assert any("Журнал на диск не пишется" in l for l in задача["log"])


def test_один_план_применяется_один_раз(client, app_module, library, mkfile):
    library([FakeMovie("Фильм", 2000, [mkfile("ф.mkv")], ["tmdb://1"])])
    тело = client.post("/preview", data={"plex_url": "u", "plex_token": "t",
                                         "library_name": "Кино", "template": TPL}).data.decode()
    номер = тело.split('name="plan_id" value="')[1].split('"')[0]
    client.post("/apply", data={"plan_id": номер})
    повтор = client.post("/apply", data={"plan_id": номер})
    assert "устарел".encode() in повтор.data

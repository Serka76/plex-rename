"""
Переименование фильмов по данным Plex — веб-приложение с боковым меню.
Автор интерфейса/оформления: Sergey Sychev.

Функционально не отличается от предыдущей версии, изменён только UI:
- боковая навигация вместо длинной страницы со скроллом
- счётчики видны сразу (sticky-панель)
- вкладки: Настройка / Превью / Конфликты / Без TMDB / Журнал
"""

import os
import re
import threading
import time
import uuid
from datetime import datetime

from flask import Flask, request, render_template_string, jsonify

try:
    from plexapi.server import PlexServer
except ImportError:
    PlexServer = None

app = Flask(__name__)

VERSION = "1.7.2"
STARTED_AT = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

LAST_PLAN = []
LAST_CONFLICTS = []
LAST_UNMATCHED = []
LAST_ALREADY_OK = 0

JOBS = {}
LOG_DIR = "/app/logs"

DEFAULT_TEMPLATE = "{title_full} ({year}) - {resolution} [{video_codec}][{audio_codec} {audio_channels}]{edition} {{{ext_ref}}}"

PAGE = """
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Переименование фильмов — Plex Rename</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #0a0c10;
    --surface: #12151a;
    --surface-raised: #181c22;
    --line: #232830;
    --text-hi: #ecedf1;
    --text-lo: #868d97;
    --accent: #2fd4c0;
    --accent-dim: #1a3a37;
    --danger: #f0554a;
    --danger-dim: #3a1c19;
    --warn: #f5a623;
    --warn-dim: #3a2c10;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text-hi);
    font-family: 'Space Grotesk', sans-serif;
    display: flex; min-height: 100vh;
  }
  code, .mono, input, .filename { font-family: 'JetBrains Mono', monospace; }

  nav.rail {
    width: 232px; flex-shrink: 0; background: var(--surface);
    border-right: 1px solid var(--line); padding: 20px 12px;
    display: flex; flex-direction: column; gap: 4px;
  }
  .brand { padding: 4px 10px 20px; }
  .brand .mark { color: var(--accent); font-size: 13px; letter-spacing: .12em; font-weight: 600; }
  .brand .title { font-size: 16px; font-weight: 700; margin-top: 4px; }
  .navitem {
    display: flex; align-items: center; gap: 10px; padding: 10px 10px;
    border-radius: 8px; cursor: pointer; color: var(--text-lo); font-size: 14px; font-weight: 500;
    border: 1px solid transparent; user-select: none;
  }
  .navitem:hover { background: var(--surface-raised); color: var(--text-hi); }
  .navitem.active { background: var(--accent-dim); color: var(--accent); border-color: rgba(47,212,192,.25); }
  .navitem svg { width: 16px; height: 16px; flex-shrink: 0; }
  .navitem .badge {
    margin-left: auto; font-size: 11px; font-family: 'JetBrains Mono', monospace;
    background: var(--line); color: var(--text-lo); padding: 1px 7px; border-radius: 20px;
  }
  .navitem .badge.warn { background: var(--warn-dim); color: var(--warn); }
  .navitem .badge.danger { background: var(--danger-dim); color: var(--danger); }
  .navitem .badge.ok { background: var(--accent-dim); color: var(--accent); }
  .rail-footer { margin-top: auto; padding: 10px; font-size: 11px; color: var(--text-lo); line-height: 1.7; border-top: 1px solid var(--line); }
  .rail-footer .ver { color: var(--accent); font-family: 'JetBrains Mono', monospace; font-weight: 600; }

  main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
  .statbar {
    display: flex; gap: 0; border-bottom: 1px solid var(--line); background: var(--surface);
    position: sticky; top: 0; z-index: 5;
  }
  .stat { padding: 14px 22px; border-right: 1px solid var(--line); }
  .stat .num { font-family: 'JetBrains Mono', monospace; font-size: 20px; font-weight: 600; }
  .stat .lbl { font-size: 11px; color: var(--text-lo); text-transform: uppercase; letter-spacing: .06em; margin-top: 2px; }
  .stat.accent .num { color: var(--accent); }
  .stat.warn .num { color: var(--warn); }
  .stat.danger .num { color: var(--danger); }

  .panel { display: none; padding: 28px 32px; overflow-y: auto; }
  .panel.active { display: block; }
  h1 { font-size: 18px; margin: 0 0 4px; }
  .sub { color: var(--text-lo); font-size: 13px; margin: 0 0 22px; max-width: 640px; line-height: 1.5; }

  label { display: block; margin-top: 16px; font-size: 12px; color: var(--text-lo); text-transform: uppercase; letter-spacing: .04em; }
  input[type=text] {
    width: 100%; max-width: 620px; padding: 10px 12px; border-radius: 8px; border: 1px solid var(--line);
    background: var(--surface-raised); color: var(--text-hi); font-size: 13px; margin-top: 6px;
  }
  input[type=text]:focus { outline: none; border-color: var(--accent); }
  .hint { font-size: 11px; color: var(--text-lo); margin-top: 6px; max-width: 620px; line-height: 1.5; }

  button {
    margin-top: 20px; padding: 11px 20px; border-radius: 8px; border: none;
    font-family: 'Space Grotesk', sans-serif; font-weight: 600; font-size: 13px; cursor: pointer;
  }
  .btn-primary { background: var(--accent); color: #06110f; }
  .btn-danger { background: var(--danger); color: #1a0908; }
  .btn-primary:hover, .btn-danger:hover { filter: brightness(1.08); }

  .msg { padding: 12px 14px; border-radius: 8px; font-size: 13px; margin-bottom: 18px; max-width: 640px; }
  .msg-ok { background: var(--accent-dim); color: var(--accent); }
  .msg-err { background: var(--danger-dim); color: var(--danger); }

  .diffrow {
    display: flex; align-items: stretch; margin-bottom: 8px; border-radius: 8px; overflow: hidden;
    border: 1px solid var(--line); background: var(--surface);
  }
  .diffrow .bar { width: 3px; flex-shrink: 0; }
  .diffrow .bar.old { background: var(--danger); }
  .diffrow .lines { padding: 8px 12px; flex: 1; min-width: 0; }
  .diffrow .filename { font-size: 12.5px; word-break: break-all; }
  .diffrow .filename.old { color: #c9857e; text-decoration: line-through; text-decoration-color: rgba(240,85,74,.4); }
  .diffrow .filename.new { color: var(--accent); margin-top: 4px; }

  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  td, th { border-bottom: 1px solid var(--line); padding: 8px 6px; text-align: left; }
  th { color: var(--text-lo); font-weight: 500; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }

  .empty { color: var(--text-lo); font-size: 13px; padding: 40px 0; text-align: center; }

  #progress-bar-bg { background: var(--surface-raised); border-radius: 8px; overflow: hidden; height: 20px; max-width: 620px; }
  #progress-bar { background: var(--accent); height: 100%; width: 0%; transition: width .3s; }
  #progress-text { margin-top: 8px; font-size: 12.5px; color: var(--text-lo); font-family: 'JetBrains Mono', monospace; }
  #progress-log { margin-top: 14px; max-height: 320px; overflow-y: auto; background: var(--surface-raised);
    padding: 10px 12px; border-radius: 8px; font-size: 12px; font-family: 'JetBrains Mono', monospace; }
  #progress-log div { padding: 1px 0; color: var(--text-lo); }

  #loading-overlay {
    display: none; position: fixed; inset: 0; background: rgba(10,12,16,.94);
    z-index: 100; align-items: center; justify-content: center; flex-direction: column;
  }
  #loading-overlay.show { display: flex; }
  .spinner {
    width: 40px; height: 40px; border-radius: 50%;
    border: 3px solid var(--line); border-top-color: var(--accent);
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  #loading-overlay .txt { margin-top: 18px; font-size: 14px; color: var(--text-hi); font-family: 'Space Grotesk', sans-serif; }
  #loading-overlay .sub { margin-top: 6px; font-size: 12px; color: var(--text-lo); }
</style>
</head>
<body>

<nav class="rail">
  <div class="brand">
    <div class="mark">PLEX · RENAME</div>
    <div class="title">Библиотека фильмов</div>
  </div>

  <div class="navitem" data-tab="settings">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06A1.65 1.65 0 005 15a1.65 1.65 0 00-1.51-1H3.4a2 2 0 010-4h.09A1.65 1.65 0 005 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06A1.65 1.65 0 009 4.6a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09A1.65 1.65 0 0015 4.6a1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>
    Настройка
  </div>
  <div class="navitem" data-tab="preview">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/></svg>
    Превью
    {% if plan is not none %}<span class="badge ok">{{ plan|length }}</span>{% endif %}
  </div>
  <div class="navitem" data-tab="conflicts">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><path d="M12 9v4M12 17h.01"/></svg>
    Конфликты
    {% if conflicts %}<span class="badge danger">{{ conflicts|length }}</span>{% endif %}
  </div>
  <div class="navitem" data-tab="unmatched">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3M12 17h.01"/></svg>
    Без TMDB
    {% if unmatched %}<span class="badge warn">{{ unmatched|length }}</span>{% endif %}
  </div>
  <div class="navitem" data-tab="log">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 17l6-6-6-6M12 19h8"/></svg>
    Журнал
  </div>

  <div class="rail-footer">
    Plex Rename <span class="ver">v{{ version }}</span> · Sergey Sychev<br>
    Запущено: {{ started_at }}<br>
    Логи: {{ log_dir }}/
  </div>
</nav>

<main>
  <div class="statbar">
    <div class="stat accent"><div class="num">{{ plan|length if plan is not none else '—' }}</div><div class="lbl">к переименованию</div></div>
    <div class="stat"><div class="num">{{ already_ok }}</div><div class="lbl">уже в порядке</div></div>
    <div class="stat danger"><div class="num">{{ conflicts|length if conflicts is not none else 0 }}</div><div class="lbl">конфликтов</div></div>
    <div class="stat warn"><div class="num">{{ unmatched|length if unmatched is not none else 0 }}</div><div class="lbl">без tmdb id</div></div>
  </div>

  <section class="panel" data-panel="settings">
    <h1>Настройка подключения</h1>
    <p class="sub">Укажите адрес вашего Plex-сервера, токен доступа и имя библиотеки. Ничего не отправляется никуда, кроме вашего собственного Plex.</p>

    {% if message %}<div class="msg {{ 'msg-ok' if status=='ok' else 'msg-err' }}">{{ message | safe }}</div>{% endif %}

    <form method="post" action="/preview">
      <label>Адрес Plex (Plex URL)</label>
      <input type="text" name="plex_url" value="{{ plex_url }}" placeholder="http://192.168.2.2:32400">

      <label>Plex Token</label>
      <input type="text" name="plex_token" value="{{ plex_token }}" placeholder="ваш X-Plex-Token">

      <label>Имя библиотеки в Plex</label>
      <input type="text" name="library_name" value="{{ library_name }}" placeholder="BestFilms">

      <label>Шаблон нового имени файла</label>
      <input type="text" name="template" value="{{ template }}">
      <p class="hint">Доступно: {title_full} (название + оригинальное, если оно рус/лат) · {year} · {resolution} · {video_codec} · {audio_codec} · {audio_channels} · {edition} · {ext_ref} (tmdb-ID или, если его нет — imdb-ID)</p>

      <button type="submit" class="btn-primary">Показать превью →</button>
    </form>
  </section>

  <section class="panel" data-panel="preview">
    <h1>Превью переименования</h1>
    <p class="sub">Ничего на диске не изменено. Список ниже — то, что произойдёт после нажатия «Применить».</p>

    {% if plan %}
    <form method="post" action="/apply">
      <input type="hidden" name="plex_url" value="{{ plex_url }}">
      <input type="hidden" name="plex_token" value="{{ plex_token }}">
      <input type="hidden" name="library_name" value="{{ library_name }}">
      <input type="hidden" name="template" value="{{ template }}">
      <button type="submit" class="btn-danger" onclick="return confirm('Точно переименовать {{ plan|length }} файлов на диске? Это действие нельзя отменить массово.');">
        Применить переименование ({{ plan|length }})
      </button>
    </form>
    {% for item in plan %}
    <div class="diffrow">
      <div class="bar old"></div>
      <div class="lines">
        <div class="filename old">{{ item.old }}</div>
        <div class="filename new">{{ item.new }}</div>
      </div>
    </div>
    {% endfor %}
    {% elif plan is not none %}
      <div class="empty">Все файлы уже в порядке — переименовывать нечего.</div>
    {% else %}
      <div class="empty">Сначала нажмите «Показать превью» на вкладке «Настройка».</div>
    {% endif %}
  </section>

  <section class="panel" data-panel="conflicts">
    <h1>Конфликты имён</h1>
    <p class="sub">Эти файлы получили бы одинаковое новое имя — переименование для них пропущено, чтобы не потерять данные.</p>
    {% if conflicts %}
    <table>
      <tr><th>Новое имя (совпало)</th><th>Файлы-источники</th></tr>
      {% for c in conflicts %}
      <tr><td class="filename">{{ c.new }}</td><td class="filename">{{ c.olds | join('<br>') | safe }}</td></tr>
      {% endfor %}
    </table>
    {% else %}
      <div class="empty">Конфликтов нет.</div>
    {% endif %}
  </section>

  <section class="panel" data-panel="unmatched">
    <h1>Без TMDB ID</h1>
    <p class="sub">Plex не сопоставил эти фильмы с TMDB — переименование для них пропущено. Поправьте сопоставление в самом Plex и запустите превью заново.</p>

    <form method="post" action="/debug" style="margin-bottom:24px; padding:16px; background:var(--surface); border:1px solid var(--line); border-radius:8px; max-width:640px;">
      <input type="hidden" name="plex_url" value="{{ plex_url }}">
      <input type="hidden" name="plex_token" value="{{ plex_token }}">
      <input type="hidden" name="library_name" value="{{ library_name }}">
      <input type="hidden" name="template" value="{{ template }}">
      <label style="margin-top:0;">Диагностика: посмотреть сырые данные Plex для фильма</label>
      <input type="text" name="debug_query" value="{{ debug_query }}" placeholder="например: Апокалипсис сегодня">
      <button type="submit" class="btn-primary" style="margin-top:10px;">Показать сырые данные</button>
    </form>

    {% if debug_result %}
    <pre style="background:var(--surface-raised); padding:14px; border-radius:8px; font-family:'JetBrains Mono',monospace; font-size:12px; white-space:pre-wrap; max-width:900px; margin-bottom:24px;">{{ debug_result }}</pre>
    {% endif %}

    {% if unmatched %}
    <table>
      <tr><th>Файл</th><th>Название в Plex</th></tr>
      {% for u in unmatched %}
      <tr><td class="filename">{{ u.file }}</td><td>{{ u.title }}</td></tr>
      {% endfor %}
    </table>
    {% else %}
      <div class="empty">Все фильмы сопоставлены с TMDB.</div>
    {% endif %}
  </section>

  <section class="panel" data-panel="log">
    <h1>Журнал переименования</h1>
    <p class="sub">Полная история выполненных переименований также сохраняется в файл на диске.</p>
    {% if job_id %}
    <div id="progress-bar-bg"><div id="progress-bar"></div></div>
    <div id="progress-text">Запуск…</div>
    <div id="progress-log"></div>
    {% else %}
    <div class="empty">Журнал появится здесь после нажатия «Применить переименование».</div>
    {% endif %}
  </section>
</main>

<div id="loading-overlay">
  <div class="spinner"></div>
  <div class="txt" id="loading-text">Идёт сканирование библиотеки…</div>
  <div class="sub">Это может занять до нескольких минут на большой библиотеке — не закрывайте страницу</div>
</div>

<script>
  const navitems = document.querySelectorAll('.navitem');
  const panels = document.querySelectorAll('.panel');
  function activate(tab) {
    navitems.forEach(n => n.classList.toggle('active', n.dataset.tab === tab));
    panels.forEach(p => p.classList.toggle('active', p.dataset.panel === tab));
  }
  navitems.forEach(n => n.addEventListener('click', () => activate(n.dataset.tab)));
  activate({{ active_tab | tojson }});

  const overlay = document.getElementById('loading-overlay');
  const overlayText = document.getElementById('loading-text');
  function showOverlay(text) {
    if (!overlay) return;
    if (overlayText) overlayText.textContent = text;
    overlay.classList.add('show');
  }
  document.querySelectorAll('form[action="/preview"]').forEach(f => {
    f.addEventListener('submit', () => showOverlay('Идёт сканирование библиотеки…'));
  });
  document.querySelectorAll('form[action="/apply"]').forEach(f => {
    f.addEventListener('submit', (e) => {
      // confirm() уже отработал в onclick кнопки; если пользователь отменил — submit не произойдёт
      showOverlay('Запускаю переименование…');
    });
  });
  document.querySelectorAll('form[action="/debug"]').forEach(f => {
    f.addEventListener('submit', () => showOverlay('Запрашиваю данные у Plex…'));
  });

  const jobId = {{ job_id | tojson }};
  if (jobId) {
    const bar = document.getElementById('progress-bar');
    const text = document.getElementById('progress-text');
    const logBox = document.getElementById('progress-log');
    const timer = setInterval(async () => {
      const r = await fetch('/progress/' + jobId);
      const data = await r.json();
      const pct = data.total ? Math.round(data.done / data.total * 100) : 0;
      bar.style.width = pct + '%';
      text.textContent = data.done + ' из ' + data.total + (data.running ? ' — выполняется…' : ' — готово');
      logBox.innerHTML = data.log.slice(-40).map(l => '<div>' + l + '</div>').join('');
      logBox.scrollTop = logBox.scrollHeight;
      if (!data.running) clearInterval(timer);
    }, 1000);
  }
</script>

</body>
</html>
"""

LATIN_CYRILLIC_RE = re.compile(r"^[A-Za-zА-Яа-яЁё0-9\s\-:,.'!?&()«»№]+$")


def safe_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def get_external_ref(movie):
    """
    Возвращает строку вида "tmdb-12345", "imdb-tt0078788" или "kp-354" —
    то, что реально есть в Plex для этого фильма. Порядок предпочтения:
    TMDB -> IMDb -> Кинопоиск (некоторые библиотеки сопоставлены через
    сторонний агент Кинопоиска, у него нет перекрёстных ID на TMDB/IMDb).
    Возвращает None только если фильм в Plex вообще не опознан.
    """
    def _search(guid_list, legacy_guid):
        for guid in guid_list:
            if guid.id.startswith("tmdb://"):
                return "tmdb-" + guid.id.replace("tmdb://", "")
        for guid in guid_list:
            if guid.id.startswith("imdb://"):
                return "imdb-" + guid.id.replace("imdb://", "")
        m = re.search(r"themoviedb://(\d+)", legacy_guid)
        if m:
            return "tmdb-" + m.group(1)
        m = re.search(r"imdb://(tt\d+)", legacy_guid)
        if m:
            return "imdb-" + m.group(1)
        m = re.search(r"(?:kinopoisk2?|poiskkino)://(?:movie/)?(\d+)", legacy_guid)
        if m:
            return "kp-" + m.group(1)
        return None

    guids = getattr(movie, "guids", []) or []
    legacy = getattr(movie, "guid", "") or ""
    ref = _search(guids, legacy)
    if ref:
        return ref

    try:
        movie.reload()
    except Exception:
        return None

    guids = getattr(movie, "guids", []) or []
    legacy = getattr(movie, "guid", "") or ""
    return _search(guids, legacy)


def build_title_full(title, original_title):
    if original_title and original_title != title and LATIN_CYRILLIC_RE.match(original_title):
        return f"{title} ({original_title})"
    return title


def get_hdr_label(media):
    for attr in ("videoDynamicRange", "videoDynamicRangeType"):
        val = getattr(media, attr, None)
        if val:
            return str(val).upper()
    return None


def get_audio_channels_label(media):
    ch = getattr(media, "audioChannels", None)
    if not ch:
        return "unknown"
    mapping = {1: "1.0", 2: "2.0", 6: "5.1", 8: "7.1"}
    return mapping.get(ch, f"{ch}ch")


def build_new_name(movie, template: str, ext_ref: str) -> str:
    title = movie.title or "Unknown"
    original_title = getattr(movie, "originalTitle", None) or title
    year = movie.year or "0000"

    video_codec = "unknown"
    audio_codec = "unknown"
    resolution = "unknown"
    audio_channels = "unknown"
    hdr = None
    if movie.media:
        media = movie.media[0]
        video_codec = (media.videoCodec or "unknown").upper()
        audio_codec = (media.audioCodec or "unknown").upper()
        resolution = media.videoResolution or "unknown"
        audio_channels = get_audio_channels_label(media)
        hdr = get_hdr_label(media)

    edition = getattr(movie, "editionTitle", None) or ""
    edition_part = f" - {edition}" if edition else ""

    title_full = build_title_full(title, original_title)
    video_codec_display = f"{video_codec} {hdr}" if hdr else video_codec

    try:
        new_name = template.format(
            title_full=title_full,
            title=title,
            original_title=original_title,
            year=year,
            video_codec=video_codec_display,
            audio_codec=audio_codec,
            audio_channels=audio_channels,
            resolution=resolution,
            ext_ref=ext_ref,
            edition=edition_part,
        )
    except KeyError as e:
        raise ValueError(
            f"В шаблоне используется неизвестный плейсхолдер {{{e.args[0]}}}. "
            f"Доступны: title_full, year, resolution, video_codec, audio_codec, "
            f"audio_channels, edition, ext_ref."
        )
    return safe_filename(new_name)


def compute_plan(plex_url, plex_token, library_name, template):
    plex = PlexServer(plex_url, plex_token)
    library = plex.library.section(library_name)
    movies = library.all()

    raw_items = []
    unmatched = []
    already_ok = 0

    for movie in movies:
        if not movie.media or not movie.media[0].parts:
            continue

        ext_ref = get_external_ref(movie)
        if not ext_ref:
            for part in movie.media[0].parts:
                if part.file:
                    unmatched.append({"file": os.path.basename(part.file), "title": f"{movie.title} ({movie.year})"})
            continue

        for part in movie.media[0].parts:
            old_path = part.file
            if not old_path or not os.path.exists(old_path):
                continue
            folder = os.path.dirname(old_path)
            ext = os.path.splitext(old_path)[1]
            new_base = build_new_name(movie, template, ext_ref)
            new_path = os.path.join(folder, new_base + ext)
            if old_path == new_path:
                already_ok += 1
                continue
            raw_items.append({"old_path": old_path, "new_path": new_path,
                               "old": os.path.basename(old_path), "new": os.path.basename(new_path)})

    by_new_path = {}
    for item in raw_items:
        by_new_path.setdefault(item["new_path"], []).append(item)

    plan = []
    conflicts = []
    for new_path, items in by_new_path.items():
        if len(items) > 1:
            conflicts.append({"new": os.path.basename(new_path), "olds": [i["old"] for i in items]})
        else:
            plan.append(items[0])

    return plan, conflicts, unmatched, already_ok


def render(plex_url="", plex_token="", library_name="BestFilms", template=DEFAULT_TEMPLATE,
           plan=None, conflicts=None, unmatched=None, already_ok=0,
           message=None, status="ok", job_id=None, active_tab="settings",
           debug_result=None, debug_query=""):
    return render_template_string(
        PAGE, plex_url=plex_url, plex_token=plex_token, library_name=library_name,
        template=template, plan=plan, conflicts=conflicts, unmatched=unmatched, already_ok=already_ok,
        message=message, status=status, job_id=job_id, active_tab=active_tab, log_dir=LOG_DIR,
        version=VERSION, started_at=STARTED_AT, debug_result=debug_result, debug_query=debug_query,
    )


@app.route("/debug", methods=["POST"])
def debug():
    plex_url = request.form.get("plex_url", "")
    plex_token = request.form.get("plex_token", "")
    library_name = request.form.get("library_name", "")
    query = request.form.get("debug_query", "")

    debug_result = None
    try:
        plex = PlexServer(plex_url, plex_token)
        library = plex.library.section(library_name)
        results = library.search(title=query)
        if not results:
            debug_result = f"Ничего не нашлось по запросу «{query}»."
        else:
            lines = []
            for movie in results[:3]:
                lines.append(f"=== {movie.title} ({movie.year}) ===")
                lines.append(f"movie.guid = {getattr(movie, 'guid', None)!r}")
                lines.append(f"movie.guids (до reload) = {getattr(movie, 'guids', None)!r}")
                try:
                    movie.reload()
                    lines.append(f"movie.guids (после reload) = {getattr(movie, 'guids', None)!r}")
                except Exception as e:
                    lines.append(f"reload() не удался: {e}")
                lines.append("")
            debug_result = "\n".join(lines)
    except Exception as e:
        debug_result = f"Ошибка: {e}"

    template = request.form.get("template", DEFAULT_TEMPLATE)
    library_name_val = library_name

    return render(plex_url, plex_token, library_name_val, template,
                  LAST_PLAN if LAST_PLAN else None, LAST_CONFLICTS, LAST_UNMATCHED,
                  LAST_ALREADY_OK, None, "ok", None, "unmatched", debug_result=debug_result, debug_query=query)


@app.route("/", methods=["GET"])
def index():
    return render()


@app.route("/preview", methods=["POST"])
def preview():
    global LAST_PLAN, LAST_CONFLICTS, LAST_UNMATCHED, LAST_ALREADY_OK
    plex_url = request.form.get("plex_url", "")
    plex_token = request.form.get("plex_token", "")
    library_name = request.form.get("library_name", "")
    template = request.form.get("template", DEFAULT_TEMPLATE)

    try:
        plan, conflicts, unmatched, already_ok = compute_plan(plex_url, plex_token, library_name, template)
        LAST_PLAN, LAST_CONFLICTS, LAST_UNMATCHED, LAST_ALREADY_OK = plan, conflicts, unmatched, already_ok
        message = "Готово. Ничего на диске ещё не изменено — проверьте вкладки «Превью», «Конфликты» и «Без TMDB»."
        status = "ok"
        active_tab = "preview"
    except Exception as e:
        plan, conflicts, unmatched, already_ok = None, [], [], 0
        LAST_PLAN, LAST_CONFLICTS, LAST_UNMATCHED, LAST_ALREADY_OK = [], [], [], 0
        message = f"Ошибка: {e}"
        status = "err"
        active_tab = "settings"

    return render(plex_url, plex_token, library_name, template, plan, conflicts, unmatched,
                  already_ok, message, status, None, active_tab)


def run_rename_job(job_id, plan):
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f"rename_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    job = JOBS[job_id]

    with open(log_path, "a", encoding="utf-8") as logf:
        logf.write(f"=== Запуск переименования: {datetime.now().isoformat()} ===\n")
        for item in plan:
            try:
                os.rename(item["old_path"], item["new_path"])
                line = f"OK: {item['old']} -> {item['new']}"
            except Exception as e:
                line = f"ОШИБКА: {item['old']}: {e}"
            logf.write(line + "\n")
            logf.flush()
            job["log"].append(line)
            job["done"] += 1
            time.sleep(0.01)
        logf.write(f"=== Завершено: {datetime.now().isoformat()} ===\n")

    job["running"] = False


@app.route("/apply", methods=["POST"])
def apply():
    plan = LAST_PLAN
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"total": len(plan), "done": 0, "running": True, "log": []}

    thread = threading.Thread(target=run_rename_job, args=(job_id, plan), daemon=True)
    thread.start()

    plex_url = request.form.get("plex_url", "")
    plex_token = request.form.get("plex_token", "")
    library_name = request.form.get("library_name", "")
    template = request.form.get("template", DEFAULT_TEMPLATE)

    return render(plex_url, plex_token, library_name, template, None, LAST_CONFLICTS, LAST_UNMATCHED,
                  LAST_ALREADY_OK, f"Запущено переименование {len(plan)} файлов.", "ok", job_id, "log")


@app.route("/progress/<job_id>")
def progress(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"total": 0, "done": 0, "running": False, "log": ["Задача не найдена"]})
    return jsonify(job)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5055, threaded=True)

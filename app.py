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

VERSION = "1.9.2"
STARTED_AT = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# v1.9.0. Раньше план лежал в одной переменной на весь процесс. Открыв
# превью «Мультфильмов» в одной вкладке и «Фильмов» в другой, по кнопке
# «Применить» в первой вкладке можно было переименовать вторую
# библиотеку. Теперь у каждого превью свой идентификатор. Он же
# защищает /apply: без него маршрут ничего не делает, а подобрать его со
# стороннего сайта нельзя — то есть чужая страница больше не способна
# запустить переименование вслепую.
PLANS = {}
MAX_PLANS = 20

JOBS = {}
MAX_JOBS = 20
LOG_DIR = os.environ.get("LOG_DIR", "/app/logs")

# Сколько ждать ответа от Plex. Умолчание plexapi — 30 секунд, и на
# библиотеке в полторы тысячи фильмов этого не хватало: превью падало
# с «Read timed out», не показав ни одной строки. Запас вчетверо
# дешевле, чем необъяснимая ошибка на половине библиотеки.
PLEX_TIMEOUT = int(os.environ.get("PLEX_TIMEOUT", "120"))

# Предел длины имени файла в ext4/btrfs — 255 байт, а кириллица занимает
# по два байта на букву. Русское название вместе с оригинальным и
# кодеками этот предел перебирает, и os.rename падает по каждому такому
# файлу.
MAX_NAME_BYTES = 255

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
  <div class="navitem" data-tab="ambiguous">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 2l9 5v10l-9 5-9-5V7z"/><path d="M12 8v4M12 16h.01"/></svg>
    Спорный ID
    {% if ambiguous %}<span class="badge danger">{{ ambiguous|length }}</span>{% endif %}
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
    <div class="stat danger"><div class="num">{{ ambiguous|length if ambiguous is not none else 0 }}</div><div class="lbl">спорный id</div></div>
  </div>

  <section class="panel" data-panel="settings">
    <h1>Настройка подключения</h1>
    <p class="sub">Укажите адрес вашего Plex-сервера, токен доступа и имя библиотеки. Ничего не отправляется никуда, кроме вашего собственного Plex.</p>

    {% if message %}<div class="msg {{ 'msg-ok' if status=='ok' else 'msg-err' }}">{{ message }}</div>{% endif %}

    <form method="post" action="/preview">
      <label>Адрес Plex (Plex URL)</label>
      <input type="text" name="plex_url" value="{{ plex_url }}" placeholder="http://192.168.2.2:32400">

      <label>Plex Token</label>
      <input type="password" name="plex_token" value="{{ plex_token }}" placeholder="ваш X-Plex-Token">
      <p class="hint">Токен остаётся на вашем сервере. С версии 1.9.0 он не дублируется в скрытые поля на других вкладках — форма «Применить» передаёт только номер плана.</p>

      <label>Имя библиотеки в Plex</label>
      <input type="text" name="library_name" value="{{ library_name }}" placeholder="BestFilms">

      <label>Шаблон нового имени файла</label>
      <input type="text" name="template" value="{{ template }}">
      <p class="hint">Доступно: {title_full} (название + оригинальное, если оно рус/лат) · {year} · {resolution} · {video_codec} · {audio_codec} · {audio_channels} · {edition} · {ext_ref} (tmdb-ID или, если его нет — imdb-ID). Многочастевые фильмы (несколько файлов у одного фильма в Plex — например старые советские картины в 2 сериях) получают суффикс « - pt1», « - pt2» и т.д. в конце имени автоматически, по стандартному соглашению Plex — в шаблоне указывать не нужно.</p>

      <button type="submit" class="btn-primary">Показать превью →</button>
    </form>
  </section>

  <section class="panel" data-panel="preview">
    <h1>Превью переименования</h1>
    <p class="sub">Ничего на диске не изменено. Список ниже — то, что произойдёт после нажатия «Применить».</p>

    {% if plan %}
    <form method="post" action="/apply">
      <input type="hidden" name="plan_id" value="{{ plan_id }}">
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
      <tr><th>Новое имя</th><th>Причина</th><th>Файлы-источники</th></tr>
      {% for c in conflicts %}
      <tr>
        <td class="filename">{{ c.new }}</td>
        <td>{{ c.reason }}</td>
        <td class="filename">{% for o in c.olds %}{{ o }}{% if not loop.last %}<br>{% endif %}{% endfor %}</td>
      </tr>
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
      <input type="hidden" name="plan_id" value="{{ plan_id }}">
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

  <section class="panel" data-panel="ambiguous">
    <h1>Спорный ID</h1>
    <p class="sub">У этих фильмов в карточке Plex больше одного внешнего ID. Plex не стирает прежний ID при пересопоставлении — после Fix Match старый остаётся рядом с новым. Взять первый попавшийся нельзя: он может указывать на другой фильм, а записанный в имя файла ID Plex потом использует для принудительного сопоставления, и ошибка закрепится. Поправьте сопоставление в Plex и запустите превью заново.</p>
    {% if ambiguous %}
    <table>
      <tr><th>Файл</th><th>Название в Plex</th><th>Найденные ID</th></tr>
      {% for a in ambiguous %}
      <tr><td class="filename">{{ a.file }}</td><td>{{ a.title }}</td><td class="filename">{{ a.ids }}</td></tr>
      {% endfor %}
    </table>
    {% else %}
      <div class="empty">Спорных ID нет.</div>
    {% endif %}
  </section>

  <section class="panel" data-panel="log">
    <h1>Журнал переименования</h1>
    <p class="sub">Полная история выполненных переименований также сохраняется в файл на диске.</p>
    {% if job_id %}
    <div class="msg msg-ok" style="max-width:640px;">Файлы переименованы мимо Radarr и Sonarr — у них остались прежние пути, и фильмы будут числиться отсутствующими. После завершения запустите в них пересканирование библиотеки. Саму библиотеку Plex приложение обновит само.</div>
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


def store_plan(record: dict) -> str:
    """Кладёт результат превью и возвращает его идентификатор."""
    plan_id = str(uuid.uuid4())
    PLANS[plan_id] = record
    while len(PLANS) > MAX_PLANS:
        PLANS.pop(next(iter(PLANS)), None)
    return plan_id


def _truncate_to_bytes(text: str, limit: int) -> str:
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    return data[:limit].decode("utf-8", "ignore").rstrip()


def fit_name(base: str, ext: str) -> str:
    """Укладывает имя в 255 байт, сохраняя хвост вида {tmdb-12345}.

    Обрезать просто с конца нельзя: там лежит ID, по которому Plex
    принудительно сопоставляет файл с карточкой. Поэтому хвост в фигурных
    скобках отрезается, укорачивается начало, затем хвост возвращается.
    """
    limit = MAX_NAME_BYTES - len(ext.encode("utf-8"))
    if len(base.encode("utf-8")) <= limit:
        return base
    tail = ""
    m = re.search(r"\s*\{[^{}]+\}\s*$", base)
    if m:
        tail = m.group(0).strip()
        base = base[:m.start()]
    head_limit = limit - len(tail.encode("utf-8")) - 1
    if head_limit < 1:
        return _truncate_to_bytes(base + tail, limit)
    head = _truncate_to_bytes(base, head_limit).rstrip(" .-")
    return (head + " " + tail).strip() if tail else head


def safe_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def _collect_ids(guid_list, prefix):
    """Все ID одного вида из карточки, без повторов и в исходном порядке."""
    found = []
    for guid in guid_list:
        gid = getattr(guid, "id", "") or ""
        if gid.startswith(prefix):
            value = gid[len(prefix):]
            if value and value not in found:
                found.append(value)
    return found


def get_external_ref(movie):
    """
    Возвращает пару (ref, ambiguous).

    ref — строка вида "tmdb-12345", "imdb-tt0078788" или "kp-354": то,
    что реально есть в Plex для этого фильма. Порядок предпочтения:
    TMDB -> IMDb -> Кинопоиск (некоторые библиотеки сопоставлены через
    сторонний агент Кинопоиска, у него нет перекрёстных ID на TMDB/IMDb).

    ambiguous — список ID, когда их в карточке несколько.

    v1.9.0. Plex не удаляет прежние внешние ID при пересопоставлении: ни
    Fix Match, ни Refresh, ни отвязка с повторной привязкой не стирают
    старый tmdb:// — он остаётся в карточке рядом с новым. Прежний код
    брал первый попавшийся и мог зашить в имя файла ID чужого фильма.
    Ошибка при этом закрепляется навсегда: Plex потом читает {tmdb-ID}
    из имени файла и принудительно сопоставляет карточку по нему.
    Поэтому при нескольких ID файл не переименовывается, а уходит в
    отдельный список — пусть человек решит, какой ID верный.
    """
    def _search(guid_list, legacy_guid):
        tmdb = _collect_ids(guid_list, "tmdb://")
        if tmdb:
            return ("tmdb-" + tmdb[0], ["tmdb-" + i for i in tmdb] if len(tmdb) > 1 else None)
        imdb = _collect_ids(guid_list, "imdb://")
        if imdb:
            return ("imdb-" + imdb[0], ["imdb-" + i for i in imdb] if len(imdb) > 1 else None)
        m = re.search(r"themoviedb://(\d+)", legacy_guid)
        if m:
            return ("tmdb-" + m.group(1), None)
        m = re.search(r"imdb://(tt\d+)", legacy_guid)
        if m:
            return ("imdb-" + m.group(1), None)
        m = re.search(r"(?:kinopoisk2?|poiskkino)://(?:movie/)?(\d+)", legacy_guid)
        if m:
            return ("kp-" + m.group(1), None)
        return (None, None)

    guids = getattr(movie, "guids", []) or []
    legacy = getattr(movie, "guid", "") or ""
    ref, ambiguous = _search(guids, legacy)
    if ref:
        return ref, ambiguous

    try:
        movie.reload()
    except Exception:
        return None, None

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


def build_new_name(movie, template: str, ext_ref: str, part_num: int = None, part_total: int = None) -> str:
    """
    part_num/part_total описывают многочастевой фильм — когда у одного
    фильма в Plex несколько файлов-частей (типично для старых советских
    картин, выходивших по 2 (иногда больше) сериям). Если part_total > 1,
    к итоговому имени добавляется суффикс " - ptN" в самом конце, перед
    расширением — это официальный формат Plex для многочастевых файлов
    (см. https://support.plex.tv, "Multi-part movies"), он же позволяет
    Plex и дальше держать части одного фильма вместе после переименования.
    """
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

    if part_total and part_total > 1 and part_num:
        new_name = f"{new_name} - pt{part_num}"

    return safe_filename(new_name)


def compute_plan(plex_url, plex_token, library_name, template):
    plex = PlexServer(plex_url, plex_token, timeout=PLEX_TIMEOUT)
    library = plex.library.section(library_name)
    movies = library.all()

    raw_items = []
    unmatched = []
    ambiguous = []
    already_ok = 0

    for movie in movies:
        if not movie.media or not movie.media[0].parts:
            continue

        ext_ref, ambiguous_ids = get_external_ref(movie)
        if not ext_ref:
            for part in movie.media[0].parts:
                if part.file:
                    unmatched.append({"file": os.path.basename(part.file), "title": f"{movie.title} ({movie.year})"})
            continue

        if ambiguous_ids:
            # В карточке несколько внешних ID — какой из них настоящий,
            # знает только человек. Подробности в get_external_ref.
            for part in movie.media[0].parts:
                if part.file:
                    ambiguous.append({"file": os.path.basename(part.file),
                                      "title": f"{movie.title} ({movie.year})",
                                      "ids": ", ".join(ambiguous_ids)})
            continue

        parts = movie.media[0].parts
        part_total = len(parts)
        for part_num, part in enumerate(parts, start=1):
            old_path = part.file
            if not old_path or not os.path.exists(old_path):
                continue
            folder = os.path.dirname(old_path)
            ext = os.path.splitext(old_path)[1]
            new_base = build_new_name(movie, template, ext_ref, part_num=part_num, part_total=part_total)
            new_base = fit_name(new_base, ext)
            new_path = os.path.join(folder, new_base + ext)
            if old_path == new_path:
                already_ok += 1
                continue
            raw_items.append({"old_path": old_path, "new_path": new_path,
                               "old": os.path.basename(old_path), "new": os.path.basename(new_path)})

    by_new_path = {}
    for item in raw_items:
        by_new_path.setdefault(item["new_path"], []).append(item)

    planned_sources = {item["old_path"] for item in raw_items}

    plan = []
    conflicts = []
    for new_path, items in by_new_path.items():
        if len(items) > 1:
            conflicts.append({"new": os.path.basename(new_path),
                              "reason": "несколько файлов дают одно имя",
                              "olds": [i["old"] for i in items]})
            continue
        # v1.9.0. os.rename на Linux молча затирает файл, который уже
        # лежит по целевому пути. Проверка выше ловит только столкновения
        # внутри плана: файл, которого в плане нет — ручная копия,
        # остаток старого релиза, файл без карточки в Plex — прежде
        # исчезал без следа и без строки в журнале.
        if os.path.exists(new_path):
            reason = ("целевое имя занято файлом, который тоже переименовывается"
                      if new_path in planned_sources
                      else "целевое имя уже занято другим файлом")
            conflicts.append({"new": os.path.basename(new_path),
                              "reason": reason,
                              "olds": [items[0]["old"]]})
            continue
        plan.append(items[0])

    return plan, conflicts, unmatched, ambiguous, already_ok


def render(plex_url="", plex_token="", library_name="BestFilms", template=DEFAULT_TEMPLATE,
           plan=None, conflicts=None, unmatched=None, ambiguous=None, already_ok=0,
           message=None, status="ok", job_id=None, active_tab="settings",
           debug_result=None, debug_query="", plan_id=""):
    return render_template_string(
        PAGE, plex_url=plex_url, plex_token=plex_token, library_name=library_name,
        template=template, plan=plan, conflicts=conflicts, unmatched=unmatched,
        ambiguous=ambiguous, already_ok=already_ok,
        message=message, status=status, job_id=job_id, active_tab=active_tab, log_dir=LOG_DIR,
        version=VERSION, started_at=STARTED_AT, debug_result=debug_result, debug_query=debug_query,
        plan_id=plan_id,
    )


def render_record(record, plan_id, **over):
    """Страница по сохранённому результату превью."""
    args = dict(
        plex_url=record["plex_url"], plex_token=record["plex_token"],
        library_name=record["library_name"], template=record["template"],
        plan=record["plan"], conflicts=record["conflicts"], unmatched=record["unmatched"],
        ambiguous=record["ambiguous"], already_ok=record["already_ok"], plan_id=plan_id,
    )
    args.update(over)
    return render(**args)


@app.route("/", methods=["GET"])
def index():
    return render()


@app.route("/preview", methods=["POST"])
def preview():
    plex_url = request.form.get("plex_url", "")
    plex_token = request.form.get("plex_token", "")
    library_name = request.form.get("library_name", "")
    template = request.form.get("template", DEFAULT_TEMPLATE)

    try:
        plan, conflicts, unmatched, ambiguous, already_ok = compute_plan(
            plex_url, plex_token, library_name, template)
    except Exception as e:
        return render(plex_url, plex_token, library_name, template,
                      None, [], [], [], 0, f"Ошибка: {e}", "err", None, "settings")

    record = {"plex_url": plex_url, "plex_token": plex_token, "library_name": library_name,
              "template": template, "plan": plan, "conflicts": conflicts,
              "unmatched": unmatched, "ambiguous": ambiguous, "already_ok": already_ok}
    plan_id = store_plan(record)
    return render_record(
        record, plan_id, status="ok", active_tab="preview",
        message="Готово. Ничего на диске ещё не изменено — проверьте вкладки «Превью», "
                "«Конфликты», «Без TMDB» и «Спорный ID».")


@app.route("/debug", methods=["POST"])
def debug():
    plan_id = request.form.get("plan_id", "")
    record = PLANS.get(plan_id)
    if not record:
        return render(message="Результат превью устарел — запустите превью заново.",
                      status="err", active_tab="settings")

    query = request.form.get("debug_query", "")
    try:
        plex = PlexServer(record["plex_url"], record["plex_token"], timeout=PLEX_TIMEOUT)
        library = plex.library.section(record["library_name"])
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

    return render_record(record, plan_id, active_tab="unmatched",
                         debug_result=debug_result, debug_query=query)


def _open_log():
    """Открывает файл журнала. Если каталог недоступен, возвращает
    (None, причина): переименование из-за этого не отменяется — раньше
    ошибка на os.makedirs убивала поток целиком, файлы оставались
    нетронутыми, а в интерфейсе просто навсегда застывал прогресс-бар."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        path = os.path.join(LOG_DIR, f"rename_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        return open(path, "a", encoding="utf-8"), None
    except OSError as e:
        return None, f"Журнал на диск не пишется ({e}); переименование всё равно выполняется."


def run_rename_job(job_id, record):
    job = JOBS[job_id]
    logf, log_problem = _open_log()
    if log_problem:
        job["log"].append(log_problem)

    def write(line):
        job["log"].append(line)
        if logf:
            logf.write(line + "\n")
            logf.flush()

    try:
        write(f"=== Запуск переименования: {datetime.now().isoformat()} ===")
        for item in record["plan"]:
            try:
                # Повторная проверка перед самим переименованием: между
                # превью и применением файл по целевому пути мог
                # появиться, а os.rename затирает его молча.
                if os.path.exists(item["new_path"]):
                    line = f"ПРОПУСК: {item['old']}: целевое имя уже занято — {item['new']}"
                else:
                    os.rename(item["old_path"], item["new_path"])
                    line = f"OK: {item['old']} -> {item['new']}"
            except OSError as e:
                line = f"ОШИБКА: {item['old']}: {e}"
            write(line)
            job["done"] += 1
            time.sleep(0.01)

        # Пока Plex не пересканирует библиотеку, он держит прежние пути и
        # фильмы остаются недоступными для проигрывания.
        try:
            plex = PlexServer(record["plex_url"], record["plex_token"], timeout=PLEX_TIMEOUT)
            plex.library.section(record["library_name"]).update()
            write("Запущено обновление библиотеки в Plex.")
        except Exception as e:
            write(f"Обновление библиотеки в Plex не запустилось: {e}")

        write(f"=== Завершено: {datetime.now().isoformat()} ===")
    except Exception as e:
        # Что бы ни случилось, задача обязана завершиться: иначе
        # прогресс-бар в интерфейсе крутится бесконечно.
        job["log"].append(f"Задача прервана: {e}")
    finally:
        if logf:
            logf.close()
        job["running"] = False


@app.route("/apply", methods=["POST"])
def apply():
    plan_id = request.form.get("plan_id", "")
    record = PLANS.get(plan_id)
    # Без действующего номера плана маршрут не делает ничего. Номер
    # выдаётся только странице превью и подобрать его со стороннего сайта
    # нельзя — значит, чужая страница не запустит переименование вслепую.
    if not record:
        return render(message="Результат превью устарел или уже применён — запустите превью заново.",
                      status="err", active_tab="settings")
    PLANS.pop(plan_id, None)   # один план применяется один раз

    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"total": len(record["plan"]), "done": 0, "running": True, "log": []}
    for stale in [k for k, v in list(JOBS.items())[:-MAX_JOBS] if not v.get("running")]:
        JOBS.pop(stale, None)

    thread = threading.Thread(target=run_rename_job, args=(job_id, record), daemon=True)
    thread.start()

    return render_record(record, "", plan=None, job_id=job_id, active_tab="log", status="ok",
                         message=f"Запущено переименование {len(record['plan'])} файлов.")


@app.route("/progress/<job_id>")
def progress(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"total": 0, "done": 0, "running": False, "log": ["Задача не найдена"]})
    return jsonify(job)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5055, threaded=True)
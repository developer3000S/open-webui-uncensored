"""Режимы и шаблоны генерации (план coder.qwen.ai, приоритет B).

Аналог Qwen Coder: Web Dev / Data Visualization / Visual Design / Prototype —
каждый режим имеет системный промпт, стартовый скелет файлов и описание.
Шаблоны-старты (галерея «Build a Snake Game» и т.п.) дают готовый каркас в sandbox.
"""

MODES: dict[str, dict] = {
    'web-dev': {
        'label': 'Web Dev',
        'description': 'Frontend/back-end web application with HTML/CSS/JS.',
        'system_prompt': (
            'You are an expert web developer. Build clean, responsive single-page '
            'apps using vanilla HTML/CSS/JS unless the user requests a framework. '
            'Always output complete files as a change set.'
        ),
        'skeleton': {
            'index.html': (
                '<!doctype html>\n<html lang="en">\n<head>\n  <meta charset="utf-8" />\n'
                '  <meta name="viewport" content="width=device-width, initial-scale=1" />\n'
                '  <title>New App</title>\n  <link rel="stylesheet" href="styles.css" />\n</head>\n'
                '<body>\n  <main id="app"></main>\n  <script src="app.js"></script>\n</body>\n</html>\n'
            ),
            'styles.css': ':root {\n  font-family: system-ui, sans-serif;\n}\n\nbody {\n  margin: 0;\n}\n',
            'app.js': "const app = document.getElementById('app');\napp.textContent = 'Hello world';\n",
        },
    },
    'data-viz': {
        'label': 'Data Visualization',
        'description': 'Interactive charts and dashboards.',
        'system_prompt': (
            'You are a data visualization engineer. Create interactive charts/dashboards '
            'with Chart.js or D3 via CDN. Include sample datasets inline.'
        ),
        'skeleton': {
            'index.html': (
                '<!doctype html>\n<html lang="en">\n<head>\n  <meta charset="utf-8" />\n'
                '  <title>Data Dashboard</title>\n  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>\n'
                '  <style>body{font-family:system-ui;margin:2rem;background:#f6f7fb}</style>\n</head>\n'
                '<body>\n  <h1>Dashboard</h1>\n  <canvas id="chart" width="600" height="320"></canvas>\n'
                '  <script src="app.js"></script>\n</body>\n</html>\n'
            ),
            'app.js': (
                "const ctx = document.getElementById('chart');\n"
                "new Chart(ctx, { type: 'bar', data: { labels: ['A','B','C'], datasets: [{ label: 'Value', data: [5,9,3] }] } });\n"
            ),
        },
    },
    'visual-design': {
        'label': 'Visual Design',
        'description': 'Landing pages and polished visual designs.',
        'system_prompt': (
            'You are a UI/visual designer. Craft pixel-perfect, aesthetically refined '
            'static pages with modern CSS (gradients, glassmorphism, animations).'
        ),
        'skeleton': {
            'index.html': (
                '<!doctype html>\n<html lang="en">\n<head>\n  <meta charset="utf-8" />\n'
                '  <title>Landing</title>\n  <style>body{margin:0;font-family:system-ui}'
                '.hero{min-height:100vh;display:grid;place-items:center;'
                'background:linear-gradient(135deg,#6366f1,#ec4899);color:#fff}'
                '.hero h1{font-size:3rem;margin:0}</style>\n</head>\n'
                '<body><section class="hero"><h1>Your product</h1></section></body>\n</html>\n'
            ),
        },
    },
    'prototype': {
        'label': 'Prototype',
        'description': 'Quick interactive prototypes and demos.',
        'system_prompt': (
            'You rapidly build clickable prototypes: minimal but functional demos that '
            'communicate an idea. Prefer single-file HTML with inline JS/CSS.'
        ),
        'skeleton': {
            'index.html': (
                '<!doctype html>\n<html lang="en">\n<head>\n  <meta charset="utf-8" />\n'
                '  <title>Prototype</title>\n  <style>body{font-family:system-ui;margin:2rem}</style>\n</head>\n'
                '<body>\n  <h1>Prototype</h1>\n  <button onclick="alert(\'clicked\')">Click me</button>\n</body>\n</html>\n'
            ),
        },
    },
}


TEMPLATES: list[dict] = [
    {
        'id': 'snake-game',
        'title': 'Build a Snake Game',
        'description': 'Classic snake on canvas with score and keyboard controls.',
        'mode': 'web-dev',
        'prompt': 'Build a Snake game with canvas rendering, arrow-key controls, score counter and game-over/restart.',
    },
    {
        'id': 'pomodoro-timer',
        'title': 'Create a Pomodoro Timer',
        'description': '25/5 focus timer with start/pause/reset and session counter.',
        'mode': 'web-dev',
        'prompt': 'Create a Pomodoro timer (25 min work / 5 min break) with start, pause, reset and completed-session count.',
    },
    {
        'id': 'coffee-shop',
        'title': 'Build a Coffee Shop',
        'description': 'Landing page for a coffee shop with menu and order form.',
        'mode': 'visual-design',
        'prompt': 'Build a cozy coffee shop landing page: hero, menu cards with prices, and an order contact form.',
    },
    {
        'id': 'solar-system',
        'title': 'Create a Solar System Demo',
        'description': 'Animated orbit demo of planets around the sun.',
        'mode': 'data-viz',
        'prompt': 'Create an animated solar system demo with orbiting planets, relative sizes and hover tooltips.',
    },
    {
        'id': 'todo-app',
        'title': 'Build a Todo List',
        'description': 'Task manager with add/complete/delete and localStorage.',
        'mode': 'prototype',
        'prompt': 'Build a todo list app with add, toggle-complete, delete and persistence in localStorage.',
    },
    {
        'id': 'weather-widget',
        'title': 'Create a Weather Widget',
        'description': 'Compact forecast card with mock data.',
        'mode': 'prototype',
        'prompt': 'Create a weather widget card showing current temp and 5-day forecast using realistic mock data.',
    },
]


def get_mode(mode_id: str | None) -> dict | None:
    if not mode_id:
        return None
    return MODES.get(mode_id.lower().strip())


def list_modes() -> list[dict]:
    return [{'id': k, **{f: v[f] for f in ('label', 'description')}} for k, v in MODES.items()]


def list_templates() -> list[dict]:
    return [{k: t[k] for k in ('id', 'title', 'description', 'mode', 'prompt')} for t in TEMPLATES]


def get_template(template_id: str) -> dict | None:
    for t in TEMPLATES:
        if t['id'] == template_id:
            return t
    return None


def skeleton_for(mode_id: str | None) -> dict:
    mode = get_mode(mode_id)
    if mode:
        return dict(mode['skeleton'])
    return dict(MODES['web-dev']['skeleton'])


def derive_title_and_tags(prompt: str) -> tuple[str, list[str]]:
    """§B3: быстрая эвристика без LLM для title/tags (используется как fallback)."""
    words = [w for w in prompt.replace('\n', ' ').split(' ') if w.strip()]
    stop = {'a', 'an', 'the', 'to', 'with', 'and', 'for', 'of', 'in', 'on', 'my', 'please', 'can', 'you'}
    title_words = []
    for w in words[:12]:
        clean = ''.join(c for c in w if c.isalnum() or c in "-_'")
        if clean and clean.lower() not in stop:
            title_words.append(clean.capitalize())
        if len(title_words) >= 6:
            break
    title = ' '.join(title_words) if title_words else (prompt[:48].strip() or 'New task')
    lowered = prompt.lower()
    tags = []
    keyword_map = {
        'game': ['gaming'],
        'timer': ['productivity'],
        'chart': ['charts'],
        'dashboard': ['dataviz'],
        'landing': ['design'],
        'todo': ['productivity'],
        'weather': ['api'],
        'css': ['frontend'],
        'react': ['react'],
        'python': ['python'],
        'canvas': ['graphics'],
        'animation': ['motion'],
    }
    for kw, t in keyword_map.items():
        if kw in lowered:
            tags.extend(t)
    tags = sorted(set(tags))[:5]
    if not tags:
        tags = ['general']
    return title[:80], tags


FOLLOWUP_SUGGESTIONS = [
    'Add dark mode toggle',
    'Make it responsive for mobile',
    'Add animations and transitions',
    'Write unit tests for the core logic',
    'Improve accessibility (ARIA labels)',
    'Deploy it to GitHub Pages',
]


def followup_suggestions(mode_id: str | None = None) -> list[str]:
    base = list(FOLLOWUP_SUGGESTIONS)
    if mode_id == 'data-viz':
        base.insert(0, 'Export the chart as PNG')
    elif mode_id == 'web-dev':
        base.insert(0, 'Add form validation')
    return base[:6]

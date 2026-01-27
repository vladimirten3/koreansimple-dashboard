"""
Веб-дашборд для просмотра задач.
MVP версия - только просмотр и отметка выполнения.
"""

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import aiosqlite
from datetime import datetime
from pathlib import Path
import re
from typing import List, Dict, Any, Optional
import secrets

# Генерируем токен доступа при первом запуске
ACCESS_TOKEN = "demo123"  # TODO: сохранять в .env

app = FastAPI(title="Task Dashboard")

DB_PATH = Path(__file__).parent.parent / "data" / "assistant.db"

# ============================================================================
# DATABASE
# ============================================================================

async def get_db():
    """Получить соединение с БД."""
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    return db


async def init_task_tables():
    """Создаёт таблицы для задач если их нет."""
    db = await get_db()
    
    # Таблица распарсенных задач
    await db.execute("""
        CREATE TABLE IF NOT EXISTS parsed_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_message_id INTEGER,
            title TEXT NOT NULL,
            description TEXT,
            assignee TEXT,
            due_date TEXT,
            status TEXT DEFAULT 'pending',
            project TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (source_message_id) REFERENCES messages(id)
        )
    """)
    
    # Таблица истории изменений
    await db.execute("""
        CREATE TABLE IF NOT EXISTS task_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            field_changed TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            changed_by TEXT,
            changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES parsed_tasks(id)
        )
    """)
    
    await db.commit()
    await db.close()


async def get_messages() -> List[Dict]:
    """Получить все сообщения."""
    db = await get_db()
    cursor = await db.execute("""
        SELECT DISTINCT text, sender_name, date, forward_from 
        FROM messages 
        ORDER BY date DESC
    """)
    rows = await cursor.fetchall()
    await db.close()
    
    return [dict(row) for row in rows]


async def get_parsed_tasks() -> List[Dict]:
    """Получить все распарсенные задачи."""
    db = await get_db()
    cursor = await db.execute("""
        SELECT * FROM parsed_tasks ORDER BY 
            CASE status 
                WHEN 'pending' THEN 0 
                WHEN 'in_progress' THEN 1 
                WHEN 'done' THEN 2 
            END,
            created_at DESC
    """)
    rows = await cursor.fetchall()
    await db.close()
    
    return [dict(row) for row in rows]


async def update_task_status(task_id: int, new_status: str, changed_by: str = "web"):
    """Обновить статус задачи с логированием."""
    db = await get_db()
    
    # Получаем текущий статус
    cursor = await db.execute("SELECT status FROM parsed_tasks WHERE id = ?", (task_id,))
    row = await cursor.fetchone()
    if not row:
        await db.close()
        raise HTTPException(status_code=404, detail="Task not found")
    
    old_status = row["status"]
    
    # Обновляем статус
    await db.execute("""
        UPDATE parsed_tasks 
        SET status = ?, updated_at = CURRENT_TIMESTAMP 
        WHERE id = ?
    """, (new_status, task_id))
    
    # Логируем изменение
    await db.execute("""
        INSERT INTO task_history (task_id, field_changed, old_value, new_value, changed_by)
        VALUES (?, 'status', ?, ?, ?)
    """, (task_id, old_status, new_status, changed_by))
    
    await db.commit()
    await db.close()


async def get_task_history(task_id: int) -> List[Dict]:
    """Получить историю изменений задачи."""
    db = await get_db()
    cursor = await db.execute("""
        SELECT * FROM task_history 
        WHERE task_id = ? 
        ORDER BY changed_at DESC
    """, (task_id,))
    rows = await cursor.fetchall()
    await db.close()
    
    return [dict(row) for row in rows]


def parse_tasks_from_text(text: str, sender: str) -> List[Dict]:
    """Извлекает задачи из текста сообщения с учётом смены ответственного."""
    tasks = []
    
    # Разбиваем текст на строки для анализа
    lines = text.strip().split('\n')
    
    # Определяем начального ответственного из первой строки
    first_line = lines[0] if lines else ""
    assignee_match = re.search(r'^@(\w+)', first_line)
    current_assignee = assignee_match.group(1) if assignee_match else None
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Проверяем смену ответственного
        # Формат: просто имя на отдельной строке (например "Вова")
        if re.match(r'^[А-Яа-яЁё]+$', line) and len(line) < 20:
            current_assignee = line
            continue
        
        # Формат: @username на отдельной строке
        username_match = re.match(r'^@(\w+)\s*$', line)
        if username_match:
            current_assignee = username_match.group(1)
            continue
        
        # Формат: @username в начале строки с текстом (не задача)
        if re.match(r'^@\w+\s+[а-яА-Яa-zA-Z]', line) and not re.match(r'^\d+\.', line):
            # Это может быть новый ответственный или просто комментарий
            new_assignee = re.match(r'^@(\w+)', line)
            if new_assignee:
                current_assignee = new_assignee.group(1)
            continue
        
        # Ищем нумерованную задачу: "1. текст задачи"
        task_match = re.match(r'^(\d+)\.\s*(.+)$', line)
        if task_match:
            task_num = task_match.group(1)
            task_text = task_match.group(2).strip()
            
            if task_text:
                tasks.append({
                    "title": task_text[:200],
                    "assignee": current_assignee,
                    "description": None,
                    "due_date": None,
                    "status": "pending",
                    "project": None,
                })
    
    return tasks


async def parse_and_save_tasks():
    """Парсит задачи из сообщений и сохраняет в БД с дедупликацией."""
    db = await get_db()
    
    # Получаем все сообщения
    cursor = await db.execute("""
        SELECT DISTINCT m.id, m.text, m.sender_name, m.date 
        FROM messages m
        WHERE m.text IS NOT NULL AND m.text != ''
        ORDER BY m.date DESC
    """)
    messages = await cursor.fetchall()
    
    # Получаем уже существующие задачи для дедупликации
    existing_cursor = await db.execute("SELECT LOWER(title) as title FROM parsed_tasks")
    existing_rows = await existing_cursor.fetchall()
    existing_titles = {row["title"] for row in existing_rows}
    
    count = 0
    seen_in_this_run = set()  # Дедупликация внутри текущего запуска
    
    for msg in messages:
        tasks = parse_tasks_from_text(msg["text"], msg["sender_name"])
        for task in tasks:
            title_lower = task["title"].lower().strip()
            
            # Пропускаем если уже есть такая задача
            if title_lower in existing_titles or title_lower in seen_in_this_run:
                continue
            
            seen_in_this_run.add(title_lower)
            
            await db.execute("""
                INSERT INTO parsed_tasks 
                (source_message_id, title, assignee, description, due_date, status, project)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                msg["id"], 
                task["title"], 
                task["assignee"],
                task["description"],
                task["due_date"],
                task["status"],
                task["project"],
            ))
            count += 1
    
    await db.commit()
    await db.close()
    return count


# ============================================================================
# HTML TEMPLATES
# ============================================================================

def render_dashboard(tasks: List[Dict], messages: List[Dict], message: str = None) -> str:
    """Рендерит HTML дашборда."""
    
    # Группируем задачи по статусу
    pending = [t for t in tasks if t["status"] == "pending"]
    in_progress = [t for t in tasks if t["status"] == "in_progress"]
    done = [t for t in tasks if t["status"] == "done"]
    
    def render_task_row(task: Dict) -> str:
        status_class = {
            "pending": "bg-yellow-100",
            "in_progress": "bg-blue-100", 
            "done": "bg-green-100 line-through opacity-60"
        }.get(task["status"], "")
        
        status_emoji = {
            "pending": "⏳",
            "in_progress": "🔄",
            "done": "✅"
        }.get(task["status"], "")
        
        assignee = task["assignee"] or "-"
        due_date = task["due_date"] or "-"
        
        buttons = ""
        if task["status"] != "done":
            buttons = f'''
                <form method="POST" action="/task/{task["id"]}/status" class="inline">
                    <input type="hidden" name="status" value="done">
                    <button type="submit" class="px-2 py-1 bg-green-500 text-white rounded text-sm hover:bg-green-600">
                        ✓ Готово
                    </button>
                </form>
            '''
        if task["status"] == "pending":
            buttons += f'''
                <form method="POST" action="/task/{task["id"]}/status" class="inline ml-1">
                    <input type="hidden" name="status" value="in_progress">
                    <button type="submit" class="px-2 py-1 bg-blue-500 text-white rounded text-sm hover:bg-blue-600">
                        ▶ В работе
                    </button>
                </form>
            '''
        
        return f'''
            <tr class="{status_class}">
                <td class="px-4 py-2 border">{status_emoji}</td>
                <td class="px-4 py-2 border">{task["title"]}</td>
                <td class="px-4 py-2 border">@{assignee}</td>
                <td class="px-4 py-2 border">{due_date}</td>
                <td class="px-4 py-2 border">{buttons}</td>
            </tr>
        '''
    
    task_rows = "\n".join(render_task_row(t) for t in tasks)
    
    # Сообщение-уведомление
    message_html = ""
    if message:
        message_html = f'''
            <div class="mb-4 p-4 bg-green-100 border border-green-400 text-green-700 rounded">
                {message}
            </div>
        '''
    
    return f'''
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📋 Задачи</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 min-h-screen">
    <div class="container mx-auto px-4 py-8">
        <header class="mb-8">
            <h1 class="text-3xl font-bold text-gray-800">📋 Дашборд задач</h1>
            <p class="text-gray-600">Задачи собранные из Telegram</p>
        </header>
        
        {message_html}
        
        <!-- Статистика -->
        <div class="grid grid-cols-3 gap-4 mb-8">
            <div class="bg-yellow-100 p-4 rounded-lg text-center">
                <div class="text-3xl font-bold text-yellow-700">{len(pending)}</div>
                <div class="text-yellow-600">⏳ Ожидают</div>
            </div>
            <div class="bg-blue-100 p-4 rounded-lg text-center">
                <div class="text-3xl font-bold text-blue-700">{len(in_progress)}</div>
                <div class="text-blue-600">🔄 В работе</div>
            </div>
            <div class="bg-green-100 p-4 rounded-lg text-center">
                <div class="text-3xl font-bold text-green-700">{len(done)}</div>
                <div class="text-green-600">✅ Выполнено</div>
            </div>
        </div>
        
        <!-- Кнопки управления -->
        <div class="mb-4 flex gap-2">
            <form method="POST" action="/parse">
                <button type="submit" class="px-4 py-2 bg-purple-500 text-white rounded hover:bg-purple-600">
                    🔄 Обновить из Telegram
                </button>
            </form>
            <a href="/export/csv" class="px-4 py-2 bg-green-500 text-white rounded hover:bg-green-600 inline-block">
                📥 Скачать CSV
            </a>
        </div>
        
        <!-- Таблица задач -->
        <div class="bg-white rounded-lg shadow overflow-hidden">
            <table class="w-full">
                <thead class="bg-gray-200">
                    <tr>
                        <th class="px-4 py-3 text-left">Статус</th>
                        <th class="px-4 py-3 text-left">Задача</th>
                        <th class="px-4 py-3 text-left">Ответственный</th>
                        <th class="px-4 py-3 text-left">Срок</th>
                        <th class="px-4 py-3 text-left">Действия</th>
                    </tr>
                </thead>
                <tbody>
                    {task_rows if task_rows else '<tr><td colspan="5" class="px-4 py-8 text-center text-gray-500">Нет задач. Нажмите "Обновить задачи из Telegram"</td></tr>'}
                </tbody>
            </table>
        </div>
        
        <!-- Исходные сообщения -->
        <details class="mt-8">
            <summary class="cursor-pointer text-gray-600 hover:text-gray-800">
                📨 Исходные сообщения ({len(messages)})
            </summary>
            <div class="mt-4 bg-white rounded-lg shadow p-4">
                {"".join(f'<div class="mb-4 p-3 bg-gray-50 rounded"><div class="text-sm text-gray-500">{m["sender_name"]} • {m["date"]}</div><div class="mt-1">{m["text"]}</div></div>' for m in messages)}
            </div>
        </details>
        
        <footer class="mt-8 text-center text-gray-500 text-sm">
            Обновлено: {datetime.now().strftime("%d.%m.%Y %H:%M")}
        </footer>
    </div>
</body>
</html>
    '''


# ============================================================================
# ROUTES
# ============================================================================

@app.on_event("startup")
async def startup():
    """Инициализация при запуске."""
    await init_task_tables()


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, msg: str = None):
    """Главная страница дашборда."""
    tasks = await get_parsed_tasks()
    messages = await get_messages()
    return render_dashboard(tasks, messages, message=msg)


@app.post("/parse")
async def parse_tasks():
    """Парсит задачи из новых сообщений."""
    count = await parse_and_save_tasks()
    return RedirectResponse(url=f"/?msg=Добавлено задач: {count}", status_code=303)


@app.get("/export/csv")
async def export_csv():
    """Экспорт задач в CSV для Google Sheets."""
    from fastapi.responses import Response
    import csv
    import io
    
    tasks = await get_parsed_tasks()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Заголовки
    writer.writerow(["Задача", "Ответственный", "Статус", "Дата создания"])
    
    # Данные
    for task in tasks:
        status_ru = {"pending": "Ожидает", "in_progress": "В работе", "done": "Готово"}.get(task["status"], task["status"])
        writer.writerow([
            task["title"],
            task["assignee"] or "-",
            status_ru,
            task["created_at"][:10] if task["created_at"] else "-",
        ])
    
    content = output.getvalue()
    
    return Response(
        content=content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=tasks_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        }
    )


@app.post("/task/{task_id}/status")
async def change_status(task_id: int, status: str = Form(...)):
    """Меняет статус задачи."""
    await update_task_status(task_id, status)
    return RedirectResponse(url="/?msg=Статус обновлён", status_code=303)


@app.get("/task/{task_id}/history", response_class=HTMLResponse)
async def task_history(task_id: int):
    """История изменений задачи."""
    history = await get_task_history(task_id)
    
    rows = "\n".join(f'''
        <tr>
            <td class="px-4 py-2 border">{h["changed_at"]}</td>
            <td class="px-4 py-2 border">{h["field_changed"]}</td>
            <td class="px-4 py-2 border">{h["old_value"]} → {h["new_value"]}</td>
            <td class="px-4 py-2 border">{h["changed_by"]}</td>
        </tr>
    ''' for h in history)
    
    return f'''
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>История задачи #{task_id}</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 p-8">
    <h1 class="text-2xl font-bold mb-4">История изменений задачи #{task_id}</h1>
    <a href="/" class="text-blue-500 hover:underline mb-4 block">← Назад</a>
    <table class="w-full bg-white rounded shadow">
        <thead class="bg-gray-200">
            <tr>
                <th class="px-4 py-2">Дата</th>
                <th class="px-4 py-2">Поле</th>
                <th class="px-4 py-2">Изменение</th>
                <th class="px-4 py-2">Кто</th>
            </tr>
        </thead>
        <tbody>{rows if rows else '<tr><td colspan="4" class="px-4 py-8 text-center">Нет истории</td></tr>'}</tbody>
    </table>
</body>
</html>
    '''


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)

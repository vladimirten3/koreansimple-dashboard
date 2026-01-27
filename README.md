# 📊 Дашборд продаж KoreanSimple

Динамический веб-дашборд с автообновлением данных из AmoCRM через Supabase.

## 🚀 Деплой за 5 минут

### Перед началом убедитесь что у вас есть:

- ✅ Аккаунт в [Supabase](https://supabase.com)
- ✅ Установлен [Vercel CLI](https://vercel.com/download)
- ✅ Python 3.10+

### Шаги деплоя:

```bash
# 1. Выполните SQL в Supabase
# Откройте ../supabase_setup.sql и выполните в Supabase SQL Editor

# 2. Получите ключи Supabase
# Settings → API → скопируйте URL и ключи

# 3. Обновите конфиг в index.html
# Замените YOUR_SUPABASE_URL и YOUR_SUPABASE_ANON_KEY на реальные

# 4. Загрузите данные в Supabase
cd ..
pip install supabase
python3 scripts/amocrm/upload_to_supabase.py

# 5. Деплой на Vercel
cd web_dashboard
vercel --prod
```

## 📁 Структура файлов

```
web_dashboard/
├── index.html       # Главная страница дашборда (деплоится на Vercel)
├── vercel.json      # Конфигурация для Vercel
├── app.py          # FastAPI приложение (опционально, для локальной разработки)
└── README.md       # Этот файл
```

## 🔧 Локальная разработка

Для локального тестирования просто откройте `index.html` в браузере:

```bash
# Mac
open index.html

# Windows
start index.html

# Linux
xdg-open index.html
```

Или запустите простой HTTP сервер:

```bash
# Python
python3 -m http.server 8000

# Затем откройте http://localhost:8000
```

## 📊 Что показывает дашборд

- **Общая статистика**: количество сделок, сумма, конверсия
- **График по дням**: динамика создания сделок
- **График по менеджерам**: производительность команды
- **Источники лидов**: откуда приходят клиенты

## 🔄 Обновление данных

### Ручное обновление

```bash
python3 scripts/amocrm/upload_to_supabase.py
```

### Автоматическое обновление

См. раздел "Автоматическое обновление данных" в `../DEPLOYMENT_GUIDE.md`

## 🎨 Кастомизация

Все графики используют Plotly.js. Вы можете кастомизировать:
- Цвета графиков
- Типы визуализаций
- Метрики и расчеты
- Фильтры данных

## 🔒 Безопасность

- Используйте `anon` ключ в фронтенде (публичный доступ только на чтение)
- `service_role` ключ используйте только в backend скриптах (полный доступ)
- Не коммитьте `.env` файл в git

## 🆘 Проблемы?

См. раздел "Устранение проблем" в `../DEPLOYMENT_GUIDE.md`

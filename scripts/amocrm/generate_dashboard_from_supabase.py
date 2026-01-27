#!/usr/bin/env python3
"""
Генерация дашборда из данных Supabase
Адаптирует существующий дашборд для работы с Supabase
"""

import os
import json
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client

# Загрузка .env
root_dir = Path(__file__).parent.parent.parent
load_dotenv(root_dir / '.env')

# Инициализация Supabase
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ Не заданы SUPABASE_URL или SUPABASE_SERVICE_KEY")
    exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Пути
DATA_DIR = root_dir / 'data' / 'analytics'
OUTPUT_DIR = root_dir / 'web_dashboard'
TEMPLATE_FILE = DATA_DIR / 'sales-dashboard.html'

STATUS_SUCCESS = 142
STATUS_LOST = 143


def convert_supabase_to_dashboard_format(supabase_deals):
    """Преобразует данные из Supabase в формат для дашборда"""
    dashboard_deals = []
    
    # Создаем маппинг имени менеджера на уникальный ID
    manager_name_to_id = {}
    next_manager_id = 1000000  # Начинаем с большого числа, чтобы не конфликтовать с реальными ID
    
    for deal in supabase_deals:
        # Преобразуем дату из ISO в timestamp
        created_at = 0
        closed_at = None
        
        if deal.get('created_date'):
            try:
                dt = datetime.fromisoformat(deal['created_date'].replace('Z', '+00:00'))
                created_at = int(dt.timestamp())
            except:
                pass
        
        if deal.get('closed_date'):
            try:
                dt = datetime.fromisoformat(deal['closed_date'].replace('Z', '+00:00'))
                closed_at = int(dt.timestamp())
            except:
                pass
        
        # Используем status_id из базы, если есть
        status_id = deal.get('status_id')
        if status_id is None:
            # Определяем status_id на основе статуса и цены
            status = deal.get('status', '').upper()
            price = deal.get('price', 0) or 0
            
            # Если цена > 0, считаем успешной
            if price > 0:
                status_id = STATUS_SUCCESS
            elif 'закрыт' in status.lower() or 'не реализован' in status.lower():
                status_id = STATUS_LOST
            else:
                status_id = None  # Активная сделка
        
        # Для успешных сделок, если нет closed_at, используем created_at
        if status_id == STATUS_SUCCESS and closed_at is None and created_at > 0:
            closed_at = created_at
        
        # Маппинг менеджера по имени
        responsible_user_id = None
        manager_name = deal.get('responsible_user')
        if manager_name:
            if manager_name not in manager_name_to_id:
                manager_name_to_id[manager_name] = next_manager_id
                next_manager_id += 1
            responsible_user_id = manager_name_to_id[manager_name]
        
        dashboard_deal = {
            'id': int(deal.get('deal_id', 0)) if deal.get('deal_id') else deal.get('id', 0),
            'name': deal.get('name', 'Новая сделка'),
            'price': deal.get('price', 0) or 0,
            'status_id': status_id,
            'created_at': created_at,
            'closed_at': closed_at,
            'responsible_user_id': responsible_user_id,
            'responsible_user_name': manager_name,
            'product': deal.get('learning_goal') or 'Не указан',
            'country': deal.get('country') or 'Не указана',
            'loss_reason': deal.get('loss_reason'),
            'link': f"https://koreansimple.amocrm.ru/leads/detail/{deal.get('deal_id') or deal.get('id')}",
            'source': deal.get('source') or deal.get('traffic_source'),
            'pipeline': deal.get('pipeline'),
            'contact_name': deal.get('contact_name'),
            'email': deal.get('email'),
            'phone': deal.get('phone'),
        }
        
        dashboard_deals.append(dashboard_deal)
    
    return dashboard_deals, manager_name_to_id


def generate_dashboard():
    """Генерирует дашборд с данными из Supabase"""
    
    print("📊 Загрузка данных из Supabase...")
    
    # Загружаем все сделки (без лимита)
    # Supabase по умолчанию возвращает 1000 записей, нужно загружать пакетами
    all_deals = []
    page_size = 1000
    offset = 0
    
    while True:
        result = supabase.table('deals').select('*').range(offset, offset + page_size - 1).execute()
        batch = result.data
        if not batch:
            break
        all_deals.extend(batch)
        offset += page_size
        if len(batch) < page_size:
            break
    
    supabase_deals = all_deals
    print(f"✅ Загружено {len(supabase_deals)} сделок")
    
    # Преобразуем в формат дашборда
    dashboard_deals, manager_name_to_id = convert_supabase_to_dashboard_format(supabase_deals)
    print(f"👥 Найдено {len(manager_name_to_id)} уникальных менеджеров")
    
    # Загружаем шаблон
    print("📖 Загрузка шаблона дашборда...")
    if not TEMPLATE_FILE.exists():
        print(f"❌ Шаблон не найден: {TEMPLATE_FILE}")
        return None
    
    with open(TEMPLATE_FILE, 'r', encoding='utf-8') as f:
        template = f.read()
    
    # Заменяем данные в шаблоне
    # Ищем строку с const allDeals = [...]
    import re
    
    # Формируем JSON для вставки
    deals_json = json.dumps(dashboard_deals, ensure_ascii=False, indent=12)
    
    # Создаем маппинг usersMapping для обратной совместимости
    # usersMapping[manager_id] = manager_name
    users_mapping = {str(v): k for k, v in manager_name_to_id.items()}
    users_mapping_json = json.dumps(users_mapping, ensure_ascii=False, indent=12)
    
    # Заменяем данные в шаблоне
    pattern = r'const allDeals = \[.*?\];'
    replacement = f'const allDeals = {deals_json};'
    
    new_template = re.sub(pattern, replacement, template, flags=re.DOTALL)
    
    # Если не нашли паттерн, ищем другой вариант
    if new_template == template:
        # Ищем где данные встроены
        pattern2 = r'(const allDeals = )\[.*?(\];)'
        replacement2 = f'\\1{deals_json}\\2'
        new_template = re.sub(pattern2, replacement2, template, flags=re.DOTALL)
    
    # Обновляем usersMapping, если он есть в шаблоне
    users_mapping_pattern = r'const usersMapping = \{.*?\};'
    users_mapping_replacement = f'const usersMapping = {users_mapping_json};'
    new_template = re.sub(users_mapping_pattern, users_mapping_replacement, new_template, flags=re.DOTALL)
    
    # Если usersMapping не найден, добавляем его после allDeals
    if 'const usersMapping' not in new_template:
        # Ищем место после const allDeals
        insert_pattern = r'(const allDeals = [^;]+;)'
        insert_replacement = f'\\1\n        const usersMapping = {users_mapping_json};'
        new_template = re.sub(insert_pattern, insert_replacement, new_template, flags=re.DOTALL)
    
    # Сохраняем
    OUTPUT_DIR.mkdir(exist_ok=True)
    output_file = OUTPUT_DIR / 'index.html'
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(new_template)
    
    print(f"✅ Дашборд сохранен: {output_file}")
    print(f"📊 Всего сделок в дашборде: {len(dashboard_deals)}")
    total_sum = sum(d.get("price", 0) for d in dashboard_deals)
    print(f"💰 Сумма: {total_sum:,} ₩")
    
    return output_file


if __name__ == '__main__':
    print("=" * 60)
    print("🚀 Генерация дашборда из Supabase")
    print("=" * 60)
    
    try:
        output_file = generate_dashboard()
        if output_file:
            print("=" * 60)
            print("✨ Готово! Дашборд сгенерирован")
            print(f"📁 Файл: {output_file}")
            print("=" * 60)
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        exit(1)

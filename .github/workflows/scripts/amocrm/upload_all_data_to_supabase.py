#!/usr/bin/env python3
"""
Загрузка ВСЕХ данных из sales_data.json в Supabase
"""

import os
import json
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client

# Загрузка .env
root_dir = Path(__file__).parent.parent.parent
load_dotenv(root_dir / '.env')

# Инициализация Supabase
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ Не заданы SUPABASE_URL или SUPABASE_SERVICE_KEY")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

DATA_DIR = root_dir / 'data' / 'analytics'
SALES_DATA_FILE = DATA_DIR / 'sales_data.json'

STATUS_SUCCESS = 142
STATUS_LOST = 143


def convert_deal_to_supabase_format(deal):
    """Преобразует сделку из формата sales_data.json в формат Supabase"""
    
    # Преобразуем timestamp в ISO дату
    created_at_ts = deal.get('created_at', 0)
    closed_at_ts = deal.get('closed_at')
    
    created_date = None
    if created_at_ts:
        try:
            created_date = datetime.fromtimestamp(created_at_ts).isoformat()
        except:
            pass
    
    closed_date = None
    if closed_at_ts:
        try:
            closed_date = datetime.fromtimestamp(closed_at_ts).isoformat()
        except:
            pass
    
    # Получаем имя менеджера
    responsible_user = None
    if deal.get('responsible_user_name'):
        responsible_user = deal['responsible_user_name']
    elif deal.get('responsible_user_id'):
        responsible_user = f"User_{deal['responsible_user_id']}"
    
    # Определяем статус
    status_id = deal.get('status_id')
    status = None
    if status_id == 142:
        status = "Успешно реализовано"
    elif status_id == 143:
        status = "Закрыто и не реализовано"
    else:
        status = deal.get('status', 'Активная')
    
    supabase_deal = {
        'deal_id': str(deal.get('id', '')),
        'name': deal.get('name', 'Новая сделка'),
        'price': deal.get('price', 0) or 0,
        'responsible_user': responsible_user,
        'created_date': created_date,
        'closed_date': closed_date,
        'status': status,
        'status_id': status_id,
        'pipeline': deal.get('pipeline', ''),
        'contact_name': deal.get('contact_name', ''),
        'phone': deal.get('phone', ''),
        'email': deal.get('email', ''),
        'source': deal.get('source', ''),
        'traffic_source': deal.get('traffic_source', ''),
        'country': deal.get('country', ''),
        'age_group': deal.get('age_group', ''),
        'learning_goal': deal.get('product', ''),
        'knowledge_level': deal.get('knowledge_level', ''),
        'tags': deal.get('tags', ''),
        'notes': deal.get('notes', ''),
        'loss_reason': deal.get('loss_reason', ''),
        'utm_source': deal.get('utm_source', ''),
        'utm_medium': deal.get('utm_medium', ''),
        'utm_campaign': deal.get('utm_campaign', ''),
        'created_at': datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat()
    }
    
    return supabase_deal


def load_all_deals():
    """Загружает все сделки из sales_data.json"""
    print(f"📖 Загрузка данных из {SALES_DATA_FILE}...")
    
    if not SALES_DATA_FILE.exists():
        print(f"❌ Файл не найден: {SALES_DATA_FILE}")
        return []
    
    with open(SALES_DATA_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Обрабатываем разные форматы
    if isinstance(data, list):
        deals = data
    elif isinstance(data, dict):
        deals = data.get('deals', [])
    else:
        print("❌ Неизвестный формат данных")
        return []
    
    print(f"✅ Загружено {len(deals)} сделок из JSON")
    return deals


def upload_to_supabase(deals):
    """Загружает сделки в Supabase пакетами"""
    
    print("🗑️  Очистка старых данных...")
    try:
        # Удаляем все существующие записи
        supabase.table('deals').delete().neq('id', 0).execute()
    except Exception as e:
        print(f"⚠️  Ошибка при очистке: {e}")
    
    # Преобразуем в формат Supabase
    print("🔄 Преобразование данных...")
    supabase_deals = []
    for deal in deals:
        try:
            supabase_deal = convert_deal_to_supabase_format(deal)
            supabase_deals.append(supabase_deal)
        except Exception as e:
            print(f"⚠️  Ошибка при преобразовании сделки {deal.get('id')}: {e}")
            continue
    
    print(f"✅ Преобразовано {len(supabase_deals)} сделок")
    
    # Загружаем пакетами по 500 записей
    batch_size = 500
    total = len(supabase_deals)
    
    print(f"📤 Загрузка {total} сделок в Supabase...")
    
    for i in range(0, total, batch_size):
        batch = supabase_deals[i:i+batch_size]
        try:
            supabase.table('deals').insert(batch).execute()
            print(f"✅ Загружено {min(i+batch_size, total)}/{total}")
        except Exception as e:
            print(f"❌ Ошибка при загрузке пакета {i}-{i+batch_size}: {e}")
    
    print("✨ Загрузка завершена!")


def main():
    print("=" * 60)
    print("📊 Загрузка ВСЕХ данных в Supabase")
    print("=" * 60)
    
    # Загружаем данные
    deals = load_all_deals()
    
    if not deals:
        print("❌ Нет данных для загрузки")
        return
    
    # Загружаем в Supabase
    upload_to_supabase(deals)
    
    print("=" * 60)
    print("✨ Готово! Все данные загружены в Supabase")
    print("=" * 60)


if __name__ == '__main__':
    main()

"""
从价格变化表导入记录到数据库
文件: 价格变化_2026-03-04.xlsx (无标题行)
"""
import pandas as pd
import pymysql
import pymysql.cursors
import json
import os
import re
from datetime import datetime, date, timedelta
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

MAX_VALID_DATE = date(9999, 12, 31)
BATCH_SIZE = 500
NUM_WORKERS = max(4, multiprocessing.cpu_count() - 1)

EXCEL_FILE = r'd:\Work\dunhill\product\调价清单\价格变动表\价格变化_2026-03-04.xlsx'

# 列定义: spu, name, validFrom, validTo, rsp, category
COLUMN_NAMES = ['spu', 'name', 'validFrom', 'validTo', 'rsp', 'category']
HEADER_ROW = 0  # 第一行是标题


def to_date(dt):
    if pd.isna(dt) or dt is None:
        return MAX_VALID_DATE
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return dt
    if hasattr(dt, 'date'):
        return dt.date()
    if isinstance(dt, str):
        if '9999' in dt:
            return MAX_VALID_DATE
        parts = dt.split('-')
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    return date(dt.year, dt.month, dt.day)


def load_db_config():
    db_config_path = os.path.join(os.path.expanduser('~'), 'database_config.json')
    with open(db_config_path, 'r', encoding='utf-8') as f:
        content = f.read()
        content = re.sub(r'^\s*//.*$', '', content, flags=re.MULTILINE)
        db_config_json = json.loads(content)
        for db in db_config_json['databases']:
            if db['name'] == 'Aliyun DB':
                return {
                    'host': db['host'],
                    'user': db['user'],
                    'password': db['password'],
                    'database': db['database'],
                    'port': db.get('port', 3306),
                    'charset': 'utf8mb4'
                }
    return None


def check_overlap_with_db(new_from, new_to, db_records):
    for rec in db_records:
        db_from = rec['validFrom']
        db_to = rec['validTo']
        if new_from <= db_to and db_from <= new_to:
            return True, f"[{new_from}~{new_to}] 与 [{db_from}~{db_to}] 重叠"
    return False, None


def insert_batch(batch, db_config):
    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()
    insert_sql = '''
    INSERT INTO dunhill_价格源 (category, spu, name, validFrom, validTo, rsp)
    VALUES (%s, %s, %s, %s, %s, %s)
    '''
    inserted = 0
    errors = 0
    error_msgs = []
    for rec in batch:
        try:
            cursor.execute(insert_sql, (
                rec['category'], rec['spu'], rec['name'],
                rec['validFrom'], rec['validTo'], rec['rsp']
            ))
            inserted += 1
        except Exception as e:
            errors += 1
            if len(error_msgs) < 3:
                error_msgs.append(str(e))
    conn.commit()
    cursor.close()
    conn.close()
    return inserted, errors, error_msgs


def main():
    print('=' * 60)
    print('从价格变化表导入记录')
    print('=' * 60)

    if not os.path.exists(EXCEL_FILE):
        print(f'错误: 文件不存在 - {EXCEL_FILE}')
        return

    print(f'\n文件: {os.path.basename(EXCEL_FILE)}')

    db_config = load_db_config()

    # 获取数据库现有记录
    print('\n连接数据库...')
    conn = pymysql.connect(**db_config)
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute('SELECT spu, validFrom, validTo FROM dunhill_价格源')
    db_records_by_spu = defaultdict(list)
    existing_keys = set()

    for r in cursor.fetchall():
        spu = r['spu']
        db_records_by_spu[spu].append({
            'validFrom': r['validFrom'],
            'validTo': r['validTo']
        })
        existing_keys.add((spu, str(r['validFrom']), str(r['validTo'])))

    print(f'  数据库现有记录: {sum(len(v) for v in db_records_by_spu.values())} 条')
    cursor.close()
    conn.close()

    # 读取Excel - 有标题行
    print('\n读取Excel...')
    df = pd.read_excel(EXCEL_FILE, header=HEADER_ROW)
    print(f'  原始数据: {len(df)} 行')
    print(f'  列: {list(df.columns)}')

    # 筛选有效数据
    df['rsp'] = pd.to_numeric(df['rsp'], errors='coerce')
    df = df[df['rsp'].notna() & (df['rsp'] > 0)]
    print(f'  筛选有效价格后: {len(df)} 行')

    # 检查记录
    print('\n检查记录...')
    new_records = []
    skipped_existing = 0
    skipped_overlap = []

    for idx, row in df.iterrows():
        spu = str(row['spu']).strip() if pd.notna(row['spu']) else ''
        if not spu:
            continue

        valid_from = to_date(row['validFrom'])
        valid_to = to_date(row['validTo'])
        key = (spu, str(valid_from), str(valid_to))

        # 检查是否已存在
        if key in existing_keys:
            skipped_existing += 1
            continue

        # 检查日期重叠
        if spu in db_records_by_spu:
            has_overlap, desc = check_overlap_with_db(valid_from, valid_to, db_records_by_spu[spu])
            if has_overlap:
                skipped_overlap.append({'spu': spu, 'desc': desc})
                continue

        new_records.append({
            'category': str(row['category']) if pd.notna(row['category']) else '',
            'spu': spu,
            'name': str(row['name']) if pd.notna(row['name']) else '',
            'validFrom': valid_from,
            'validTo': valid_to,
            'rsp': float(row['rsp'])
        })

    print(f'  已存在（跳过）: {skipped_existing} 条')
    print(f'  日期重叠（跳过）: {len(skipped_overlap)} 条')
    print(f'  可导入: {len(new_records)} 条')

    if skipped_overlap:
        print('\n  重叠详情:')
        for item in skipped_overlap[:5]:
            print(f'    SPU={item["spu"]}, {item["desc"]}')
        if len(skipped_overlap) > 5:
            print(f'    ... 还有 {len(skipped_overlap) - 5} 条')

    if len(new_records) == 0:
        print('\n没有记录需要导入')
        return

    # 导入
    batches = [new_records[i:i + BATCH_SIZE] for i in range(0, len(new_records), BATCH_SIZE)]
    print(f'\n开始导入 {len(new_records)} 条记录...')
    print(f'使用 {NUM_WORKERS} 个进程并发导入')

    total_inserted = 0
    total_errors = 0
    all_error_msgs = []

    with ProcessPoolExecutor(max_workers=NUM_WORKERS) as executor:
        futures = {
            executor.submit(insert_batch, batch, db_config): i
            for i, batch in enumerate(batches)
        }
        for future in as_completed(futures):
            batch_idx = futures[future]
            try:
                inserted, errors, error_msgs = future.result()
                total_inserted += inserted
                total_errors += errors
                all_error_msgs.extend(error_msgs)
                print(f'  批次 {batch_idx + 1}/{len(batches)} 完成，成功 {inserted} 条')
            except Exception as e:
                print(f'  批次 {batch_idx} 失败: {e}')

    print(f'\n导入完成:')
    print(f'  成功: {total_inserted} 条')
    print(f'  错误: {total_errors} 条')

    if all_error_msgs:
        print('\n错误详情:')
        for msg in all_error_msgs[:5]:
            print(f'  {msg}')

    # 验证
    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM dunhill_价格源')
    total = cursor.fetchone()[0]
    cursor.close()
    conn.close()

    print(f'\n数据库总记录: {total} 条')
    print('=' * 60)


if __name__ == '__main__':
    main()

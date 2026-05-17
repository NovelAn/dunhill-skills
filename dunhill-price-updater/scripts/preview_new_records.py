"""
预览新增记录 - 在执行价格更新前验证是否有需要导入的记录

用法:
    python preview_new_records.py                    # 使用最新价格文件
    python preview_new_records.py --file PRICE_20251218.xlsx  # 指定文件

输出:
    在价格文件目录下生成 new_records_preview.csv 文件
"""
import pandas as pd
import pymysql
import pymysql.cursors
import json
import os
import re
import glob
import yaml
from datetime import datetime, date
from collections import defaultdict
from typing import Set, Dict, List, Optional


# 需要排除的SKC编码列表（与主脚本保持一致）
EXCLUDED_SKC_CODES = {
    'DU1AB575211',
    'DU1AB575216',
    'DU1AB575221',
    'DU1DBFB5211',
    'DU1DBFB5216',
    'DU1DBFB5221',
}

MAX_VALID_DATE = date(9999, 12, 31)


def load_config():
    """加载配置文件"""
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "config", "price-config.yaml"
    )
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_db_config() -> Optional[Dict]:
    """加载数据库配置"""
    config_path = os.path.join(os.path.expanduser('~'), 'database_config.json')
    with open(config_path, 'r', encoding='utf-8') as f:
        content = f.read()
        # Remove comments from JSON
        content_no_comments = re.sub(r'^\s*//.*$', '', content, flags=re.MULTILINE)
        config = json.loads(content_no_comments)

    for db in config.get('databases', []):
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


def find_latest_price_file(config) -> str:
    """查找最新的价格文件"""
    directory = config['price_files']['directory']
    pattern = config['price_files']['pattern']
    search_pattern = os.path.join(directory, pattern)
    files = glob.glob(search_pattern)

    if not files:
        raise FileNotFoundError(f"未找到价格文件: {search_pattern}")

    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]


def is_spu(product_name) -> bool:
    """判断是否为SPU记录"""
    if pd.isna(product_name):
        return False
    parts = [p.strip() for p in str(product_name).split(',')]
    return len(parts) == 1


def to_date(dt) -> Optional[date]:
    """转换为日期对象"""
    if pd.isna(dt) or dt is None:
        return None
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return dt
    if hasattr(dt, 'date'):
        return dt.date()
    return date(dt.year, dt.month, dt.day)


def clean_overlapping_records(df: pd.DataFrame) -> pd.DataFrame:
    """清理重叠记录，保留高价"""
    by_spu = defaultdict(list)
    for idx, row in df.iterrows():
        by_spu[row['spu']].append((idx, row))

    records_to_delete = set()

    for spu, rows in by_spu.items():
        if len(rows) <= 1:
            continue

        sorted_rows = sorted(rows, key=lambda x: to_date(x[1]['CON - Valid From']))

        for i in range(len(sorted_rows) - 1):
            idx_i, row_i = sorted_rows[i]
            price_i = float(row_i['ZRSP'])
            valid_to_i = to_date(row_i['CON - Valid To'])

            for j in range(i + 1, len(sorted_rows)):
                idx_j, row_j = sorted_rows[j]
                price_j = float(row_j['ZRSP'])
                valid_from_j = to_date(row_j['CON - Valid From'])

                # Check overlap
                has_overlap = False
                if valid_to_i == MAX_VALID_DATE:
                    has_overlap = True
                elif valid_from_j <= valid_to_i:
                    has_overlap = True

                if has_overlap:
                    if price_i >= price_j:
                        records_to_delete.add(idx_j)
                    else:
                        records_to_delete.add(idx_i)
                        break

    return df.drop(index=list(records_to_delete))


def get_existing_records(db_config: Dict) -> Set[tuple]:
    """获取数据库中现有记录的复合键集合"""
    conn = pymysql.connect(**db_config)
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute('SELECT spu, validFrom, validTo FROM dunhill_价格源')
    existing = set()
    for r in cursor.fetchall():
        key = (r['spu'], str(r['validFrom']), str(r['validTo']))
        existing.add(key)

    cursor.close()
    conn.close()
    return existing


def main():
    import argparse
    parser = argparse.ArgumentParser(description='预览新增价格记录')
    parser.add_argument('--file', type=str, help='指定价格文件名')
    args = parser.parse_args()

    print('=' * 60)
    print('预览新增价格记录')
    print('=' * 60)

    # 加载配置
    config = load_config()

    # 确定价格文件
    if args.file:
        file_path = os.path.join(config['price_files']['directory'], args.file)
    else:
        file_path = find_latest_price_file(config)

    print(f'价格文件: {os.path.basename(file_path)}')
    print()

    # 读取Excel
    print('读取Excel...')
    df = pd.read_excel(file_path, header=2)
    print(f'  原始数据: {len(df)} 行')

    # 筛选SPU记录
    df = df[df['Product - Name'].apply(is_spu)]
    print(f'  筛选SPU记录后: {len(df)} 行')

    # 排除'_'结尾的SPU
    df = df[~df['spu'].astype(str).str.endswith('_')]
    print(f'  排除\'_\'结尾后: {len(df)} 行')

    # 排除已知SKC编码
    df = df[~df['spu'].astype(str).isin(EXCLUDED_SKC_CODES)]
    print(f'  排除SKC编码后: {len(df)} 行')

    # 筛选有效价格
    df['ZRSP'] = pd.to_numeric(df['ZRSP'], errors='coerce')
    df = df[df['ZRSP'].notna() & (df['ZRSP'] > 0)]
    print(f'  筛选有效价格后: {len(df)} 行')

    # 去重
    df = df.drop_duplicates(subset=['spu', 'CON - Valid From', 'CON - Valid To'], keep='first')
    print(f'  去重后: {len(df)} 行')

    # 清理重叠记录
    df_cleaned = clean_overlapping_records(df)
    print(f'  清理重叠记录后: {len(df_cleaned)} 行')

    # 连接数据库
    print()
    print('连接数据库...')
    db_config = load_db_config()
    existing = get_existing_records(db_config)
    print(f'  数据库现有记录: {len(existing)} 条')

    # 找出新记录
    new_records = []
    for idx, row in df_cleaned.iterrows():
        spu = row['spu']
        valid_from = to_date(row['CON - Valid From'])
        valid_to = to_date(row['CON - Valid To'])

        key = (spu, str(valid_from), str(valid_to))
        if key not in existing:
            new_records.append({
                'category': row['ART - Hier. Lvl 5'],
                'spu': spu,
                'name': row['Product - Name'],
                'validFrom': valid_from,
                'validTo': valid_to,
                'rsp': float(row['ZRSP'])
            })

    print()
    print('=' * 60)
    print(f'新增记录数: {len(new_records)} 条')
    print('=' * 60)

    # 导出结果
    if new_records:
        export_df = pd.DataFrame(new_records)
        output_dir = config['price_files']['directory']
        output_path = os.path.join(output_dir, 'new_records_preview.csv')
        export_df.to_csv(output_path, index=False, encoding='utf-8-sig')

        print(f'\n已导出到: {output_path}')
        print('\n前5条记录:')
        print(export_df.head().to_string())

        print('\n按SPU统计:')
        spu_counts = export_df['spu'].value_counts()
        print(spu_counts.to_string())
    else:
        print('\n没有新增记录，无需执行价格更新。')

    return len(new_records)


if __name__ == '__main__':
    main()

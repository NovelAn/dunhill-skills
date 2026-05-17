"""
在历史价格文件中搜索指定SPU的调价记录
"""
import os
import pandas as pd
from datetime import date
from collections import defaultdict

# 加载 .env 跨平台路径配置
from pathlib import Path as _P
_env_file = _P.home() / ".claude" / "skills" / ".env"
if _env_file.exists():
    with open(_env_file, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                _k, _v = _k.strip(), _v.strip()
                if _k and _k not in os.environ:
                    os.environ[_k] = _v

# 要搜索的SPU列表
TARGET_SPUS = {
    'DU0DWADUN200',
    'DU1K1054A',
    'DUJSA82B6',
    'DU0DWADUN212',
    'DU20RWRAE33',
    'DUBM004TX',
    'DU1DBFB52',
    'DU1AB5752',
}

MAX_VALID_DATE = date(9999, 12, 31)


def is_spu(product_name):
    if pd.isna(product_name):
        return False
    parts = [p.strip() for p in str(product_name).split(',')]
    return len(parts) == 1


def to_date(dt):
    if pd.isna(dt) or dt is None:
        return MAX_VALID_DATE
    if hasattr(dt, 'date'):
        return dt.date()
    if isinstance(dt, str):
        if '9999' in dt:
            return MAX_VALID_DATE
        parts = dt.split('-')
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    return date(dt.year, dt.month, dt.day)


def main():
    print('=' * 60)
    print('搜索SPU历史调价记录')
    print('=' * 60)
    print(f'目标SPU: {TARGET_SPUS}')

    base_dir = os.path.join(os.getenv('DUNHILL_DATA_DIR', 'D:/Work/dunhill'), 'product', '调价清单')

    # 收集所有Excel文件
    all_files = []
    for root, dirs, files in os.walk(base_dir):
        for f in files:
            if f.endswith(('.xlsx', '.xls')) and not f.startswith('~'):
                all_files.append(os.path.join(root, f))

    print(f'\n找到 {len(all_files)} 个Excel文件')

    # 按修改时间排序（最新的优先）
    all_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)

    # 收集所有匹配的记录
    all_records = defaultdict(list)  # spu -> [(文件, 记录), ...]

    for file_path in all_files:
        file_name = os.path.basename(file_path)
        try:
            df = pd.read_excel(file_path, header=2)

            # 检查必要列
            if 'spu' not in df.columns:
                continue

            # 筛选目标SPU
            for idx, row in df.iterrows():
                spu = str(row.get('spu', '')).strip()
                if spu in TARGET_SPUS:
                    # 只保留SPU级别的记录
                    if is_spu(row.get('Product - Name', '')):
                        valid_from = to_date(row.get('CON - Valid From'))
                        valid_to = to_date(row.get('CON - Valid To'))
                        rsp = row.get('ZRSP')

                        if pd.notna(rsp) and float(rsp) > 0:
                            all_records[spu].append({
                                'file': file_name,
                                'category': row.get('ART - Hier. Lvl 5', ''),
                                'name': row.get('Product - Name', ''),
                                'validFrom': valid_from,
                                'validTo': valid_to,
                                'rsp': float(rsp)
                            })
        except Exception as e:
            pass

    # 输出结果
    print('\n' + '=' * 60)
    print('搜索结果')
    print('=' * 60)

    found_spus = set(all_records.keys())
    not_found = TARGET_SPUS - found_spus

    if not_found:
        print(f'\n未找到的SPU: {not_found}')

    for spu in sorted(found_spus):
        records = all_records[spu]
        print(f'\n【{spu}】找到 {len(records)} 条记录:')

        # 按validFrom排序
        records.sort(key=lambda x: x['validFrom'])

        # 去重（同一时间段只保留一条）
        unique_records = []
        seen = set()
        for rec in records:
            key = (rec['validFrom'], rec['validTo'], rec['rsp'])
            if key not in seen:
                seen.add(key)
                unique_records.append(rec)

        for rec in unique_records:
            print(f"  {rec['validFrom']} ~ {rec['validTo']} | ¥{rec['rsp']:.0f} | {rec['name'][:30]}... | 来源: {rec['file']}")

    # 导出CSV
    if all_records:
        csv_path = os.path.join(base_dir, 'found_spu_records.csv')
        with open(csv_path, 'w', encoding='utf-8-sig') as f:
            f.write('spu,category,name,validFrom,validTo,rsp,source_file\n')
            for spu in sorted(found_spus):
                for rec in all_records[spu]:
                    name = str(rec['name']).replace(',', ' ').replace('"', '')
                    f.write(f"{spu},{rec['category']},\"{name}\",{rec['validFrom']},{rec['validTo']},{rec['rsp']},{rec['file']}\n")
        print(f'\n已导出到: {csv_path}')


if __name__ == '__main__':
    main()

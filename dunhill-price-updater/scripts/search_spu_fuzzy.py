"""
模糊搜索SPU历史调价记录 - 输出到文件
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
TARGET_SPUS = [
    'DU0DDASDH130',
    'DU0DDAVDH118',
    'DU0DDAVDH128',
    'DU1BSN152',
    'DU1K1104A',
    'DU1K1804A',
    'DU1L1201Y',
    'DUAL1201Y',
    'DUCH263B',
    'DUCH270B5',
    'DUCPTP4PT',
    'DUJNV3164',
    'DUL1C106',
]

MAX_VALID_DATE = date(9999, 12, 31)


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


def match_spu(spu_value, targets):
    if pd.isna(spu_value):
        return None
    spu_str = str(spu_value).strip().upper()
    for target in targets:
        target_upper = target.upper()
        if spu_str == target_upper or spu_str.startswith(target_upper):
            return target
    return None


def main():
    base_dir = os.path.join(os.getenv('DUNHILL_DATA_DIR', 'D:/Work/dunhill'), 'product', '调价清单')
    output_file = os.path.join(base_dir, 'found_spu_records.txt')

    # 收集所有Excel文件
    all_files = []
    for root, dirs, files in os.walk(base_dir):
        for f in files:
            if f.endswith(('.xlsx', '.xls')) and not f.startswith('~'):
                all_files.append(os.path.join(root, f))

    all_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)

    # 收集所有匹配的记录
    all_records = defaultdict(list)

    for file_path in all_files:
        file_name = os.path.basename(file_path)
        try:
            df = pd.read_excel(file_path, header=2)
            if 'spu' not in df.columns:
                continue

            for idx, row in df.iterrows():
                spu_raw = row.get('spu', '')
                matched_target = match_spu(spu_raw, TARGET_SPUS)

                if matched_target:
                    valid_from = to_date(row.get('CON - Valid From'))
                    valid_to = to_date(row.get('CON - Valid To'))
                    rsp = row.get('ZRSP')

                    if pd.notna(rsp) and float(rsp) > 0:
                        all_records[matched_target].append({
                            'spu_raw': str(spu_raw),
                            'file': file_name,
                            'category': row.get('ART - Hier. Lvl 5', ''),
                            'name': row.get('Product - Name', ''),
                            'validFrom': valid_from,
                            'validTo': valid_to,
                            'rsp': float(rsp)
                        })
        except Exception as e:
            pass

    # 写入文件
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('=' * 80 + '\n')
        f.write('SPU历史调价记录搜索结果\n')
        f.write('=' * 80 + '\n\n')

        found_spus = list(all_records.keys())
        not_found = [s for s in TARGET_SPUS if s not in found_spus]

        if not_found:
            f.write(f'未找到的SPU: {not_found}\n\n')

        for spu in sorted(found_spus):
            records = all_records[spu]
            f.write(f'【{spu}】找到 {len(records)} 条记录:\n')

            # 去重
            unique_records = []
            seen = set()
            for rec in records:
                key = (rec['spu_raw'], rec['validFrom'], rec['validTo'], rec['rsp'])
                if key not in seen:
                    seen.add(key)
                    unique_records.append(rec)

            unique_records.sort(key=lambda x: (x['spu_raw'], x['validFrom']))

            for rec in unique_records:
                f.write(f"  {rec['spu_raw']} | {rec['validFrom']} ~ {rec['validTo']} | RSP:{rec['rsp']:.0f} | {rec['file']}\n")
                f.write(f"    Name: {rec['name']}\n")
            f.write('\n')

        # CSV格式
        csv_path = os.path.join(base_dir, 'found_spu_records.csv')
        with open(csv_path, 'w', encoding='utf-8-sig') as csv:
            csv.write('spu,spu_raw,category,name,validFrom,validTo,rsp,source_file\n')
            for spu in sorted(found_spus):
                for rec in all_records[spu]:
                    name = str(rec['name']).replace(',', ' ').replace('"', '')
                    csv.write(f"{spu},{rec['spu_raw']},{rec['category']},\"{name}\",{rec['validFrom']},{rec['validTo']},{rec['rsp']},{rec['file']}\n")

    print(f'结果已保存到: {output_file}')
    print(f'CSV已保存到: {csv_path}')

    # 简单统计
    print(f'\n找到的SPU数量: {len(found_spus)}')
    print(f'未找到的SPU: {not_found}')


if __name__ == '__main__':
    main()

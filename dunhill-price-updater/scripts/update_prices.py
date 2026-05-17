"""
Dunhill商品价格更新脚本
从价格变动文件读取数据，筛选SPU记录并更新数据库

================================================================================
【核心原则】同一SPU的所有调价记录，日期必须连续，不能有重叠或间隙
================================================================================

这是本脚本最重要的验证规则：
- 同一个SPU可能有多条调价记录（不同时间段不同价格）
- 这些记录的日期范围必须紧密衔接：下一条的 validFrom = 上一条的 validTo + 1天
- 任何重叠或间隙都是数据错误，必须修复后才能入库

示例（正确）：
  记录1: 2024-01-01 ~ 2024-06-30
  记录2: 2024-07-01 ~ 2024-12-31  ✓ 连续（6/30 + 1 = 7/1）

示例（错误-重叠）：
  记录1: 2024-01-01 ~ 2024-07-15
  记录2: 2024-07-01 ~ 2024-12-31  ✗ 重叠（7/15 >= 7/1）

示例（错误-间隙）：
  记录1: 2024-01-01 ~ 2024-06-30
  记录2: 2024-08-01 ~ 2024-12-31  ✗ 间隙（缺少7/1~7/31）

================================================================================

其他设计要点：
1. 使用复合唯一键 (spu, validFrom, validTo) 进行匹配
2. 正确处理 validTo 为空/NaT 的情况（转为 9999-12-31）
3. 正确处理 datetime 到 date 的转换
4. 只新增/更新 Excel 中的记录，不删除数据库中已有的记录
"""
import os
import re
import json
import glob
import multiprocessing
from datetime import datetime, date, timedelta
from typing import List, Dict, Tuple, Optional, Set
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd
import pymysql
import yaml

# 多进程并发配置
BATCH_SIZE = 500  # 每批处理的记录数
NUM_WORKERS = max(4, multiprocessing.cpu_count() - 1)  # 工作进程数


def _insert_batch(batch: List[Dict], db_config: Dict, table_name: str) -> Tuple[int, int]:
    """批量插入记录到数据库（用于多进程）

    Args:
        batch: 记录列表
        db_config: 数据库配置
        table_name: 表名

    Returns:
        (插入成功数, 错误数)
    """
    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()

    insert_sql = f"""
    INSERT IGNORE INTO `{table_name}`
    (category, spu, name, validFrom, validTo, rsp)
    VALUES (%s, %s, %s, %s, %s, %s)
    """

    inserted = 0
    errors = 0

    for record in batch:
        try:
            cursor.execute(insert_sql, (
                record['category'],
                record['spu'],
                record['product_name'],
                record['valid_from'],
                record['valid_to'],
                record['retail_price']
            ))
            if cursor.rowcount > 0:
                inserted += 1
        except Exception:
            errors += 1

    conn.commit()
    cursor.close()
    conn.close()

    return inserted, errors


def _update_batch(batch: List[Dict], db_config: Dict, table_name: str) -> Tuple[int, int]:
    """批量更新记录到数据库（用于多进程）

    Args:
        batch: 记录列表
        db_config: 数据库配置
        table_name: 表名

    Returns:
        (更新成功数, 错误数)
    """
    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()

    update_sql = f"""
    UPDATE `{table_name}`
    SET category = %s, name = %s, rsp = %s
    WHERE spu = %s AND validFrom = %s AND validTo = %s
    """

    updated = 0
    errors = 0

    for record in batch:
        try:
            cursor.execute(update_sql, (
                record['category'],
                record['product_name'],
                record['retail_price'],
                record['spu'],
                record['valid_from'],
                record['valid_to']
            ))
            if cursor.rowcount > 0:
                updated += 1
        except Exception:
            errors += 1

    conn.commit()
    cursor.close()
    conn.close()

    return updated, errors


class DBConfigManager:
    """数据库配置管理器 - 复用现有模式"""

    SYSTEM_DB_CONFIG_PATH = os.path.join(os.path.expanduser("~"), "database_config.json")

    @classmethod
    def load_db_config(cls) -> List[Dict]:
        """加载数据库配置"""
        if not os.path.exists(cls.SYSTEM_DB_CONFIG_PATH):
            raise FileNotFoundError(
                f"数据库配置文件不存在: {cls.SYSTEM_DB_CONFIG_PATH}\n"
                f"请确保配置文件已正确设置。"
            )

        with open(cls.SYSTEM_DB_CONFIG_PATH, 'r', encoding='utf-8') as f:
            content = f.read()
            # 移除 JSON 中的注释
            content_no_comments = re.sub(r'^\s*//.*$', '', content, flags=re.MULTILINE)
            config = json.loads(content_no_comments)

        return config.get('databases', [])

    @classmethod
    def get_db_config_by_name(cls, name: str) -> Optional[Dict]:
        """根据名称获取数据库配置"""
        dbs = cls.load_db_config()
        for db in dbs:
            if db.get('name') == name:
                return {
                    "host": db.get("host"),
                    "user": db.get("user"),
                    "password": db.get("password"),
                    "database": db.get("database"),
                    "port": db.get("port", 3306),
                    "charset": db.get("charset", "utf8mb4")
                }
        return None


class PriceUpdater:
    """价格更新器"""

    # 有效期的默认最大日期（表示长期有效）
    MAX_VALID_DATE = date(9999, 12, 31)

    # 需要排除的SKC编码列表（这些是颜色编码，对应的SPU已在数据库中）
    # SKC = SPU + 颜色后缀，如 DU1DBFB52 + 11 = DU1DBFB5211
    EXCLUDED_SKC_CODES = {
        'DU1AB575211',
        'DU1AB575216',
        'DU1AB575221',
        'DU1DBFB5211',
        'DU1DBFB5216',
        'DU1DBFB5221',
    }

    def __init__(self, config_path: str = None):
        """初始化

        Args:
            config_path: 配置文件路径，默认为脚本同级config目录
        """
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "config", "price-config.yaml"
            )

        self.config = self._load_config(config_path)
        self.db_config = None
        self.connection = None

    def _load_config(self, config_path: str) -> Dict:
        """加载YAML配置文件"""
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def find_latest_price_file(self) -> str:
        """查找最新的价格文件

        Returns:
            最新价格文件的完整路径

        Raises:
            FileNotFoundError: 没有找到价格文件
        """
        directory = self.config['price_files']['directory']
        pattern = self.config['price_files']['pattern']

        # 构建搜索模式
        search_pattern = os.path.join(directory, pattern)
        files = glob.glob(search_pattern)

        if not files:
            raise FileNotFoundError(f"未找到价格文件: {search_pattern}")

        # 按修改时间排序，返回最新的
        files.sort(key=os.path.getmtime, reverse=True)
        latest_file = files[0]

        print(f"找到最新价格文件: {os.path.basename(latest_file)}")
        return latest_file

    def is_spu(self, product_name: str) -> bool:
        """判断是否为SPU记录

        SPU记录的商品名称不含逗号分隔的颜色和尺码信息
        例: "COLLEGE PENNY LOAFER LTR" -> SPU
        例: "COLLEGE PENNY LOAFER LTR, BLACK, 39, .0" -> SKU

        Args:
            product_name: 商品名称

        Returns:
            True表示是SPU，False表示是SKU
        """
        if pd.isna(product_name):
            return False
        parts = [p.strip() for p in str(product_name).split(',')]
        return len(parts) == 1

    def to_date(self, dt) -> Optional[date]:
        """将各种日期格式转换为 Python date 对象

        关键处理：
        - NaT/None/pd.Na -> 返回 MAX_VALID_DATE (9999-12-31)
        - datetime -> 转换为 date（去掉时间部分）
        - date -> 直接返回

        Args:
            dt: 日期值（可能是 datetime, date, Timestamp, NaT, None）

        Returns:
            Python date 对象，或 MAX_VALID_DATE（如果输入为空）
        """
        if pd.isna(dt) or dt is None:
            return self.MAX_VALID_DATE

        # 如果已经是 date 类型
        if isinstance(dt, date) and not isinstance(dt, datetime):
            return dt

        # 如果是 datetime 类型（包括 pandas Timestamp）
        if hasattr(dt, 'date'):
            return dt.date()

        # 其他情况尝试转换
        return date(dt.year, dt.month, dt.day)

    def read_and_filter_price_data(self, file_path: str) -> pd.DataFrame:
        """读取Excel并筛选SPU记录

        Args:
            file_path: 价格文件路径

        Returns:
            筛选后的DataFrame
        """
        # 读取Excel
        # Excel结构：
        #   Row 0: "Pricing Conditions" 标题
        #   Row 1: 空行
        #   Row 2: 列名 (ART - Hier. Lvl 3, spu, Product - Name, ...)
        #   Row 3+: 数据
        # 使用 header=2 让 pandas 用 Row 2 (index=2) 作为列名
        df = pd.read_excel(file_path, header=2)

        print(f"原始数据总行数: {len(df)}")

        # 只转换ZRSP为数值类型，日期保持原样（Excel中已经是datetime）
        df['ZRSP'] = pd.to_numeric(df['ZRSP'], errors='coerce')

        # 筛选条件1: 只要SPU记录
        df = df[df['Product - Name'].apply(self.is_spu)]
        print(f"筛选SPU记录后: {len(df)} 行")

        # 筛选条件1.5: 排除SPU编码以'_'结尾的记录（这类记录不是标准SPU）
        df = df[~df['spu'].astype(str).str.endswith('_')]
        print(f"排除'_'结尾的SPU后: {len(df)} 行")

        # 筛选条件1.6: 排除已知的SKC编码（颜色编码，对应SPU已在数据库中）
        df = df[~df['spu'].astype(str).isin(self.EXCLUDED_SKC_CODES)]
        print(f"排除SKC编码后: {len(df)} 行")

        # 筛选条件2: 零售价不为空且大于0
        df = df[df['ZRSP'].notna() & (df['ZRSP'] > 0)]
        print(f"筛选有零售价记录后: {len(df)} 行")

        # 去重：按 SPU + ValidFrom + ValidTo 组合去重
        # 注意：同一SPU在不同时间段可能有不同价格，需要保留所有调价记录
        df = df.drop_duplicates(
            subset=['spu', 'CON - Valid From', 'CON - Valid To'],
            keep='first'
        )
        print(f"去重后(SPU+ValidFrom+ValidTo): {len(df)} 行")

        # 【关键】清理Excel中的低价重叠记录
        # 品牌方Excel可能将折扣价错误写成零售价，导致同一时间段出现多条记录
        # 规则：保留高价记录，删除低价记录（折扣价）
        df = self._clean_overlapping_records(df)

        return df

    def _clean_overlapping_records(self, df: pd.DataFrame) -> pd.DataFrame:
        """清理Excel中的低价重叠记录

        同一SPU可能有多条时间重叠的记录（正价 + 折扣价），
        保留高价记录（正价），删除低价记录（折扣价）。

        Args:
            df: 筛选后的DataFrame

        Returns:
            清理后的DataFrame
        """
        if len(df) == 0:
            return df

        # 按SPU分组
        from collections import defaultdict
        by_spu = defaultdict(list)
        for idx, row in df.iterrows():
            by_spu[row['spu']].append((idx, row))

        indices_to_keep = []

        for spu, rows in by_spu.items():
            if len(rows) <= 1:
                # 单条记录，直接保留
                indices_to_keep.extend([idx for idx, _ in rows])
                continue

            # 按validFrom排序
            sorted_rows = sorted(rows, key=lambda x: x[1]['CON - Valid From'])

            # 标记要删除的记录
            keep_indices = set(range(len(sorted_rows)))

            for i in range(len(sorted_rows)):
                if i not in keep_indices:
                    continue
                idx_i, row_i = sorted_rows[i]
                valid_from_i = self.to_date(row_i['CON - Valid From'])
                valid_to_i = self.to_date(row_i['CON - Valid To'])
                price_i = float(row_i['ZRSP']) if pd.notna(row_i['ZRSP']) else 0

                for j in range(i + 1, len(sorted_rows)):
                    if j not in keep_indices:
                        continue
                    idx_j, row_j = sorted_rows[j]
                    valid_from_j = self.to_date(row_j['CON - Valid From'])
                    valid_to_j = self.to_date(row_j['CON - Valid To'])
                    price_j = float(row_j['ZRSP']) if pd.notna(row_j['ZRSP']) else 0

                    # 检查是否重叠
                    has_overlap = False
                    if valid_to_i == self.MAX_VALID_DATE:
                        has_overlap = True
                    elif valid_from_j <= valid_to_i:
                        has_overlap = True

                    if has_overlap:
                        # 保留高价，删除低价
                        if price_i >= price_j:
                            keep_indices.discard(j)
                        else:
                            keep_indices.discard(i)
                            break  # 当前记录被删除，不需要继续比较

            for i in keep_indices:
                indices_to_keep.append(sorted_rows[i][0])

        cleaned_df = df.loc[indices_to_keep]

        removed_count = len(df) - len(cleaned_df)
        if removed_count > 0:
            print(f"清理低价重叠记录: 删除 {removed_count} 条，保留 {len(cleaned_df)} 条")

        return cleaned_df

    def connect_database(self):
        """连接数据库"""
        db_name = self.config['database']['config_name']
        self.db_config = DBConfigManager.get_db_config_by_name(db_name)

        if self.db_config is None:
            raise ValueError(f"未找到数据库配置: {db_name}")

        self.connection = pymysql.connect(**self.db_config)
        print(f"已连接数据库: {db_name}")

    def disconnect_database(self):
        """断开数据库连接"""
        if self.connection:
            self.connection.close()
            self.connection = None
            print("已断开数据库连接")

    def _make_record_key(self, spu: str, valid_from: date, valid_to: date) -> str:
        """生成记录的唯一键（SPU + ValidFrom + ValidTo）

        Args:
            spu: SPU编码
            valid_from: 生效日期
            valid_to: 失效日期

        Returns:
            格式为 "SPU|YYYY-MM-DD|YYYY-MM-DD" 的字符串
        """
        return f"{spu}|{valid_from}|{valid_to}"

    def get_existing_db_records(self) -> Dict[str, Dict]:
        """获取数据库现有记录

        Returns:
            以"SPU|ValidFrom|ValidTo"为key的记录字典
        """
        table_name = self.config['database']['table_name']

        with self.connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(f"SELECT * FROM `{table_name}`")
            records = cursor.fetchall()

        # 转换为字典，使用复合键
        result = {}
        for record in records:
            spu = record.get('spu')
            valid_from = record.get('validFrom')
            valid_to = record.get('validTo')
            if spu:
                # 数据库中的日期已经是 date 类型
                key = self._make_record_key(spu, valid_from, valid_to)
                result[key] = record

        print(f"数据库现有记录数: {len(result)}")
        return result

    def get_db_records_by_spu(self) -> Dict[str, List[Dict]]:
        """按SPU分组获取数据库记录（用于检查日期重叠）

        Returns:
            以 SPU 为 key，该 SPU 的所有记录列表为 value 的字典
        """
        table_name = self.config['database']['table_name']

        with self.connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(f"SELECT * FROM `{table_name}` ORDER BY spu, validFrom")
            records = cursor.fetchall()

        result = {}
        for record in records:
            spu = record.get('spu')
            if spu not in result:
                result[spu] = []
            result[spu].append(record)

        return result

    def check_date_overlap(self, spu: str, new_from: date, new_to: date,
                           existing_records: Dict[str, List[Dict]],
                           exclude_key: str = None) -> List[str]:
        """检查新记录是否与现有记录存在日期重叠

        日期重叠定义：两个时间段有交集
        - 记录A: [validFrom_A, validTo_A]
        - 记录B: [validFrom_B, validTo_B]
        - 重叠条件: validFrom_A <= validTo_B AND validFrom_B <= validTo_A

        Args:
            spu: SPU编码
            new_from: 新记录的生效日期
            new_to: 新记录的失效日期
            existing_records: 按SPU分组的现有记录
            exclude_key: 要排除的记录key（用于更新场景）

        Returns:
            重叠警告消息列表（空列表表示无重叠）
        """
        warnings = []

        if spu not in existing_records:
            return warnings

        for record in existing_records[spu]:
            existing_from = record.get('validFrom')
            existing_to = record.get('validTo')

            # 生成key用于排除
            record_key = self._make_record_key(spu, existing_from, existing_to)
            if exclude_key and record_key == exclude_key:
                continue

            # 检查日期重叠
            if new_from <= existing_to and existing_from <= new_to:
                warnings.append(
                    f"日期重叠: SPU={spu}, 新记录[{new_from}~{new_to}] "
                    f"与现有记录[{existing_from}~{existing_to}]重叠"
                )

        return warnings

    def validate_spu_date_continuity(
        self,
        df: pd.DataFrame,
        db_records_by_spu: Dict[str, List[Dict]] = None
    ) -> List[Dict]:
        """验证同一SPU的所有记录日期是否连续（无重叠、无间隙）

        【核心原则】同一SPU的所有调价记录，日期必须连续！
        - 连续定义：下一条记录的 validFrom = 上一条记录的 validTo + 1天
        - 重叠：下一条记录的 validFrom <= 上一条记录的 validTo
        - 间隙：下一条记录的 validFrom > 上一条记录的 validTo + 1天

        Args:
            df: Excel中筛选后的价格数据
            db_records_by_spu: 数据库中按SPU分组的记录（可选，用于合并验证）

        Returns:
            问题列表，每个问题包含 spu, type(overlap/gap), details
        """
        issues = []

        # 按SPU分组Excel数据
        excel_by_spu = defaultdict(list)
        for _, row in df.iterrows():
            spu = str(row['spu']).strip()
            valid_from = self.to_date(row['CON - Valid From'])
            valid_to = self.to_date(row['CON - Valid To'])
            excel_by_spu[spu].append({
                'valid_from': valid_from,
                'valid_to': valid_to,
                'source': 'excel'
            })

        # 如果提供了数据库记录，合并到验证数据中
        if db_records_by_spu:
            for spu, records in db_records_by_spu.items():
                for rec in records:
                    if spu not in excel_by_spu:
                        excel_by_spu[spu] = []
                    # 检查是否已存在相同记录（避免重复）
                    valid_from = rec.get('validFrom')
                    valid_to = rec.get('validTo')
                    exists = any(
                        r['valid_from'] == valid_from and r['valid_to'] == valid_to
                        for r in excel_by_spu[spu]
                    )
                    if not exists:
                        excel_by_spu[spu].append({
                            'valid_from': valid_from,
                            'valid_to': valid_to,
                            'source': 'database'
                        })

        # 验证每个SPU的日期连续性
        for spu, records in excel_by_spu.items():
            if len(records) <= 1:
                continue

            # 按valid_from排序
            sorted_records = sorted(records, key=lambda x: x['valid_from'])

            for i in range(len(sorted_records) - 1):
                curr = sorted_records[i]
                next_rec = sorted_records[i + 1]

                curr_end = curr['valid_to']
                next_start = next_rec['valid_from']

                # 如果当前记录的结束日期是 9999-12-31，则不应该有下一条记录
                # 这种情况下必然是重叠
                if curr_end == self.MAX_VALID_DATE:
                    issues.append({
                        'spu': spu,
                        'type': 'overlap',
                        'details': f"记录重叠: [{curr['valid_from']}~{curr_end}] 已是永久有效，但仍存在后续记录 [{next_start}~{next_rec['valid_to']}]",
                        'record1': f"{curr['valid_from']}~{curr_end}",
                        'record2': f"{next_start}~{next_rec['valid_to']}"
                    })
                    continue

                expected_start = curr_end + timedelta(days=1)

                if next_start <= curr_end:
                    # 重叠
                    issues.append({
                        'spu': spu,
                        'type': 'overlap',
                        'details': f"记录重叠: [{curr['valid_from']}~{curr_end}] 与 [{next_start}~{next_rec['valid_to']}]",
                        'record1': f"{curr['valid_from']}~{curr_end}",
                        'record2': f"{next_start}~{next_rec['valid_to']}"
                    })
                elif next_start > expected_start:
                    # 间隙
                    issues.append({
                        'spu': spu,
                        'type': 'gap',
                        'details': f"日期间隙: [{curr_end}] 与 [{next_start}] 之间缺少 {expected_start}~{next_start - timedelta(days=1)}",
                        'record1': f"{curr['valid_from']}~{curr_end}",
                        'record2': f"{next_start}~{next_rec['valid_to']}"
                    })

        return issues

    def compare_and_prepare_changes(
        self,
        df: pd.DataFrame,
        existing_records: Dict[str, Dict],
        db_records_by_spu: Dict[str, List[Dict]]
    ) -> Tuple[List[Dict], List[Dict], List[str]]:
        """对比并准备变更

        Args:
            df: 新的价格数据
            existing_records: 数据库现有记录（以复合键为索引）
            db_records_by_spu: 按SPU分组的数据库记录（用于检查重叠）

        Returns:
            (新增记录列表, 更新记录列表, 警告消息列表)
        """
        new_records = []
        update_records = []
        warnings = []

        for _, row in df.iterrows():
            spu = str(row['spu']).strip()
            valid_from = self.to_date(row['CON - Valid From'])
            valid_to = self.to_date(row['CON - Valid To'])

            record = {
                'category': row['ART - Hier. Lvl 5'],
                'spu': spu,
                'product_name': row['Product - Name'],
                'valid_from': valid_from,
                'valid_to': valid_to,
                'retail_price': float(row['ZRSP']) if pd.notna(row['ZRSP']) else None
            }

            # 使用复合键查找
            key = self._make_record_key(spu, valid_from, valid_to)

            if key in existing_records:
                existing = existing_records[key]
                # 检查是否需要更新（比较零售价）
                if record['retail_price'] != existing.get('rsp'):
                    update_records.append(record)
            else:
                # 新记录：检查日期重叠
                overlap_warnings = self.check_date_overlap(
                    spu, valid_from, valid_to, db_records_by_spu
                )
                if overlap_warnings:
                    warnings.extend(overlap_warnings)
                new_records.append(record)

        print(f"新增记录: {len(new_records)} 条")
        print(f"更新记录: {len(update_records)} 条")

        if warnings:
            print(f"警告: 发现 {len(warnings)} 个日期重叠问题")

        return new_records, update_records, warnings

    def execute_updates(
        self,
        new_records: List[Dict],
        update_records: List[Dict]
    ) -> Tuple[int, int]:
        """执行数据库更新（使用多进程并发导入）

        Args:
            new_records: 新增记录列表
            update_records: 更新记录列表

        Returns:
            (新增数量, 更新数量)
        """
        table_name = self.config['database']['table_name']
        total_inserted = 0
        total_updated = 0

        # 多进程并发插入新记录
        if new_records:
            num_batches = (len(new_records) + BATCH_SIZE - 1) // BATCH_SIZE
            batches = [new_records[i:i + BATCH_SIZE] for i in range(0, len(new_records), BATCH_SIZE)]

            print(f'\n并发插入 {len(new_records)} 条新记录...')
            print(f'  分 {num_batches} 批，每批 {BATCH_SIZE} 条，使用 {NUM_WORKERS} 个进程')

            with ProcessPoolExecutor(max_workers=NUM_WORKERS) as executor:
                futures = {
                    executor.submit(_insert_batch, batch, self.db_config, table_name): i
                    for i, batch in enumerate(batches)
                }

                for future in as_completed(futures):
                    batch_idx = futures[future]
                    try:
                        inserted, errors = future.result()
                        total_inserted += inserted
                        if (batch_idx + 1) % 5 == 0 or batch_idx == num_batches - 1:
                            print(f'    已完成 {batch_idx + 1}/{num_batches} 批，累计插入 {total_inserted} 条')
                    except Exception as e:
                        print(f'    批次 {batch_idx} 失败: {e}')

        # 多进程并发更新记录
        if update_records:
            num_batches = (len(update_records) + BATCH_SIZE - 1) // BATCH_SIZE
            batches = [update_records[i:i + BATCH_SIZE] for i in range(0, len(update_records), BATCH_SIZE)]

            print(f'\n并发更新 {len(update_records)} 条记录...')
            print(f'  分 {num_batches} 批，每批 {BATCH_SIZE} 条，使用 {NUM_WORKERS} 个进程')

            with ProcessPoolExecutor(max_workers=NUM_WORKERS) as executor:
                futures = {
                    executor.submit(_update_batch, batch, self.db_config, table_name): i
                    for i, batch in enumerate(batches)
                }

                for future in as_completed(futures):
                    batch_idx = futures[future]
                    try:
                        updated, errors = future.result()
                        total_updated += updated
                        if (batch_idx + 1) % 5 == 0 or batch_idx == num_batches - 1:
                            print(f'    已完成 {batch_idx + 1}/{num_batches} 批，累计更新 {total_updated} 条')
                    except Exception as e:
                        print(f'    批次 {batch_idx} 失败: {e}')

        return total_inserted, total_updated

    def run(self, dry_run: bool = False, skip_overlap_check: bool = False, skip_continuity_check: bool = False) -> Dict:
        """执行完整的价格更新流程

        Args:
            dry_run: 是否只预览不执行
            skip_overlap_check: 是否跳过日期重叠检查（如果确认重叠是预期的）
            skip_continuity_check: 是否跳过日期连续性检查（不推荐）

        Returns:
            执行结果统计
        """
        result = {
            'file': None,
            'total_spu': 0,
            'new_records': 0,
            'updated_records': 0,
            'overlap_warnings': [],
            'continuity_issues': [],
            'dry_run': dry_run,
            'success': False,
            'error': None
        }

        try:
            # Step 1: 找到最新价格文件
            file_path = self.find_latest_price_file()
            result['file'] = os.path.basename(file_path)

            # Step 2: 读取并筛选数据
            df = self.read_and_filter_price_data(file_path)
            result['total_spu'] = len(df)

            # Step 3: 连接数据库
            self.connect_database()

            # Step 4: 获取现有记录
            existing_records = self.get_existing_db_records()
            db_records_by_spu = self.get_db_records_by_spu()

            # Step 5: 【关键】验证SPU日期连续性
            # 同一SPU的所有记录日期必须连续，不能有重叠或间隙
            if not skip_continuity_check:
                print("\n[关键检查] 验证SPU日期连续性...")
                continuity_issues = self.validate_spu_date_continuity(df, db_records_by_spu)
                result['continuity_issues'] = continuity_issues

                if continuity_issues:
                    overlaps = [i for i in continuity_issues if i['type'] == 'overlap']
                    gaps = [i for i in continuity_issues if i['type'] == 'gap']

                    print(f"  发现 {len(overlaps)} 个日期重叠问题")
                    print(f"  发现 {len(gaps)} 个日期间隙问题")

                    if overlaps:
                        print("\n" + "=" * 60)
                        print("【严重错误】发现日期重叠!")
                        print("=" * 60)
                        print("同一SPU的调价记录日期必须连续，不能有重叠！")
                        print()
                        for issue in overlaps[:5]:
                            print(f"  SPU: {issue['spu']}")
                            print(f"    {issue['details']}")
                        if len(overlaps) > 5:
                            print(f"  ... 还有 {len(overlaps) - 5} 个重叠问题")

                    if gaps:
                        print("\n" + "=" * 60)
                        print("【警告】发现日期间隙!")
                        print("=" * 60)
                        for issue in gaps[:5]:
                            print(f"  SPU: {issue['spu']}")
                            print(f"    {issue['details']}")
                        if len(gaps) > 5:
                            print(f"  ... 还有 {len(gaps) - 5} 个间隙问题")

                    if overlaps:
                        print("\n请修复数据源中的日期重叠问题后再执行更新。")
                        print("如果确认要强制执行，请使用 --skip-continuity 参数（不推荐）")
                        result['success'] = False
                        result['error'] = f"发现 {len(overlaps)} 个日期重叠问题，数据不符合连续性要求"
                        return result

            # Step 6: 对比并准备变更
            new_records, update_records, warnings = self.compare_and_prepare_changes(
                df, existing_records, db_records_by_spu
            )
            result['new_records'] = len(new_records)
            result['updated_records'] = len(update_records)
            result['overlap_warnings'] = warnings

            # 如果有日期重叠警告且未跳过检查，提示用户
            if warnings and not skip_overlap_check:
                print("\n" + "=" * 60)
                print("警告: 发现日期重叠问题!")
                print("=" * 60)
                for w in warnings[:5]:  # 只显示前5个
                    print(f"  {w}")
                if len(warnings) > 5:
                    print(f"  ... 还有 {len(warnings) - 5} 个警告")
                print("\n如果这些重叠是预期的（如价格调整），请使用 --skip-overlap 参数")
                print("或者手动检查数据后再执行")
                result['success'] = False
                result['error'] = f"发现 {len(warnings)} 个日期重叠问题"
                return result

            # Step 7: 执行更新（非dry_run模式）
            if not dry_run and (new_records or update_records):
                inserted, updated = self.execute_updates(new_records, update_records)
                print(f"\n更新完成: 新增 {inserted} 条, 更新 {updated} 条")
            elif dry_run:
                print("\n[预览模式] 未执行实际更新")

            result['success'] = True

        except Exception as e:
            result['error'] = str(e)
            print(f"\n错误: {e}")
            raise

        finally:
            self.disconnect_database()

        return result


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='Dunhill商品价格更新')
    parser.add_argument('--dry-run', action='store_true', help='预览模式，不执行实际更新')
    parser.add_argument('--skip-overlap', action='store_true', help='跳过日期重叠检查')
    parser.add_argument('--skip-continuity', action='store_true', help='跳过日期连续性检查（不推荐）')
    parser.add_argument('--config', type=str, help='配置文件路径')
    args = parser.parse_args()

    updater = PriceUpdater(config_path=args.config)

    print("=" * 60)
    print("Dunhill商品价格更新")
    print("=" * 60)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"模式: {'预览' if args.dry_run else '执行'}")
    print("=" * 60)

    result = updater.run(
        dry_run=args.dry_run,
        skip_overlap_check=args.skip_overlap,
        skip_continuity_check=args.skip_continuity
    )

    print("\n" + "=" * 60)
    print("执行结果:")
    print(f"  文件: {result['file']}")
    print(f"  SPU总数: {result['total_spu']}")
    print(f"  新增: {result['new_records']}")
    print(f"  更新: {result['updated_records']}")
    print(f"  状态: {'成功' if result['success'] else '失败'}")
    if result['error']:
        print(f"  错误: {result['error']}")
    print("=" * 60)


if __name__ == '__main__':
    main()

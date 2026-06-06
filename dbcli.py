#!/usr/bin/env python3
"""终端数据库管理客户端工具"""

import os
import sys
import csv
import json
import time
import math
import re
import copy
import shlex
import stat
import sqlite3
import os.path
import readline
import statistics
import termios
import tty
from datetime import datetime
from collections import OrderedDict, Counter, defaultdict

HISTORY_FILE = os.path.expanduser("~/.dbcli_history")
MAX_HISTORY = 500
FAVORITES_FILE = os.path.expanduser("~/.dbcli_favorites.json")
SLOW_LOG_FILE = os.path.expanduser("~/.dbcli_slow.log")
SLOW_QUERY_THRESHOLD_MS = 500


class DBManager:
    def __init__(self):
        self.connections = OrderedDict()
        self.current = None
        self.history = []
        self.favorites = {}
        self.slow_query_threshold_ms = SLOW_QUERY_THRESHOLD_MS
        self.load_history()
        self.load_favorites()

    def set_slow_threshold(self, ms):
        self.slow_query_threshold_ms = float(ms)
        print(f"慢查询阈值已设置为: {self.slow_query_threshold_ms} ms")

    def log_slow_query(self, sql, elapsed_ms):
        if elapsed_ms < self.slow_query_threshold_ms:
            return
        try:
            with open(SLOW_LOG_FILE, "a", encoding="utf-8") as f:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"[{ts}] {elapsed_ms:.2f}ms  {sql[:200]}\n")
        except Exception:
            pass

    def load_history(self):
        if os.path.exists(HISTORY_FILE):
            try:
                readline.read_history_file(HISTORY_FILE)
                with open(HISTORY_FILE, "r") as f:
                    self.history = [line.rstrip("\n") for line in f.readlines()]
            except Exception:
                pass

    def save_history(self):
        try:
            readline.set_history_length(MAX_HISTORY)
            readline.write_history_file(HISTORY_FILE)
        except Exception:
            pass

    def add_history(self, sql):
        self.history.append(sql)
        if len(self.history) > MAX_HISTORY:
            self.history = self.history[-MAX_HISTORY:]
        try:
            with open(HISTORY_FILE, "w") as f:
                for line in self.history:
                    f.write(line + "\n")
        except Exception:
            pass

    def load_favorites(self):
        if os.path.exists(FAVORITES_FILE):
            try:
                with open(FAVORITES_FILE, "r") as f:
                    self.favorites = json.load(f)
            except Exception:
                self.favorites = {}

    def save_favorites(self):
        try:
            with open(FAVORITES_FILE, "w") as f:
                json.dump(self.favorites, f, indent=2)
        except Exception:
            pass

    def connect(self, db_file):
        db_file = os.path.abspath(db_file)
        name = os.path.basename(db_file)
        base_name = name
        counter = 1
        while name in self.connections:
            name = f"{base_name}({counter})"
            counter += 1
        try:
            conn = sqlite3.connect(db_file)
            conn.row_factory = sqlite3.Row
            self.connections[name] = {"conn": conn, "path": db_file}
            if not self.current:
                self.current = name
            print(f"已连接: {name} -> {db_file}")
            return name
        except Exception as e:
            print(f"连接失败: {e}")
            return None

    def disconnect(self, name=None):
        if not name:
            name = self.current
        if not name:
            print("没有活动连接")
            return
        if name in self.connections:
            try:
                self.connections[name]["conn"].close()
            except Exception:
                pass
            del self.connections[name]
            print(f"已断开: {name}")
            if self.current == name:
                self.current = next(iter(self.connections)) if self.connections else None
                if self.current:
                    print(f"当前连接已切换为: {self.current}")
        else:
            print(f"未找到连接: {name}")

    def use(self, name):
        if name in self.connections:
            self.current = name
            print(f"已切换到: {name}")
        else:
            print(f"未找到连接: {name}")

    def list_connections(self):
        if not self.connections:
            print("没有活动连接")
            return
        for i, (name, info) in enumerate(self.connections.items(), 1):
            marker = "*" if name == self.current else " "
            print(f"{marker} [{i}] {name} -> {info['path']}")

    def get_current_conn(self):
        if not self.current:
            print("请先使用 connect 命令连接数据库")
            return None
        return self.connections[self.current]["conn"]


def print_table(rows, headers=None):
    if not rows:
        if headers:
            col_widths = [len(str(h)) for h in headers]
            print("+-" + "-+-".join("-" * w for w in col_widths) + "-+")
            print("| " + " | ".join(str(h).ljust(w) for h, w in zip(headers, col_widths)) + " |")
            print("+-" + "-+-".join("-" * w for w in col_widths) + "-+")
        print("(空结果集)")
        return
    custom_headers = headers is not None
    if headers is None:
        if isinstance(rows[0], sqlite3.Row):
            headers = rows[0].keys()
        else:
            headers = [f"col{i}" for i in range(len(rows[0]))]
    data = []
    for row in rows:
        if isinstance(row, sqlite3.Row):
            if custom_headers:
                vals = []
                for i in range(len(headers)):
                    try:
                        v = row[i]
                    except Exception:
                        v = None
                    vals.append(str(v) if v is not None else "NULL")
                data.append(vals)
            else:
                data.append([str(row[k]) if row[k] is not None else "NULL" for k in headers])
        else:
            data.append([str(v) if v is not None else "NULL" for v in row])
    col_widths = [len(str(h)) for h in headers]
    for row in data:
        for i, val in enumerate(row):
            if len(val) > col_widths[i]:
                col_widths[i] = len(val)
    print("+-" + "-+-".join("-" * w for w in col_widths) + "-+")
    print("| " + " | ".join(str(h).ljust(w) for h, w in zip(headers, col_widths)) + " |")
    print("+-" + "-+-".join("-" * w for w in col_widths) + "-+")
    for row in data:
        print("| " + " | ".join(str(v).ljust(w) for v, w in zip(row, col_widths)) + " |")
    print("+-" + "-+-".join("-" * w for w in col_widths) + "-+")
    print(f"({len(rows)} 行)")


def cmd_tables(db):
    conn = db.get_current_conn()
    if not conn:
        return
    rows = conn.execute(
        "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY name"
    ).fetchall()
    print_table(rows, ["名称", "类型"])


def cmd_describe(db, table_name):
    conn = db.get_current_conn()
    if not conn:
        return
    rows = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    if not rows:
        print(f"表 '{table_name}' 不存在")
        return
    result = []
    for r in rows:
        constraints = []
        if r["notnull"]:
            constraints.append("NOT NULL")
        if r["pk"]:
            constraints.append("PRIMARY KEY")
        if r["dflt_value"] is not None:
            constraints.append(f"DEFAULT {r['dflt_value']}")
        result.append([r["cid"], r["name"], r["type"], ", ".join(constraints)])
    print_table(result, ["ID", "列名", "类型", "约束/默认值"])
    fk_rows = conn.execute(f"PRAGMA foreign_key_list('{table_name}')").fetchall()
    if fk_rows:
        print("\n外键:")
        fk_result = []
        for fk in fk_rows:
            fk_result.append([fk["from"], fk["table"], fk["to"], fk["on_update"], fk["on_delete"]])
        print_table(fk_result, ["列", "引用表", "引用列", "UPDATE", "DELETE"])


def cmd_indexes(db, table_name):
    conn = db.get_current_conn()
    if not conn:
        return
    rows = conn.execute(f"PRAGMA index_list('{table_name}')").fetchall()
    if not rows:
        print(f"表 '{table_name}' 没有索引")
        return
    result = []
    for r in rows:
        idx_cols = conn.execute(f"PRAGMA index_info('{r['name']}')").fetchall()
        cols = ", ".join([ic["name"] for ic in idx_cols])
        unique = "YES" if r["unique"] else "NO"
        result.append([r["seq"], r["name"], cols, unique])
    print_table(result, ["序号", "索引名", "列", "唯一"])


def cmd_schema(db, table_name=None):
    conn = db.get_current_conn()
    if not conn:
        return
    if table_name:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name=?", (table_name,)
        ).fetchone()
        if row and row["sql"]:
            print(row["sql"] + ";")
        else:
            print(f"未找到对象 '{table_name}'")
    else:
        rows = conn.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name"
        ).fetchall()
        for r in rows:
            print(r["sql"] + ";\n")


def execute_sql(db, sql, explain=False, timing=True, return_data=False):
    conn = db.get_current_conn()
    if not conn:
        return None if return_data else None
    sql = sql.strip()
    if not sql:
        return None if return_data else None
    if sql.endswith(";"):
        sql = sql[:-1]
    db.add_history(sql)
    try:
        start = time.time()
        exec_sql = sql
        if explain:
            exec_sql = "EXPLAIN QUERY PLAN " + sql
        cursor = conn.execute(exec_sql)
        rows = cursor.fetchall()
        elapsed = (time.time() - start) * 1000
        db.log_slow_query(sql, elapsed)
        if return_data:
            return {"rows": rows, "elapsed_ms": elapsed}
        if rows:
            print_table(rows)
        else:
            if cursor.description:
                print("(空结果集)")
            else:
                print(f"OK, 影响 {cursor.rowcount} 行")
                conn.commit()
        if timing:
            print(f"耗时: {elapsed:.2f} ms")
    except Exception as e:
        print(f"错误: {e}")
        if return_data:
            return None


def read_multiline_sql():
    lines = []
    prompt = "  -> "
    first = True
    while True:
        try:
            if first:
                line = input("sql> ")
                first = False
            else:
                line = input(prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        lines.append(line)
        combined = "\n".join(lines).strip()
        if combined.endswith(";"):
            return combined
        if combined.lower() in ("exit", "quit", "\\q"):
            return "__exit__"
        if not combined:
            return None


def cmd_insert(db, table_name):
    conn = db.get_current_conn()
    if not conn:
        return
    cols = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    if not cols:
        print(f"表 '{table_name}' 不存在")
        return
    print(f"向表 '{table_name}' 插入数据 (留空跳过, Ctrl+C 取消):")
    values = {}
    for col in cols:
        default_str = f" [默认: {col['dflt_value']}]" if col["dflt_value"] is not None else ""
        pk_auto = " (自增主键)" if col["pk"] and col["type"].upper() == "INTEGER" else ""
        try:
            val = input(f"  {col['name']} ({col['type']}){default_str}{pk_auto}: ")
        except (KeyboardInterrupt, EOFError):
            print("\n已取消")
            return
        if val == "" and col["pk"] and col["type"].upper() == "INTEGER":
            continue
        if val == "":
            if col["dflt_value"] is not None or col["notnull"] == 0:
                continue
        values[col["name"]] = val
    if not values:
        print("没有输入值")
        return
    cols_list = list(values.keys())
    placeholders = ", ".join(["?"] * len(cols_list))
    sql = f"INSERT INTO {table_name} ({', '.join(cols_list)}) VALUES ({placeholders})"
    try:
        conn.execute(sql, list(values.values()))
        conn.commit()
        new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        print(f"插入成功, 新行ID: {new_id}")
    except Exception as e:
        print(f"插入失败: {e}")


def read_single_key():
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            ch2 = sys.stdin.read(1)
            if ch2 == "[":
                ch3 = sys.stdin.read(1)
                return {"A": "UP", "B": "DOWN", "C": "RIGHT", "D": "LEFT"}.get(ch3, None)
            return None
        return ch
    except Exception:
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def render_editable_table(headers, data, row_cursor, col_cursor, changes, page=0, page_size=8):
    total_rows = len(data)
    start_row = page * page_size
    end_row = min(start_row + page_size, total_rows)
    visible_data = data[start_row:end_row]
    disp_widths = [len(str(h)) for h in headers]
    for r in visible_data:
        for i, v in enumerate(r):
            display = str(changes.get((start_row + list(visible_data).index(r), i), v)) if v is not None else "NULL"
            if len(display) > disp_widths[i]:
                disp_widths[i] = min(len(display), 30)
    disp_widths = [max(w, 4) for w in disp_widths]
    sep = "+-" + "-+-".join("-" * w for w in disp_widths) + "-+"
    print("\033[H\033[J", end="")
    print("交互式数据编辑器 - 方向键移动 | Enter编辑 | s保存 | u撤销 | q退出")
    print(f"行: {row_cursor + 1}/{total_rows}  列: {col_cursor + 1}/{len(headers)}  修改: {len(changes)}  页: {page + 1}/{math.ceil(max(total_rows, 1) / page_size)}")
    print(sep)
    header_line = "| " + " | ".join(str(h).ljust(w) for h, w in zip(headers, disp_widths)) + " |"
    print(header_line)
    print(sep)
    for local_idx, r in enumerate(visible_data):
        global_idx = start_row + local_idx
        cells = []
        for ci, v in enumerate(r):
            key = (global_idx, ci)
            if key in changes:
                display_val = str(changes[key]) if changes[key] is not None else "NULL"
                prefix = "*"
            else:
                display_val = str(v) if v is not None else "NULL"
                prefix = " "
            truncated = display_val[:disp_widths[ci]]
            justified = truncated.ljust(disp_widths[ci])
            is_current = global_idx == row_cursor and ci == col_cursor
            if is_current:
                justified = "\033[7m" + justified + "\033[0m"
            cells.append(prefix + justified)
        print("|" + "|".join(cells) + "|")
    print(sep)
    print("[↑↓←→]移动  [Enter]编辑  [s]保存  [u]撤销  [PgUp/PgDn 或 H/L]翻页  [q]取消")


def cmd_update(db, table_name):
    conn = db.get_current_conn()
    if not conn:
        return
    cols = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    if not cols:
        print(f"表 '{table_name}' 不存在")
        return
    pks = [c["name"] for c in cols if c["pk"] > 0]
    headers = [c["name"] for c in cols]
    col_types = {c["name"]: c["type"] for c in cols}
    print(f"更新表 '{table_name}' 数据 (交互式)")
    try:
        where = input("WHERE 条件 (例如: id=1 或 status=0, 留空查前20行): ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n已取消")
        return
    if where:
        query_sql = f"SELECT * FROM {table_name} WHERE {where}"
    else:
        query_sql = f"SELECT * FROM {table_name} LIMIT 20"
    try:
        rows = conn.execute(query_sql).fetchall()
    except Exception as e:
        print(f"查询失败: {e}")
        return
    if not rows:
        print("未找到匹配的行")
        return
    data = [[r[h] for h in headers] for r in rows]
    row_cursor = 0
    col_cursor = 0
    page = 0
    page_size = 8
    changes = {}
    undo_stack = []
    while True:
        total_pages = math.ceil(max(len(data), 1) / page_size)
        render_editable_table(headers, data, row_cursor, col_cursor, changes, page, page_size)
        key = read_single_key()
        if key is None:
            continue
        if key == "q" or key == "Q" or key == "\x03":
            print()
            if changes and not confirm("有未保存的修改，确定退出? (y/n) "):
                continue
            print("已取消")
            return
        elif key == "UP":
            if row_cursor > 0:
                row_cursor -= 1
                if row_cursor < page * page_size:
                    page = row_cursor // page_size
        elif key == "DOWN":
            if row_cursor < len(data) - 1:
                row_cursor += 1
                if row_cursor >= (page + 1) * page_size:
                    page = row_cursor // page_size
        elif key == "LEFT":
            col_cursor = max(0, col_cursor - 1)
        elif key == "RIGHT":
            col_cursor = min(len(headers) - 1, col_cursor + 1)
        elif key == "H" or key == "h":
            page = max(0, page - 1)
            row_cursor = page * page_size
        elif key == "L" or key == "l":
            if page < total_pages - 1:
                page += 1
                row_cursor = min(page * page_size, len(data) - 1)
        elif key == "\r" or key == "\n":
            col_name = headers[col_cursor]
            current_val = changes.get((row_cursor, col_cursor), data[row_cursor][col_cursor])
            display_current = "NULL" if current_val is None else str(current_val)
            print()
            try:
                new_val_str = input(f"编辑 {col_name} ({col_types.get(col_name, '')}) [当前: {display_current}]: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n已取消编辑")
                continue
            if new_val_str == "":
                continue
            undo_stack.append((row_cursor, col_cursor, changes.get((row_cursor, col_cursor), "__NOCHANGE__")))
            if new_val_str.upper() == "NULL":
                changes[(row_cursor, col_cursor)] = None
            else:
                ctype = (col_types.get(col_name) or "").upper()
                if any(t in ctype for t in ("INT",)) and "FLOAT" not in ctype and "DECIMAL" not in ctype:
                    try:
                        changes[(row_cursor, col_cursor)] = int(new_val_str)
                    except ValueError:
                        try:
                            changes[(row_cursor, col_cursor)] = int(float(new_val_str))
                        except ValueError:
                            changes[(row_cursor, col_cursor)] = new_val_str
                elif any(t in ctype for t in ("REAL", "FLOAT", "DECIMAL", "DOUBLE", "NUMERIC")):
                    try:
                        changes[(row_cursor, col_cursor)] = float(new_val_str)
                    except ValueError:
                        changes[(row_cursor, col_cursor)] = new_val_str
                else:
                    changes[(row_cursor, col_cursor)] = new_val_str
        elif key == "s" or key == "S":
            if not changes:
                print("\n无修改，无需保存")
                input("按回车继续...")
                continue
            print(f"\n将保存 {len(changes)} 个单元格修改。")
            if not confirm("确定保存? (y/n) "):
                continue
            total_updated = 0
            failed = 0
            by_row = defaultdict(dict)
            for (ri, ci), val in changes.items():
                by_row[ri][ci] = val
            for ri, cols_modified in by_row.items():
                set_clauses = []
                params = []
                for ci, val in cols_modified.items():
                    set_clauses.append(f"{headers[ci]} = ?")
                    params.append(val)
                if pks:
                    where_clauses = []
                    where_params = []
                    for pk in pks:
                        pk_idx = headers.index(pk)
                        orig_val = data[ri][pk_idx]
                        where_clauses.append(f"{pk} = ?")
                        where_params.append(orig_val)
                    where_clause = " AND ".join(where_clauses)
                else:
                    where_clauses = []
                    where_params = []
                    for ci in range(len(headers)):
                        orig_val = data[ri][ci]
                        where_clauses.append(f"{headers[ci]} IS ?" if orig_val is None else f"{headers[ci]} = ?")
                        where_params.append(orig_val)
                    where_clause = " AND ".join(where_clauses)
                sql = f"UPDATE {table_name} SET {', '.join(set_clauses)} WHERE {where_clause}"
                full_params = params + where_params
                print(f"执行 SQL: {sql}")
                print(f"参数: {full_params}")
                try:
                    cur = conn.execute(sql, full_params)
                    total_updated += cur.rowcount
                    for ci, val in cols_modified.items():
                        data[ri][ci] = val
                except Exception as e:
                    print(f"  更新失败: {e}")
                    failed += 1
            conn.commit()
            print(f"保存完成: 成功 {total_updated} 行, 失败 {failed}")
            changes.clear()
            undo_stack.clear()
            input("按回车继续...")
        elif key == "u" or key == "U":
            if not undo_stack:
                print("\n无操作可撤销")
                input("按回车继续...")
                continue
            ri, ci, prev_val = undo_stack.pop()
            if prev_val == "__NOCHANGE__":
                if (ri, ci) in changes:
                    del changes[(ri, ci)]
            else:
                changes[(ri, ci)] = prev_val
            print("\n已撤销上一次编辑")
            input("按回车继续...")


def cmd_delete(db, table_name):
    conn = db.get_current_conn()
    if not conn:
        return
    cols = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    if not cols:
        print(f"表 '{table_name}' 不存在")
        return
    headers = [c["name"] for c in cols]
    print(f"从表 '{table_name}' 删除数据")
    try:
        where = input("WHERE 条件 (例如: id=1): ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n已取消")
        return
    if not where:
        print("必须指定 WHERE 条件 (为安全起见禁止全表删除)")
        return
    try:
        rows = conn.execute(f"SELECT * FROM {table_name} WHERE {where}").fetchall()
    except Exception as e:
        print(f"查询失败: {e}")
        return
    if not rows:
        print("未找到匹配的行")
        return
    print(f"\n将删除以下 {len(rows)} 行:")
    print_table(rows, headers)
    print()
    if not confirm(f"确定删除这 {len(rows)} 行吗? (y/n) "):
        print("已取消")
        return
    if len(rows) >= 10 and not confirm(f"警告: 将删除 {len(rows)} 行, 再次确认? (y/n) "):
        print("已取消")
        return
    try:
        cur = conn.execute(f"DELETE FROM {table_name} WHERE {where}")
        conn.commit()
        print(f"删除成功, 影响 {cur.rowcount} 行")
    except Exception as e:
        print(f"删除失败: {e}")


def percentile(sorted_data, p):
    if not sorted_data:
        return 0
    k = (len(sorted_data) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    return sorted_data[f] + (sorted_data[c] - sorted_data[f]) * (k - f)


def cmd_profile(db, args_str):
    usage = "用法: profile \"SQL语句\" [次数]\n  示例: profile \"SELECT * FROM users WHERE id=1\" 100"
    if not args_str:
        print(usage)
        return
    try:
        tokens = shlex.split(args_str)
    except ValueError:
        tokens = args_str.split()
    if len(tokens) < 1:
        print(usage)
        return
    iterations = 10
    if len(tokens) >= 2:
        try:
            iterations = int(tokens[-1])
            sql = " ".join(tokens[:-1])
        except ValueError:
            sql = " ".join(tokens)
    else:
        sql = tokens[0]
    if not sql:
        print(usage)
        return
    conn = db.get_current_conn()
    if not conn:
        return
    if sql.endswith(";"):
        sql = sql[:-1]
    print(f"对 SQL 执行 {iterations} 次性能分析...")
    print(f"SQL: {sql}")
    print()
    times = []
    errors = 0
    for i in range(iterations):
        try:
            start = time.perf_counter()
            conn.execute(sql).fetchall()
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)
        except Exception as e:
            errors += 1
            if errors == 1:
                print(f"错误: {e}")
    if not times:
        print("所有执行都失败了")
        return
    times_sorted = sorted(times)
    avg = statistics.mean(times)
    med = statistics.median(times)
    mn = min(times)
    mx = max(times)
    p95 = percentile(times_sorted, 95)
    p99 = percentile(times_sorted, 99)
    std = statistics.pstdev(times) if len(times) > 1 else 0
    print("=" * 50)
    print(f"  性能分析结果 (n={len(times)}, 错误={errors})")
    print("=" * 50)
    print(f"  平均:   {avg:.3f} ms")
    print(f"  中位数: {med:.3f} ms")
    print(f"  最小:   {mn:.3f} ms")
    print(f"  最大:   {mx:.3f} ms")
    print(f"  P95:    {p95:.3f} ms")
    print(f"  P99:    {p99:.3f} ms")
    print(f"  标准差: {std:.3f} ms")
    print("=" * 50)
    bar_max = 50
    max_t = max(times)
    print("\n耗时分布 (每个点代表 1 次执行):")
    buckets = 20
    bucket_size = (max_t - min(times)) / buckets if max_t > min(times) else 1
    counts = [0] * buckets
    for t in times:
        idx = min(int((t - min(times)) / bucket_size), buckets - 1) if bucket_size > 0 else 0
        counts[idx] = max(counts[idx], 0) + 1
    max_count = max(counts) if counts else 1
    for bi in range(buckets):
        low = min(times) + bi * bucket_size
        high = low + bucket_size
        bar_len = int(counts[bi] / max_count * bar_max) if max_count > 0 else 0
        bar = "█" * bar_len
        print(f"  {low:7.2f}-{high:7.2f} ms │ {counts[bi]:4d} {bar}")
    print()


def cmd_analyze(db, table_name=None):
    conn = db.get_current_conn()
    if not conn:
        return
    if table_name:
        tables = [table_name]
    else:
        tables = [r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()]
    if not tables:
        print("没有可用的表")
        return
    history_sqls = db.history[-100:] if db.history else []
    where_cols = Counter()
    for sql in history_sqls:
        sql_upper = sql.upper()
        where_match = re.search(r"WHERE\s+(.+?)(?:ORDER|LIMIT|GROUP|HAVING|;|$)", sql_upper, re.IGNORECASE | re.DOTALL)
        if where_match:
            clause = where_match.group(1)
            cols = re.findall(r"\b([A-Z_][A-Z0-9_]*)\b\s*=", clause)
            for c in cols:
                where_cols[c.lower()] += 1
            and_parts = re.split(r"\bAND\b", clause)
            for part in and_parts:
                cols2 = re.findall(r"\b([A-Z_][A-Z0-9_]*)\b", part)
                for c in cols2:
                    where_cols[c.lower()] += 1
    print()
    print("=" * 60)
    print("  索引使用分析建议")
    print("=" * 60)
    for t in tables:
        cols = conn.execute(f"PRAGMA table_info('{t}')").fetchall()
        if not cols:
            continue
        existing_idx = conn.execute(f"PRAGMA index_list('{t}')").fetchall()
        existing_idx_cols = set()
        for idx in existing_idx:
            idx_cols = conn.execute(f"PRAGMA index_info('{idx['name']}')").fetchall()
            if len(idx_cols) == 1:
                existing_idx_cols.add(idx_cols[0]["name"].lower())
        col_names = [c["name"] for c in cols]
        recommendations = []
        for c in col_names:
            usage = where_cols.get(c.lower(), 0)
            if usage > 0 and c.lower() not in existing_idx_cols:
                ctype = (cols[col_names.index(c)]["type"] or "").upper()
                suitable = True
                if "TEXT" in ctype and "VARCHAR" not in ctype and len(ctype) > 0:
                    pass
                recommendations.append((c, usage, ctype or "UNKNOWN"))
        if recommendations:
            print(f"\n表: {t}")
            for cname, usage, ctype in sorted(recommendations, key=lambda x: -x[1]):
                print(f"  ⚑ 建议为列 '{cname}' ({ctype}) 建索引 (历史 WHERE 中出现 {usage} 次)")
                print(f"     SQL: CREATE INDEX idx_{t}_{cname} ON {t}({cname});")
        try:
            cnt = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except Exception:
            cnt = -1
        print(f"  行数: {cnt}, 已有索引: {len(existing_idx)} 个")
        for idx in existing_idx:
            idx_cols = conn.execute(f"PRAGMA index_info('{idx['name']}')").fetchall()
            col_list = ", ".join([ic["name"] for ic in idx_cols])
            unique = " UNIQUE" if idx["unique"] else ""
            print(f"    • {idx['name']} ({col_list}){unique}")
    if not any(where_cols.values()):
        print("\n提示: 历史查询中无 WHERE 子句样本，建议先执行一些查询后再使用 analyze。")
    print()


def cmd_slow_log(db, args_str=""):
    args = args_str.strip().split() if args_str else []
    sub = args[0].lower() if args else "show"
    if sub == "show":
        n = 20
        if len(args) >= 2:
            try:
                n = int(args[1])
            except ValueError:
                pass
        if not os.path.exists(SLOW_LOG_FILE):
            print("慢查询日志为空")
            return
        try:
            with open(SLOW_LOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            print(f"读取日志失败: {e}")
            return
        if not lines:
            print("慢查询日志为空")
            return
        recent = lines[-n:]
        print(f"显示最近 {len(recent)} 条慢查询 (阈值 {db.slow_query_threshold_ms}ms):")
        print()
        for l in recent:
            print("  " + l.rstrip())
        print()
    elif sub == "threshold":
        if len(args) < 2:
            print(f"当前慢查询阈值: {db.slow_query_threshold_ms} ms")
            print("用法: slow-log threshold <毫秒数>")
            return
        try:
            db.set_slow_threshold(float(args[1]))
        except ValueError:
            print("无效的毫秒数")
    elif sub == "clear":
        try:
            if os.path.exists(SLOW_LOG_FILE):
                os.remove(SLOW_LOG_FILE)
                print("慢查询日志已清除")
            else:
                print("慢查询日志为空")
        except Exception as e:
            print(f"清除失败: {e}")
    else:
        print("用法:\n"
              "  slow-log show [N]       显示最近N条慢查询(默认20)\n"
              "  slow-log threshold <ms> 设置慢查询阈值(毫秒)\n"
              "  slow-log clear          清除慢查询日志")


def cmd_export(db, sql, filename, fmt="csv"):
    conn = db.get_current_conn()
    if not conn:
        return
    try:
        cursor = conn.execute(sql)
        rows = cursor.fetchall()
        if not rows:
            print("查询结果为空, 不导出")
            return
        headers = rows[0].keys()
        fmt = fmt.lower()
        if fmt == "csv":
            with open(filename, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                for row in rows:
                    writer.writerow([row[k] for k in headers])
            print(f"已导出 {len(rows)} 行到 {filename} (CSV)")
        elif fmt == "json":
            data = [dict(row) for row in rows]
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            print(f"已导出 {len(rows)} 行到 {filename} (JSON)")
        elif fmt == "sql":
            with open(filename, "w", encoding="utf-8") as f:
                for row in rows:
                    cols = ", ".join(headers)
                    vals = []
                    for k in headers:
                        v = row[k]
                        if v is None:
                            vals.append("NULL")
                        elif isinstance(v, (int, float)):
                            vals.append(str(v))
                        else:
                            vals.append("'" + str(v).replace("'", "''") + "'")
                    f.write(f"INSERT INTO exported ({cols}) VALUES ({', '.join(vals)});\n")
            print(f"已导出 {len(rows)} 行到 {filename} (SQL INSERT)")
        else:
            print(f"不支持的格式: {fmt}")
    except Exception as e:
        print(f"导出失败: {e}")


def cmd_run(db, filename):
    conn = db.get_current_conn()
    if not conn:
        return
    if not os.path.exists(filename):
        print(f"文件不存在: {filename}")
        return
    try:
        with open(filename, "r", encoding="utf-8") as f:
            content = f.read()
        statements = [s.strip() for s in content.split(";") if s.strip()]
        total = 0
        for stmt in statements:
            if not stmt:
                continue
            try:
                conn.execute(stmt)
                total += 1
            except Exception as e:
                print(f"执行失败: {e}\n  SQL: {stmt[:100]}")
        conn.commit()
        print(f"执行完成, 成功 {total} 条语句")
    except Exception as e:
        print(f"读取文件失败: {e}")


def cmd_backup(db, output_file):
    conn = db.get_current_conn()
    if not conn:
        return
    try:
        backup_conn = sqlite3.connect(output_file)
        conn.backup(backup_conn)
        backup_conn.close()
        print(f"数据库已备份到: {output_file}")
    except Exception as e:
        print(f"备份失败: {e}")


def cmd_restore(db, input_file):
    conn = db.get_current_conn()
    if not conn:
        return
    if not os.path.exists(input_file):
        print(f"文件不存在: {input_file}")
        return
    if not confirm("恢复将覆盖当前数据库, 确定吗? (y/n) "):
        print("已取消")
        return
    try:
        source = sqlite3.connect(input_file)
        source.backup(conn)
        source.close()
        conn.commit()
        print("数据库恢复成功")
    except Exception as e:
        print(f"恢复失败: {e}")


def cmd_vacuum(db):
    conn = db.get_current_conn()
    if not conn:
        return
    try:
        start = time.time()
        conn.execute("VACUUM")
        elapsed = (time.time() - start) * 1000
        print(f"VACUUM 完成, 耗时 {elapsed:.2f} ms")
    except Exception as e:
        print(f"VACUUM 失败: {e}")


def cmd_integrity_check(db):
    conn = db.get_current_conn()
    if not conn:
        return
    try:
        rows = conn.execute("PRAGMA integrity_check").fetchall()
        for r in rows:
            print(r[0])
    except Exception as e:
        print(f"检查失败: {e}")


def cmd_stats(db):
    conn = db.get_current_conn()
    if not conn:
        return
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    if not tables:
        print("没有用户表")
        return
    result = []
    for t in tables:
        tname = t["name"]
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {tname}").fetchone()[0]
        except Exception:
            count = -1
        try:
            size_row = conn.execute(
                "SELECT SUM(pgsize) FROM dbstat WHERE name=?", (tname,)
            ).fetchone()
            size = size_row[0] if size_row and size_row[0] else 0
        except Exception:
            size = 0
        result.append([tname, count, format_size(size)])
    print_table(result, ["表名", "行数", "大小"])


def format_size(n):
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} TB"


def is_numeric_value(v):
    if v is None:
        return False
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, str):
        try:
            float(v)
            return True
        except (ValueError, TypeError):
            return False
    return False


def to_numeric(v):
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except (ValueError, TypeError):
            return None
    return None


def is_date_like(v):
    if v is None:
        return False
    if not isinstance(v, str):
        return False
    patterns = [
        r"^\d{4}-\d{2}-\d{2}$",
        r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}",
        r"^\d{4}/\d{2}/\d{2}",
        r"^\d{2}/\d{2}/\d{4}",
    ]
    for p in patterns:
        if re.match(p, v):
            return True
    return False


def detect_chart_axes(rows, headers):
    if not rows or not headers:
        return None, None
    numeric_cols = []
    text_cols = []
    for i, h in enumerate(headers):
        sample_vals = [r[i] for r in rows[:min(10, len(rows))]]
        numeric_count = sum(1 for v in sample_vals if is_numeric_value(v))
        date_count = sum(1 for v in sample_vals if is_date_like(v))
        if numeric_count >= len(sample_vals) * 0.7 and numeric_count > 0:
            numeric_cols.append(i)
        elif date_count >= len(sample_vals) * 0.5 or (numeric_count == 0 and date_count > 0):
            text_cols.append(i)
        else:
            text_cols.append(i)
    x_col = text_cols[0] if text_cols else (numeric_cols[0] if numeric_cols else 0)
    y_col = numeric_cols[-1] if numeric_cols else (len(headers) - 1)
    return x_col, y_col


def draw_bar_chart(rows, x_col, y_col, headers, width=60, height=10):
    if not rows:
        print("(空数据)")
        return
    labels = []
    values = []
    for r in rows:
        labels.append(str(r[x_col]) if r[x_col] is not None else "NULL")
        v = to_numeric(r[y_col])
        values.append(v if v is not None else 0.0)
    if not values:
        print("(无可绘制数值)")
        return
    max_val = max(values) if max(values) > 0 else 1
    n = len(values)
    bar_area_height = height
    print()
    for row_idx in range(bar_area_height, 0, -1):
        threshold = (row_idx / bar_area_height) * max_val
        line = f"{threshold:>8.2f} │"
        for v in values:
            if v >= threshold:
                line += " ██"
            else:
                line += "   "
        print(line)
    print("         └" + "─" * (3 * n + 1))
    x_header = headers[x_col] if x_col < len(headers) else "X"
    y_header = headers[y_col] if y_col < len(headers) else "Y"
    print(f"           {x_header} vs {y_header} (n={n})")
    max_label_len = max((len(l) for l in labels), default=4)
    label_rows_needed = math.ceil(max_label_len / 2)
    for lr in range(label_rows_needed):
        line = "           "
        for l in labels:
            chunk_start = lr * 2
            chunk = l[chunk_start:chunk_start + 2] if chunk_start < len(l) else "  "
            chunk = chunk.ljust(2)
            line += " " + chunk
        print(line)
    print()


def draw_line_chart(rows, x_col, y_col, headers, width=60, height=10):
    if not rows:
        print("(空数据)")
        return
    labels = []
    values = []
    for r in rows:
        labels.append(str(r[x_col]) if r[x_col] is not None else "NULL")
        v = to_numeric(r[y_col])
        values.append(v if v is not None else 0.0)
    if not values:
        print("(无可绘制数值)")
        return
    n = len(values)
    max_val = max(values) if max(values) > 0 else 1
    min_val = min(values) if min(values) < 0 else 0
    val_range = max_val - min_val if max_val != min_val else 1
    plot_width = min(width, max(n * 2, 20))
    def col_to_x(idx):
        if n <= 1:
            return 0
        return int((idx / (n - 1)) * (plot_width - 1))
    points = {}
    for i, v in enumerate(values):
        x = col_to_x(i)
        y_norm = (v - min_val) / val_range
        y = int(round(y_norm * (height - 1)))
        points[(x, y)] = (i, v)
    x_axis_y = 0
    print()
    for row_y in range(height - 1, -1, -1):
        val = min_val + (row_y / (height - 1)) * val_range if height > 1 else max_val
        line = f"{val:>8.2f} │"
        for x in range(plot_width):
            if (x, row_y) in points:
                line += "●"
            elif row_y == x_axis_y and min_val <= 0 <= max_val:
                line += "─"
            else:
                line += " "
        print(line)
    print("         └" + "─" * plot_width)
    x_header = headers[x_col] if x_col < len(headers) else "X"
    y_header = headers[y_col] if y_col < len(headers) else "Y"
    print(f"           {x_header} vs {y_header} (n={n})")
    if n <= 10:
        label_line = "           "
        for i, l in enumerate(labels):
            x = col_to_x(i)
            while len(label_line) < x + 11:
                label_line += " "
            display = l[:3]
            label_line = label_line[:x + 11] + display + label_line[x + 11 + len(display):]
        print(label_line)
    print()


def draw_pie_chart(rows, x_col, y_col, headers, width=50, height=10):
    if not rows:
        print("(空数据)")
        return
    labels = []
    values = []
    for r in rows:
        labels.append(str(r[x_col]) if r[x_col] is not None else "NULL")
        v = to_numeric(r[y_col])
        values.append(abs(v if v is not None else 0.0))
    total = sum(values)
    if total <= 0:
        print("(总和非正，无法绘制饼图)")
        return
    print()
    print(f"  {headers[y_col] if y_col < len(headers) else 'Y'} 分布 (合计: {total:.2f})")
    print()
    colors = ["█", "▓", "▒", "░", "●", "◆", "▲", "■", "★", "✦"]
    for i, (lab, val) in enumerate(zip(labels, values)):
        pct = val / total * 100
        bar_len = int(round(pct / 100 * 40))
        fill = colors[i % len(colors)] * bar_len
        print(f"  {colors[i % len(colors)]} {lab[:20]:<20} {pct:5.1f}%  {fill} {val:.2f}")
    print()


def draw_histogram(rows, x_col, y_col, headers, width=60, height=10, bins=10):
    if not rows:
        print("(空数据)")
        return
    col_idx = y_col
    if y_col < 0 or y_col >= len(headers):
        for i in range(len(headers)):
            sample = [r[i] for r in rows[:5]]
            if all(is_numeric_value(v) for v in sample if v is not None):
                col_idx = i
                break
    values = []
    for r in rows:
        v = to_numeric(r[col_idx])
        if v is not None:
            values.append(v)
    if len(values) < 2:
        print("(数值不足)")
        return
    min_v = min(values)
    max_v = max(values)
    if max_v == min_v:
        max_v = min_v + 1
    bin_edges = [min_v + (max_v - min_v) * i / bins for i in range(bins + 1)]
    counts = [0] * bins
    for v in values:
        idx = min(int((v - min_v) / (max_v - min_v) * bins), bins - 1)
        counts[idx] += 1
    max_count = max(counts) if max(counts) > 0 else 1
    print()
    col_name = headers[col_idx] if col_idx < len(headers) else "value"
    print(f"  {col_name} 的直方图 (n={len(values)}, bins={bins})")
    print()
    for row_y in range(height, 0, -1):
        threshold = (row_y / height) * max_count
        line = f"{int(round(threshold)):>6d} │"
        for c in counts:
            if c >= threshold:
                line += " ███"
            else:
                line += "    "
        print(line)
    print("       └" + "─" * (4 * bins + 1))
    range_line = "        "
    for i in range(bins):
        label = f"{bin_edges[i]:.0f}"
        range_line += " " + label.ljust(3)[:3]
    print(range_line)
    last_label = f"{bin_edges[-1]:.0f}"
    print(f"        {' ' * (4 * bins)}{last_label}")
    print()


def cmd_chart(db, args_str):
    usage = (
        "用法: chart <TYPE> \"SQL查询\" [--width W] [--height H] [--x COL] [--y COL]\n"
        "  TYPE: bar | line | pie | histogram\n"
        "  示例: chart bar \"SELECT category_id, COUNT(*) c FROM products GROUP BY category_id\""
    )
    if not args_str:
        print(usage)
        return
    try:
        tokens = shlex.split(args_str)
    except ValueError:
        tokens = args_str.split()
    if len(tokens) < 2:
        print(usage)
        return
    chart_type = tokens[0].lower()
    if chart_type not in ("bar", "line", "pie", "histogram"):
        print(f"不支持的图表类型: {chart_type}")
        print(usage)
        return
    sql = None
    width = 60
    height = 10
    x_col_override = None
    y_col_override = None
    i = 1
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--width" and i + 1 < len(tokens):
            width = int(tokens[i + 1])
            i += 2
        elif tok == "--height" and i + 1 < len(tokens):
            height = int(tokens[i + 1])
            i += 2
        elif tok == "--x" and i + 1 < len(tokens):
            x_col_override = tokens[i + 1]
            i += 2
        elif tok == "--y" and i + 1 < len(tokens):
            y_col_override = tokens[i + 1]
            i += 2
        elif sql is None:
            sql = tok
            i += 1
        else:
            i += 1
    if not sql:
        print("请提供 SQL 查询")
        print(usage)
        return
    conn = db.get_current_conn()
    if not conn:
        return
    try:
        cursor = conn.execute(sql)
        rows = cursor.fetchall()
    except Exception as e:
        print(f"查询失败: {e}")
        return
    if not rows:
        print("(空结果集)")
        return
    if isinstance(rows[0], sqlite3.Row):
        headers = rows[0].keys()
        rows = [[r[k] for k in headers] for r in rows]
    else:
        headers = [f"col{i}" for i in range(len(rows[0]))]
    if x_col_override is not None:
        if x_col_override.isdigit():
            x_col = int(x_col_override)
        else:
            x_col = list(headers).index(x_col_override) if x_col_override in headers else 0
    else:
        x_col, _ = detect_chart_axes(rows, headers)
    if y_col_override is not None:
        if y_col_override.isdigit():
            y_col = int(y_col_override)
        else:
            y_col = list(headers).index(y_col_override) if y_col_override in headers else len(headers) - 1
    else:
        _, y_col = detect_chart_axes(rows, headers)
    if x_col is None:
        x_col = 0
    if y_col is None:
        y_col = len(headers) - 1
    print(f"[图表类型: {chart_type}] X={headers[x_col]}, Y={headers[y_col]}, 数据行={len(rows)}")
    if chart_type == "bar":
        draw_bar_chart(rows, x_col, y_col, headers, width=width, height=height)
    elif chart_type == "line":
        draw_line_chart(rows, x_col, y_col, headers, width=width, height=height)
    elif chart_type == "pie":
        draw_pie_chart(rows, x_col, y_col, headers, width=width, height=height)
    elif chart_type == "histogram":
        draw_histogram(rows, x_col, y_col, headers, width=width, height=height)


DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y/%m/%d",
    "%Y/%m/%d %H:%M:%S",
    "%d/%m/%Y",
    "%m/%d/%Y",
]


def parse_date(s):
    if not isinstance(s, str):
        return None
    s = s.strip()
    for fmt in DATE_FORMATS:
        try:
            datetime.strptime(s, fmt)
            return fmt
        except (ValueError, TypeError):
            continue
    return None


def cmd_audit(db, table_name):
    conn = db.get_current_conn()
    if not conn:
        return
    cols = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    if not cols:
        print(f"表 '{table_name}' 不存在")
        return
    try:
        rows = conn.execute(f"SELECT * FROM {table_name}").fetchall()
    except Exception as e:
        print(f"读取表数据失败: {e}")
        return
    total_rows = len(rows)
    print()
    print("=" * 60)
    print(f"  数据质量审计报告: {table_name}")
    print(f"  总行数: {total_rows}")
    print("=" * 60)
    issues = 0
    print()
    print("【1】NULL 比例超过 30% 的列:")
    null_issues = []
    for col in cols:
        cid = col["cid"]
        cname = col["name"]
        null_count = sum(1 for r in rows if r[cid] is None)
        pct = (null_count / total_rows * 100) if total_rows > 0 else 0
        if pct > 30:
            null_issues.append((cname, null_count, pct))
    if null_issues:
        for cname, cnt, pct in null_issues:
            print(f"  ⚠ {cname}: {cnt}/{total_rows} ({pct:.1f}%) 为 NULL")
            issues += 1
    else:
        print("  ✓ 无 (所有列 NULL 比例 ≤ 30%)")
    print()
    print("【2】疑似重复行 (所有列值相同):")
    seen = {}
    dup_count = 0
    for r in rows:
        key = tuple(r[c] for c in range(len(cols)))
        if key in seen:
            seen[key] += 1
            if seen[key] == 2:
                dup_count += 1
        else:
            seen[key] = 1
    if dup_count > 0:
        print(f"  ⚠ 发现 {dup_count} 组重复行")
        issues += dup_count
        for key, cnt in list(seen.items())[:5]:
            if cnt > 1:
                preview = ", ".join(str(v)[:20] for v in list(key)[:5])
                print(f"    重复 {cnt} 次: {preview}...")
    else:
        print("  ✓ 无重复行")
    print()
    print("【3】数值列异常值 (超过 3 倍标准差):")
    outlier_found = False
    for col in cols:
        ctype = col["type"].upper() if col["type"] else ""
        is_num_type = any(t in ctype for t in ("INT", "REAL", "FLOAT", "DECIMAL", "NUMERIC", "DOUBLE"))
        if not is_num_type:
            sample = [r[col["cid"]] for r in rows[:20]]
            if not all(is_numeric_value(v) for v in sample if v is not None):
                continue
        values = []
        for r in rows:
            v = to_numeric(r[col["cid"]])
            if v is not None:
                values.append(v)
        if len(values) < 3:
            continue
        try:
            mean = statistics.mean(values)
            stdev = statistics.pstdev(values)
        except Exception:
            continue
        if stdev == 0:
            continue
        outliers = [v for v in values if abs(v - mean) > 3 * stdev]
        if outliers:
            outlier_found = True
            print(f"  ⚠ {col['name']}: mean={mean:.2f}, stdev={stdev:.2f}, 异常值 {len(outliers)} 个")
            issues += 1
            if len(outliers) <= 5:
                print(f"    值: {outliers}")
            else:
                print(f"    前5个: {outliers[:5]}")
    if not outlier_found:
        print("  ✓ 无明显异常值")
    print()
    print("【4】日期列格式不一致:")
    date_issue_found = False
    for col in cols:
        cname = col["name"]
        is_date_col = "date" in cname.lower() or "time" in cname.lower() or cname.lower().endswith("_at")
        if not is_date_col:
            continue
        formats_used = Counter()
        parseable = 0
        unparseable = 0
        sample_values = []
        for r in rows:
            v = r[col["cid"]]
            if v is None:
                continue
            fmt = parse_date(v if isinstance(v, str) else str(v))
            if fmt:
                formats_used[fmt] += 1
                parseable += 1
            else:
                unparseable += 1
                if len(sample_values) < 3:
                    sample_values.append(str(v)[:50])
        if parseable == 0 and unparseable == 0:
            continue
        if len(formats_used) > 1 or unparseable > 0:
            date_issue_found = True
            print(f"  ⚠ {cname}: 检测到 {len(formats_used)} 种日期格式, {unparseable} 个无法解析")
            issues += 1
            for fmt, cnt in formats_used.most_common():
                print(f"    {fmt}: {cnt} 行")
            if sample_values:
                print(f"    无法解析示例: {sample_values}")
    if not date_issue_found:
        print("  ✓ 日期格式一致")
    print()
    print("【5】外键引用完整性:")
    fk_rows = conn.execute(f"PRAGMA foreign_key_list('{table_name}')").fetchall()
    if not fk_rows:
        print("  (无外键)")
    else:
        fk_issues = 0
        for fk in fk_rows:
            from_col = fk["from"]
            ref_table = fk["table"]
            ref_col = fk["to"]
            try:
                orphans = conn.execute(
                    f"SELECT COUNT(*) FROM {table_name} t "
                    f"WHERE t.{from_col} IS NOT NULL "
                    f"AND NOT EXISTS (SELECT 1 FROM {ref_table} r WHERE r.{ref_col} = t.{from_col})"
                ).fetchone()[0]
                if orphans > 0:
                    fk_issues += 1
                    issues += 1
                    print(f"  ⚠ {table_name}.{from_col} → {ref_table}.{ref_col}: {orphans} 条悬空引用")
            except Exception as e:
                print(f"  ? 检查 {from_col} 失败: {e}")
        if fk_issues == 0:
            print("  ✓ 所有外键引用完整")
    print()
    print("=" * 60)
    if issues == 0:
        print(f"  审计完成: 未发现问题 ✓")
    else:
        print(f"  审计完成: 发现 {issues} 个问题 ⚠")
    print("=" * 60)
    print()


def get_table_schema(conn, table_name):
    cols = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    return [
        {
            "cid": c["cid"],
            "name": c["name"],
            "type": c["type"],
            "notnull": c["notnull"],
            "dflt_value": c["dflt_value"],
            "pk": c["pk"],
        }
        for c in cols
    ]


def get_tables(conn):
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [(r["name"], r["sql"]) for r in rows]


def get_table_pks(conn, table_name):
    cols = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    return [c["name"] for c in cols if c["pk"] > 0]


def cmd_migrate(db, args_str):
    usage = (
        "用法:\n"
        "  migrate schema <源库> <目标库>           复制表结构\n"
        "  migrate data <源库> <目标库> [表...]      复制数据(可选表过滤)\n"
        "  migrate diff <库A> <库B>                 对比两库结构差异\n"
        "示例:\n"
        "  migrate schema source.db target.db\n"
        "  migrate data source.db target.db users orders\n"
        "  migrate diff old.db new.db"
    )
    if not args_str:
        print(usage)
        return
    try:
        tokens = shlex.split(args_str)
    except ValueError:
        tokens = args_str.split()
    if len(tokens) < 3:
        print(usage)
        return
    sub = tokens[0].lower()
    src_file = tokens[1]
    dst_file = tokens[2]
    table_filter = tokens[3:] if len(tokens) > 3 else None
    if not os.path.exists(src_file):
        print(f"源库不存在: {src_file}")
        return
    if sub not in ("schema", "data", "diff"):
        print(f"未知子命令: {sub}")
        print(usage)
        return
    try:
        src_conn = sqlite3.connect(src_file)
        src_conn.row_factory = sqlite3.Row
    except Exception as e:
        print(f"打开源库失败: {e}")
        return
    if sub == "diff":
        if not os.path.exists(dst_file):
            print(f"目标库不存在: {dst_file}")
            src_conn.close()
            return
        try:
            dst_conn = sqlite3.connect(dst_file)
            dst_conn.row_factory = sqlite3.Row
        except Exception as e:
            print(f"打开目标库失败: {e}")
            src_conn.close()
            return
        _migrate_diff(src_conn, dst_conn, src_file, dst_file)
        dst_conn.close()
        src_conn.close()
        return
    try:
        dst_existed = os.path.exists(dst_file)
        dst_conn = sqlite3.connect(dst_file)
        dst_conn.row_factory = sqlite3.Row
        dst_conn.execute("PRAGMA foreign_keys = OFF")
    except Exception as e:
        print(f"打开/创建目标库失败: {e}")
        src_conn.close()
        return
    if sub == "schema":
        _migrate_schema(src_conn, dst_conn, table_filter)
        dst_conn.commit()
    elif sub == "data":
        if not dst_existed:
            _migrate_schema(src_conn, dst_conn, table_filter)
            dst_conn.commit()
        _migrate_data(src_conn, dst_conn, table_filter)
        dst_conn.commit()
    dst_conn.close()
    src_conn.close()


def _migrate_schema(src_conn, dst_conn, table_filter=None):
    tables = get_tables(src_conn)
    created = 0
    skipped = 0
    for tname, tsql in tables:
        if table_filter and tname not in table_filter:
            continue
        try:
            existing = dst_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tname,)
            ).fetchone()
            if existing:
                print(f"  跳过(已存在): {tname}")
                skipped += 1
                continue
            dst_conn.execute(tsql)
            created += 1
            print(f"  ✓ 创建表: {tname}")
        except Exception as e:
            print(f"  ✗ 创建表 {tname} 失败: {e}")
    try:
        idx_rows = src_conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL"
        ).fetchall()
        for idx in idx_rows:
            try:
                dst_conn.execute(idx["sql"])
                print(f"  ✓ 创建索引: {idx['name']}")
            except Exception:
                pass
    except Exception:
        pass
    print(f"完成: 创建 {created} 张表, 跳过 {skipped} 张")


def _migrate_data(src_conn, dst_conn, table_filter=None):
    tables = [r[0] for r in get_tables(src_conn)]
    total_rows = 0
    for tname in tables:
        if table_filter and tname not in table_filter:
            continue
        try:
            src_cols = get_table_schema(src_conn, tname)
            dst_cols = get_table_schema(dst_conn, tname)
            if not dst_cols:
                print(f"  跳过(目标无此表): {tname}")
                continue
            dst_col_names = {c["name"] for c in dst_cols}
            common_cols = [c["name"] for c in src_cols if c["name"] in dst_col_names]
            pks = get_table_pks(src_conn, tname)
            src_rows = src_conn.execute(f"SELECT * FROM {tname}").fetchall()
            if not src_rows:
                print(f"  {tname}: 空表")
                continue
            inserted = 0
            conflicts = 0
            placeholders = ", ".join(["?"] * len(common_cols))
            col_list = ", ".join(common_cols)
            auto_pk = len(pks) == 1 and pks[0] in common_cols
            dst_pk_set = set()
            if auto_pk:
                pk_name = pks[0]
                try:
                    existing_pks = dst_conn.execute(f"SELECT {pk_name} FROM {tname}").fetchall()
                    dst_pk_set = {r[0] for r in existing_pks if r[0] is not None}
                except Exception:
                    pass
            for r in src_rows:
                row_dict = dict(r)
                values = [row_dict.get(c) for c in common_cols]
                if auto_pk and pk_name in row_dict and row_dict[pk_name] in dst_pk_set:
                    conflicts += 1
                    new_vals = []
                    for c, v in zip(common_cols, values):
                        if c == pk_name:
                            new_vals.append(None)
                        else:
                            new_vals.append(v)
                    values = new_vals
                    insert_cols = [c for c in common_cols if c != pk_name]
                    insert_ph = ", ".join(["?"] * len(insert_cols))
                    insert_clause = ", ".join(insert_cols)
                    final_vals = [v for c, v in zip(common_cols, values) if c != pk_name]
                    try:
                        dst_conn.execute(
                            f"INSERT INTO {tname} ({insert_clause}) VALUES ({insert_ph})",
                            final_vals,
                        )
                        inserted += 1
                    except Exception as e:
                        print(f"    ! 插入行失败: {e}")
                else:
                    try:
                        dst_conn.execute(
                            f"INSERT OR IGNORE INTO {tname} ({col_list}) VALUES ({placeholders})",
                            values,
                        )
                        inserted += 1
                    except Exception as e:
                        print(f"    ! 插入行失败: {e}")
            total_rows += inserted
            conflict_str = f" (ID冲突重分配 {conflicts} 条)" if conflicts else ""
            print(f"  ✓ {tname}: 插入 {inserted}/{len(src_rows)} 行{conflict_str}")
        except Exception as e:
            print(f"  ✗ 复制 {tname} 失败: {e}")
    print(f"完成: 共插入 {total_rows} 行")


def _migrate_diff(conn_a, conn_b, name_a, name_b):
    tables_a = dict(get_tables(conn_a))
    tables_b = dict(get_tables(conn_b))
    only_a = set(tables_a) - set(tables_b)
    only_b = set(tables_b) - set(tables_a)
    common = set(tables_a) & set(tables_b)
    print()
    print("=" * 60)
    print(f"  Schema 差异对比: {name_a} vs {name_b}")
    print("=" * 60)
    print()
    if only_a:
        print(f"【仅在 A 存在的表 ({len(only_a)})】:")
        for t in sorted(only_a):
            print(f"  + {t}")
        print()
    if only_b:
        print(f"【仅在 B 存在的表 ({len(only_b)})】:")
        for t in sorted(only_b):
            print(f"  - {t}")
        print()
    diff_tables = []
    for t in sorted(common):
        cols_a = get_table_schema(conn_a, t)
        cols_b = get_table_schema(conn_b, t)
        a_map = {c["name"]: c for c in cols_a}
        b_map = {c["name"]: c for c in cols_b}
        a_names = set(a_map)
        b_names = set(b_map)
        only_cols_a = a_names - b_names
        only_cols_b = b_names - a_names
        type_changed = []
        for cname in a_names & b_names:
            ca = a_map[cname]
            cb = b_map[cname]
            if (ca["type"] or "").upper() != (cb["type"] or "").upper():
                type_changed.append((cname, ca["type"], cb["type"]))
        if only_cols_a or only_cols_b or type_changed:
            diff_tables.append((t, only_cols_a, only_cols_b, type_changed))
    if diff_tables:
        print(f"【结构有差异的表 ({len(diff_tables)})】:")
        for t, ca, cb, tc in diff_tables:
            print(f"  * {t}:")
            for c in sorted(ca):
                print(f"      + 列 {c} (仅A)")
            for c in sorted(cb):
                print(f"      - 列 {c} (仅B)")
            for cname, ta, tb in tc:
                print(f"      ~ 列 {cname}: A='{ta}' vs B='{tb}'")
        print()
    if not only_a and not only_b and not diff_tables:
        print("  ✓ 两库结构完全一致")
    print("=" * 60)
    print()


def confirm(prompt):
    try:
        ans = input(prompt).strip().lower()
        return ans in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def cmd_history(db):
    for i, h in enumerate(reversed(db.history[-20:]), 1):
        print(f"  {len(db.history) - i + 1:4d}  {h[:120]}")
    print(f"共 {len(db.history)} 条历史记录")


def cmd_run_history(db, n):
    if 1 <= n <= len(db.history):
        sql = db.history[n - 1]
        print(f"执行: {sql}")
        execute_sql(db, sql)
    else:
        print(f"无效的历史记录编号: {n}")


def cmd_save_favorite(db, name, sql):
    db.favorites[name] = sql
    db.save_favorites()
    print(f"已保存收藏: {name}")


def cmd_list_favorites(db):
    if not db.favorites:
        print("没有收藏")
        return
    for name, sql in db.favorites.items():
        print(f"  {name}: {sql[:100]}")


def cmd_run_favorite(db, name):
    if name in db.favorites:
        sql = db.favorites[name]
        print(f"执行收藏 '{name}': {sql}")
        execute_sql(db, sql)
    else:
        print(f"未找到收藏: {name}")


def print_help():
    print("""命令列表:
  连接管理:
    connect FILE         连接/新建 SQLite 数据库
    use NAME             切换到指定连接
    connections          列出所有连接
    disconnect [NAME]    断开连接(默认当前)

  Schema 浏览:
    tables               列出所有表/视图
    describe TABLE       显示表结构
    indexes TABLE        列出表索引
    .schema [TABLE]      显示建表SQL

  查询执行:
    SQL语句;             执行SQL(多行,分号结束)
    EXPLAIN SQL;         显示查询计划

  数据操作:
    insert TABLE         交互式插入
    update TABLE         交互式表格编辑器(方向键/Enter编辑/s保存/u撤销)
    delete TABLE         交互式删除(显示待删行并二次确认)
    export SQL FILE FMT  导出查询(CSV/JSON/SQL)
    .run FILE            批量执行SQL文件

  数据可视化:
    chart TYPE SQL [--w W --h H --x COL --y COL]
                         ASCII图表: bar/line/pie/histogram

  数据质量:
    audit TABLE          数据质量审计(NULL/重复/异常值/日期格式/外键)

  数据迁移:
    migrate schema SRC DST   复制表结构
    migrate data SRC DST [T...] 复制数据(按表过滤,自动处理ID冲突)
    migrate diff A B         对比两库结构差异

  性能分析:
    profile SQL [N]      对SQL执行N次计时统计(平均/最大/最小/P95)
    analyze [TABLE]      分析索引使用建议(基于历史WHERE子句)
    slow-log show [N]    显示慢查询日志
    slow-log threshold MS 设置慢查询阈值(毫秒)
    slow-log clear       清除慢查询日志

  数据库工具:
    backup FILE          备份数据库
    restore FILE         恢复数据库
    vacuum               VACUUM优化
    integrity_check      完整性检查
    stats                表统计信息

  查询历史:
    history              显示最近历史
    !N                   执行第N条历史
    .save NAME SQL       收藏SQL
    .favorites           列出收藏
    .run NAME            执行收藏

  其他:
    help                 显示帮助
    exit/quit/\\q         退出
""")


def process_command(db, line):
    line = line.strip()
    if not line:
        return True
    if line.lower() in ("exit", "quit", "\\q"):
        return False
    if line.lower() in ("help", "\\?"):
        print_help()
        return True
    if line.lower() == "tables":
        cmd_tables(db)
        return True
    if line.lower().startswith("describe "):
        cmd_describe(db, line[9:].strip())
        return True
    if line.lower().startswith("indexes "):
        cmd_indexes(db, line[8:].strip())
        return True
    if line.startswith(".schema"):
        parts = line.split(maxsplit=1)
        table = parts[1].strip() if len(parts) > 1 else None
        cmd_schema(db, table)
        return True
    if line.lower().startswith("connect "):
        db.connect(line[8:].strip())
        return True
    if line.lower().startswith("use "):
        db.use(line[4:].strip())
        return True
    if line.lower() == "connections":
        db.list_connections()
        return True
    if line.lower().startswith("disconnect"):
        parts = line.split(maxsplit=1)
        name = parts[1].strip() if len(parts) > 1 else None
        db.disconnect(name)
        return True
    if line.lower().startswith("insert "):
        cmd_insert(db, line[7:].strip())
        return True
    if line.lower().startswith("update "):
        cmd_update(db, line[7:].strip())
        return True
    if line.lower().startswith("delete "):
        cmd_delete(db, line[7:].strip())
        return True
    if line.lower().startswith("chart "):
        cmd_chart(db, line[6:].strip())
        return True
    if line.lower().startswith("audit "):
        cmd_audit(db, line[6:].strip())
        return True
    if line.lower().startswith("migrate "):
        cmd_migrate(db, line[8:].strip())
        return True
    if line.lower().startswith("profile "):
        cmd_profile(db, line[8:].strip())
        return True
    if line.lower().startswith("analyze"):
        rest = line[8:].strip()
        cmd_analyze(db, rest if rest else None)
        return True
    if line.lower().startswith("slow-log") or line.lower().startswith("slow_log"):
        idx = line.find(" ")
        rest = line[idx + 1:].strip() if idx > 0 else ""
        cmd_slow_log(db, rest)
        return True
    if line.lower().startswith("export "):
        rest = line[7:].strip()
        if not rest:
            print("用法: export \"SQL语句\" 文件路径 [格式]")
            print("  格式: csv (默认), json, sql")
            print("  示例: export \"SELECT * FROM users\" out.csv csv")
            return True
        try:
            args = shlex.split(rest)
        except ValueError:
            args = rest.split()
        if len(args) < 2:
            print("用法: export \"SQL语句\" 文件路径 [格式]")
            print("  示例: export \"SELECT * FROM users\" out.csv csv")
            return True
        valid_formats = {"csv", "json", "sql"}
        fmt = "csv"
        if len(args) >= 3 and args[-1].lower() in valid_formats:
            fmt = args[-1].lower()
            fname = args[-2]
            sql_parts = args[:-2]
        else:
            fname = args[-1]
            sql_parts = args[:-1]
        sql = " ".join(sql_parts)
        if not sql:
            print("错误: SQL 语句为空，请用引号包裹包含空格的 SQL")
            return True
        cmd_export(db, sql, fname, fmt)
        return True
    if line.lower().startswith("backup "):
        cmd_backup(db, line[7:].strip())
        return True
    if line.lower().startswith("restore "):
        cmd_restore(db, line[8:].strip())
        return True
    if line.lower() == "vacuum":
        cmd_vacuum(db)
        return True
    if line.lower() == "integrity_check":
        cmd_integrity_check(db)
        return True
    if line.lower() == "stats":
        cmd_stats(db)
        return True
    if line.lower() == "history":
        cmd_history(db)
        return True
    if line.startswith("!"):
        try:
            n = int(line[1:])
            cmd_run_history(db, n)
        except ValueError:
            print("用法: !N (N为历史记录编号)")
        return True
    if line.startswith(".save "):
        try:
            args = shlex.split(line)
        except ValueError:
            args = line.split()
        if len(args) < 3:
            print("用法: .save NAME SQL")
            return True
        sql = " ".join(args[2:]).strip()
        if sql.startswith('"') and sql.endswith('"'):
            sql = sql[1:-1]
        if sql.startswith("'") and sql.endswith("'"):
            sql = sql[1:-1]
        cmd_save_favorite(db, args[1], sql)
        return True
    if line == ".favorites":
        cmd_list_favorites(db)
        return True
    if line.startswith(".run "):
        name = line[5:].strip()
        if name in db.favorites:
            cmd_run_favorite(db, name)
        elif os.path.exists(name):
            cmd_run(db, name)
        else:
            print(f"未找到收藏或文件: {name}")
        return True
    return None


def main():
    db = DBManager()
    if len(sys.argv) > 1:
        db.connect(sys.argv[1])
    print("=" * 60)
    print("  DB CLI - SQLite 终端管理工具")
    print("  输入 help 查看命令, exit 退出")
    print("=" * 60)
    while True:
        try:
            prompt = f"[{db.current}]> " if db.current else "> "
            line = input(prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            break
        line = line.strip()
        if not line:
            continue
        result = process_command(db, line)
        if result is False:
            break
        if result is True:
            continue
        if line.endswith(";"):
            execute_sql(db, line)
        else:
            full_sql = line
            while True:
                try:
                    more = input("  -> ")
                except (EOFError, KeyboardInterrupt):
                    print()
                    full_sql = None
                    break
                full_sql += "\n" + more
                if full_sql.strip().endswith(";"):
                    break
                if not more.strip():
                    break
            if full_sql:
                if full_sql.strip().endswith(";"):
                    execute_sql(db, full_sql)
                else:
                    print("未以分号结束, SQL 未执行")
    db.save_history()
    for info in db.connections.values():
        try:
            info["conn"].close()
        except Exception:
            pass
    print("再见!")


if __name__ == "__main__":
    main()

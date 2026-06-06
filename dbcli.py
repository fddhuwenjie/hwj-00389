#!/usr/bin/env python3
"""终端数据库管理客户端工具"""

import os
import sys
import csv
import json
import time
import shlex
import sqlite3
import os.path
import readline
from collections import OrderedDict

HISTORY_FILE = os.path.expanduser("~/.dbcli_history")
MAX_HISTORY = 500
FAVORITES_FILE = os.path.expanduser("~/.dbcli_favorites.json")


class DBManager:
    def __init__(self):
        self.connections = OrderedDict()
        self.current = None
        self.history = []
        self.favorites = {}
        self.load_history()
        self.load_favorites()

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


def execute_sql(db, sql, explain=False, timing=True):
    conn = db.get_current_conn()
    if not conn:
        return
    sql = sql.strip()
    if not sql:
        return
    if sql.endswith(";"):
        sql = sql[:-1]
    db.add_history(sql)
    try:
        start = time.time()
        if explain:
            sql = "EXPLAIN QUERY PLAN " + sql
        cursor = conn.execute(sql)
        rows = cursor.fetchall()
        elapsed = (time.time() - start) * 1000
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


def cmd_update(db, table_name):
    conn = db.get_current_conn()
    if not conn:
        return
    cols = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    if not cols:
        print(f"表 '{table_name}' 不存在")
        return
    print(f"更新表 '{table_name}' 数据")
    try:
        where = input("WHERE 条件 (例如: id=1, 留空查看前5行): ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n已取消")
        return
    if not where:
        rows = conn.execute(f"SELECT * FROM {table_name} LIMIT 5").fetchall()
        if not rows:
            print("表为空")
            return
        print_table(rows)
        try:
            where = input("请输入要更新行的 WHERE 条件: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n已取消")
            return
    if not where:
        print("未指定条件, 已取消")
        return
    existing = conn.execute(f"SELECT * FROM {table_name} WHERE {where}").fetchall()
    if not existing:
        print("未找到匹配的行")
        return
    print("当前匹配行:")
    print_table(existing)
    print("\n逐字段输入新值 (留空保持不变, NULL 设为空值):")
    set_clauses = []
    params = []
    for col in cols:
        current_val = existing[0][col["name"]] if existing else ""
        try:
            new_val = input(f"  {col['name']} ({col['type']}) [当前: {current_val}]: ")
        except (KeyboardInterrupt, EOFError):
            print("\n已取消")
            return
        if new_val == "":
            continue
        if new_val.upper() == "NULL":
            set_clauses.append(f"{col['name']} = ?")
            params.append(None)
        else:
            set_clauses.append(f"{col['name']} = ?")
            params.append(new_val)
    if not set_clauses:
        print("没有需要更新的字段")
        return
    sql = f"UPDATE {table_name} SET {', '.join(set_clauses)} WHERE {where}"
    try:
        cursor = conn.execute(sql, params)
        conn.commit()
        print(f"更新成功, 影响 {cursor.rowcount} 行")
    except Exception as e:
        print(f"更新失败: {e}")


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
    update TABLE         交互式更新
    export SQL FILE FMT  导出查询(CSV/JSON/SQL)
    .run FILE            批量执行SQL文件

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
    if line.lower().startswith("export "):
        try:
            args = shlex.split(line)
        except ValueError:
            args = line.split()
        if len(args) < 3:
            print("用法: export SQL FILE [FORMAT]  (FORMAT: csv/json/sql)")
            return True
        sql = args[1]
        fname = args[2]
        fmt = args[3] if len(args) > 3 else "csv"
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

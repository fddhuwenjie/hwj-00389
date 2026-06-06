#!/usr/bin/env python3
"""创建电商场景示例数据库: 用户/分类/商品/订单/评价"""

import sqlite3
import os
import random
from datetime import datetime, timedelta

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ecommerce.db")


def create_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) NOT NULL,
            parent_id INTEGER,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (parent_id) REFERENCES categories(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(50) NOT NULL UNIQUE,
            email VARCHAR(100) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            phone VARCHAR(20),
            address TEXT,
            balance DECIMAL(10,2) DEFAULT 0.00,
            level INTEGER DEFAULT 1,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(200) NOT NULL,
            description TEXT,
            category_id INTEGER,
            price DECIMAL(10,2) NOT NULL,
            stock INTEGER DEFAULT 0,
            status INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            order_no VARCHAR(32) NOT NULL UNIQUE,
            total_amount DECIMAL(10,2) NOT NULL,
            status INTEGER DEFAULT 0,
            shipping_address TEXT,
            remark TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            paid_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            unit_price DECIMAL(10,2) NOT NULL,
            subtotal DECIMAL(10,2) NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            order_item_id INTEGER,
            rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
            FOREIGN KEY (order_item_id) REFERENCES order_items(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);
        CREATE INDEX IF NOT EXISTS idx_products_status ON products(status);
        CREATE INDEX IF NOT EXISTS idx_products_price ON products(price);
        CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
        CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at);
        CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
        CREATE INDEX IF NOT EXISTS idx_order_items_product ON order_items(product_id);
        CREATE INDEX IF NOT EXISTS idx_reviews_product ON reviews(product_id);
        CREATE INDEX IF NOT EXISTS idx_reviews_user ON reviews(user_id);
        CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
        CREATE INDEX IF NOT EXISTS idx_categories_parent ON categories(parent_id);
    """)
    conn.commit()


def seed_data(conn):
    categories = [
        ("电子产品", None, "手机、电脑、数码产品"),
        ("服装鞋帽", None, "男女服饰、鞋靴"),
        ("图书音像", None, "书籍、音像制品"),
        ("食品生鲜", None, "食品、生鲜、零食"),
        ("智能手机", 1, "各类智能手机"),
        ("笔记本电脑", 1, "笔记本和平板"),
        ("男装", 2, "男士服装"),
        ("女装", 2, "女士服装"),
        ("小说", 3, "文学小说"),
        ("科技", 3, "科技图书"),
    ]
    for name, parent, desc in categories:
        conn.execute(
            "INSERT INTO categories (name, parent_id, description) VALUES (?, ?, ?)",
            (name, parent, desc),
        )

    users = []
    for i in range(1, 51):
        username = f"user{i:03d}"
        email = f"user{i:03d}@example.com"
        phone = f"138{i:08d}"
        balance = round(random.uniform(0, 10000), 2)
        level = random.randint(1, 5)
        users.append((username, email, "hash_" + username, phone,
                      f"北京市朝阳区街道{i}号", balance, level))
    conn.executemany(
        "INSERT INTO users (username, email, password_hash, phone, address, balance, level) VALUES (?, ?, ?, ?, ?, ?, ?)",
        users,
    )

    product_names = [
        "iPhone 15 Pro", "华为 Mate 60", "小米 14", "三星 Galaxy S24",
        "MacBook Pro 14", "联想 ThinkPad X1", "戴尔 XPS 15", "华硕 ROG",
        "男士休闲T恤", "男士牛仔裤", "男士西装", "男士运动鞋",
        "女士连衣裙", "女士高跟鞋", "女士羽绒服", "女士手提包",
        "三体全集", "百年孤独", "活着", "围城",
        "Python编程", "深度学习", "算法导论", "代码整洁之道",
        "有机苹果", "进口牛奶", "坚果礼盒", "巧克力礼盒",
    ]
    products = []
    for i, name in enumerate(product_names, 1):
        if i <= 4:
            cat_id = 5
        elif i <= 8:
            cat_id = 6
        elif i <= 12:
            cat_id = 7
        elif i <= 16:
            cat_id = 8
        elif i <= 20:
            cat_id = 9
        elif i <= 24:
            cat_id = 10
        else:
            cat_id = 4
        price = round(random.uniform(10, 20000), 2)
        stock = random.randint(0, 500)
        products.append((name, f"这是{name}的产品描述", cat_id, price, stock))
    conn.executemany(
        "INSERT INTO products (name, description, category_id, price, stock) VALUES (?, ?, ?, ?, ?)",
        products,
    )

    base = datetime(2024, 1, 1)
    def ts(dt):
        return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None

    orders = []
    order_items = []
    reviews = []
    for i in range(1, 201):
        user_id = random.randint(1, 50)
        order_no = f"ORD{datetime.now().strftime('%Y%m%d')}{i:06d}"
        total = round(random.uniform(50, 20000), 2)
        status = random.choice([0, 1, 2, 3, 4])
        created = base + timedelta(days=random.randint(0, 365))
        paid = created + timedelta(hours=random.randint(1, 48)) if status >= 1 else None
        orders.append((user_id, order_no, total, status,
                       f"收货地址{i}", "", ts(created), ts(paid)))

        num_items = random.randint(1, 5)
        for _ in range(num_items):
            pid = random.randint(1, len(product_names))
            qty = random.randint(1, 3)
            price_row = conn.execute("SELECT price FROM products WHERE id=?", (pid,)).fetchone()
            unit_price = price_row[0]
            subtotal = round(unit_price * qty, 2)
            order_items.append((i, pid, qty, unit_price, subtotal))

            if status == 4 and random.random() > 0.3:
                rating = random.randint(1, 5)
                content = random.choice([
                    "非常好，很满意！", "质量不错，物流也很快。",
                    "一般般吧，符合预期。", "不太好，有点失望。",
                    "非常棒，推荐购买！",
                ])
                reviews.append((user_id, pid, None, rating, content,
                                ts(created + timedelta(days=random.randint(1, 30)))))

    conn.executemany(
        "INSERT INTO orders (user_id, order_no, total_amount, status, shipping_address, remark, created_at, paid_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        orders,
    )
    conn.executemany(
        "INSERT INTO order_items (order_id, product_id, quantity, unit_price, subtotal) VALUES (?, ?, ?, ?, ?)",
        order_items,
    )
    conn.executemany(
        "INSERT INTO reviews (user_id, product_id, order_item_id, rating, content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        reviews,
    )
    conn.commit()


def main():
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    conn = sqlite3.connect(DB_FILE)
    print("创建示例数据库...")
    create_schema(conn)
    print("表结构已创建")
    seed_data(conn)
    print("示例数据已插入")
    conn.close()
    print(f"数据库已生成: {DB_FILE}")
    print()
    print("表统计:")
    conn = sqlite3.connect(DB_FILE)
    for t in ["categories", "users", "products", "orders", "order_items", "reviews"]:
        cnt = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {cnt} 行")
    conn.close()


if __name__ == "__main__":
    main()

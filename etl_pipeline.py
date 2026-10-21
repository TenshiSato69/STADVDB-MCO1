import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

# ==========================================
# 1. Database Connections (Secure via secrets.toml)
# ==========================================
# Extraction Connection (Local MySQL)
LOCAL_DB_URI = 'mysql+pymysql://root:eighty80*six6@localhost:3306/faker'
local_engine = create_engine(LOCAL_DB_URI)

# Loading Connection (TiDB Cloud via secrets.toml)
if "connections" in st.secrets and "mysql" in st.secrets["connections"]:
    conn = st.secrets["connections"]["mysql"]
    TIDB_HOST = conn["host"]
    TIDB_PORT = conn.get("port", 4000)
    TIDB_USER = conn["username"]
    TIDB_PASS = conn["password"]
else:
    raise RuntimeError("TiDB credentials missing from .streamlit/secrets.toml")

# Base engine to create the databases
TIDB_BASE_URI = f'mysql+pymysql://{TIDB_USER}:{TIDB_PASS}@{TIDB_HOST}:{TIDB_PORT}/test'
tidb_base_engine = create_engine(TIDB_BASE_URI, connect_args={"ssl": {"ssl_mode": "PREFERRED"}})

# Create both databases if they don't exist
with tidb_base_engine.begin() as db_conn:
    db_conn.execute(text("CREATE DATABASE IF NOT EXISTS faker;"))
    db_conn.execute(text("CREATE DATABASE IF NOT EXISTS faker_indexed;"))

# Engines for both data warehouses
TIDB_FAKER_URI = f'mysql+pymysql://{TIDB_USER}:{TIDB_PASS}@{TIDB_HOST}:{TIDB_PORT}/faker'
TIDB_FAKER_engine = create_engine(TIDB_FAKER_URI, connect_args={"ssl": {"ssl_mode": "PREFERRED"}})

TIDB_INDEXED_URI = f'mysql+pymysql://{TIDB_USER}:{TIDB_PASS}@{TIDB_HOST}:{TIDB_PORT}/faker_indexed'
TIDB_INDEXED_engine = create_engine(TIDB_INDEXED_URI, connect_args={"ssl": {"ssl_mode": "PREFERRED"}})


# ==========================================
# Phase 1: EXTRACT (From Local Source)
# ==========================================
print("Extracting data from local source...")

users = pd.read_sql("SELECT * FROM users LIMIT 250000", local_engine)
products = pd.read_sql("SELECT * FROM products LIMIT 250000", local_engine)
riders = pd.read_sql("SELECT * FROM riders LIMIT 250000", local_engine)
couriers = pd.read_sql("SELECT * FROM couriers LIMIT 250000", local_engine)
orders = pd.read_sql("SELECT * FROM orders LIMIT 500000", local_engine)
orderitems = pd.read_sql("SELECT * FROM orderitems LIMIT 500000", local_engine)


# ==========================================
# Phase 2: TRANSFORM
# ==========================================
print("Transforming data...")

# --- Transform: User Dimension ---
dim_users = users[['id', 'username', 'firstName', 'lastName', 'city', 'country', 'gender']].copy()
dim_users.rename(columns={'id': 'user_id', 'firstName': 'first_name', 'lastName': 'last_name'}, inplace=True)
dim_users['city'] = dim_users['city'].fillna('Unknown City')
dim_users['country'] = dim_users['country'].fillna('Unknown Country')
dim_users['gender'] = dim_users['gender'].str.strip().str.title()
dim_users['gender'] = dim_users['gender'].fillna('Not Specified')
gender_mapping = {'M': 'Male', 'F': 'Female'}
dim_users['gender'] = dim_users['gender'].replace(gender_mapping)

# --- Transform: Product Dimension ---
dim_products = products[['id', 'productCode', 'category', 'name', 'description']].copy()
dim_products.rename(columns={'id': 'product_id', 'productCode': 'product_code'}, inplace=True)
dim_products['description'] = dim_products['description'].fillna('No description available')
dim_products['category'] = dim_products['category'].str.strip().str.title()
category_mapping = {
    'Gadgets': 'Electronics',
    'Laptops': 'Electronics',
    'Toy': 'Toys',
    'Bag': 'Bags',
    'Make Up': 'Makeup',
    'Clothes': 'Apparel',
    "Men'S Apparel": 'Apparel'
}
dim_products['category'] = dim_products['category'].replace(category_mapping)

# --- Transform: Delivery Dimension ---
dim_delivery = pd.merge(
    riders, 
    couriers, 
    left_on='courierId', 
    right_on='id', 
    suffixes=('_rider', '_courier'),
    how='left'
)
dim_delivery = dim_delivery[['id_rider', 'firstName', 'lastName', 'vehicleType', 'courierId', 'name']].copy()
dim_delivery.rename(columns={
    'id_rider': 'rider_id',
    'firstName': 'rider_first_name',
    'lastName': 'rider_last_name',
    'vehicleType': 'vehicle_type',
    'courierId': 'courier_id',
    'name': 'courier_name'
}, inplace=True)
dim_delivery['courier_name'] = dim_delivery['courier_name'].fillna('Independent/Unknown')
dim_delivery['vehicle_type'] = dim_delivery['vehicle_type'].str.strip().str.title()
vehicle_mapping = {'Motorbike': 'Motorcycle', 'Bike': 'Bicycle', 'Trike': 'Tricycle'}
dim_delivery['vehicle_type'] = dim_delivery['vehicle_type'].replace(vehicle_mapping)

# --- Transform: Fact Order Items ---
fact_df = pd.merge(orderitems, orders, left_on='OrderId', right_on='id', how='inner')
fact_df = pd.merge(fact_df, products[['id', 'price']], left_on='ProductId', right_on='id', how='inner')

fact_df['createdAt_x'] = pd.to_datetime(fact_df['createdAt_x'], errors='coerce') 
fact_df['deliveryDate'] = pd.to_datetime(fact_df['deliveryDate'], errors='coerce') 

fact_df['unit_price'] = fact_df['price'].astype(float)
fact_df['quantity'] = fact_df['quantity'].fillna(1).astype(int)
fact_df['total_amount'] = fact_df['quantity'] * fact_df['unit_price']

fact_order_items = fact_df[[
    'OrderId', 'orderNumber', 'userId', 'ProductId', 'deliveryRiderId', 
    'createdAt_x', 'deliveryDate', 'quantity', 'unit_price', 'total_amount'
]].copy()

fact_order_items.rename(columns={
    'OrderId': 'order_id',
    'orderNumber': 'order_number',
    'userId': 'user_key',            
    'ProductId': 'product_key',      
    'deliveryRiderId': 'delivery_key',  
    'createdAt_x': 'order_date',
    'deliveryDate': 'delivery_date'
}, inplace=True)

fact_order_items.dropna(subset=['order_id', 'product_key', 'user_key', 'delivery_key'], inplace=True)
fact_order_items = fact_order_items[fact_order_items['user_key'].isin(dim_users['user_id'])]
fact_order_items = fact_order_items[fact_order_items['product_key'].isin(dim_products['product_id'])]
fact_order_items = fact_order_items[fact_order_items['delivery_key'].isin(dim_delivery['rider_id'])]


# ==========================================
# Phase 3: INITIALIZE SCHEMA & LOAD (DUAL DB)
# ==========================================
schema_ddl = """
SET FOREIGN_KEY_CHECKS = 0;

-- Wipe out old tables and conflicting foreign keys
DROP TABLE IF EXISTS fact_order_items;
DROP TABLE IF EXISTS dim_delivery;
DROP TABLE IF EXISTS dim_products;
DROP TABLE IF EXISTS dim_users;

-- Create fresh tables with proper Primary Keys
CREATE TABLE dim_users (
    user_id INT PRIMARY KEY,
    username VARCHAR(255),
    first_name VARCHAR(255),
    last_name VARCHAR(255),
    city VARCHAR(255),
    country VARCHAR(255),
    gender VARCHAR(50)
);

CREATE TABLE dim_products (
    product_id INT PRIMARY KEY,
    product_code VARCHAR(255),
    category VARCHAR(255),
    name VARCHAR(255),
    description TEXT
);

CREATE TABLE dim_delivery (
    rider_id INT PRIMARY KEY,
    rider_first_name VARCHAR(255),
    rider_last_name VARCHAR(255),
    vehicle_type VARCHAR(255),
    courier_id INT,
    courier_name VARCHAR(255)
);

CREATE TABLE fact_order_items (
    fact_id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT,
    order_number VARCHAR(255),
    user_key INT,
    product_key INT,
    delivery_key INT,
    order_date DATETIME,
    delivery_date DATETIME,
    quantity INT,
    unit_price FLOAT,
    total_amount FLOAT
);

SET FOREIGN_KEY_CHECKS = 1;
"""

engines = {
    "faker": TIDB_FAKER_engine, 
    "faker_indexed": TIDB_INDEXED_engine
}

for db_name, engine in engines.items():
    print(f"\nPreparing TiDB Schema for {db_name}...")
    with engine.begin() as conn:
        for statement in schema_ddl.split(';'):
            if statement.strip():
                conn.execute(text(statement + ';'))

    print(f"Loading transformed data into {db_name}...")
    # Increased chunksize to 10,000 for faster cloud uploading
    dim_users.to_sql('dim_users', engine, if_exists='append', index=False, chunksize=10000)
    dim_products.to_sql('dim_products', engine, if_exists='append', index=False, chunksize=10000)
    dim_delivery.to_sql('dim_delivery', engine, if_exists='append', index=False, chunksize=10000)
    fact_order_items.to_sql('fact_order_items', engine, if_exists='append', index=False, chunksize=10000)


# ==========================================
# Phase 4: INDEXING (faker_indexed ONLY)
# ==========================================
print("\nCreating secondary indexes in faker_indexed...")
indexes = [
    "CREATE INDEX idx_order_date ON fact_order_items(order_date);",
    "CREATE INDEX idx_product_category ON dim_products(category);",
    "CREATE INDEX idx_user_location ON dim_users(country, city);"
]

with TIDB_INDEXED_engine.begin() as conn:
    for idx_sql in indexes:
        try:
            conn.execute(text(idx_sql))
            print(f"Executed: {idx_sql}")
        except Exception as e:
            print(f"Index notice (may already exist): {e}")

print("\nDual Cloud Migration and ETL Pipeline completed successfully!")
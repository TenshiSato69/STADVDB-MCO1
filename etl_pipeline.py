import pandas as pd
from sqlalchemy import create_engine, text

# ==========================================
# 1. Database Connections (DUAL ENGINES)
# ==========================================
# Extraction Connection (Local MySQL)
LOCAL_DB_URI = 'mysql+pymysql://root:eighty80*six6@localhost:3306/faker'
local_engine = create_engine(LOCAL_DB_URI)

# Ensure 'faker' database exists on TiDB Cloud before connecting directly
TIDB_BASE_URI = 'mysql+pymysql://4D7HRxU1YMyqocC.root:V8vprts060560f46@gateway01.ap-northeast-1.prod.aws.tidbcloud.com:4000/test'
tidb_base_engine = create_engine(TIDB_BASE_URI, connect_args={"ssl": {"ssl_mode": "PREFERRED"}})

with tidb_base_engine.begin() as conn:
    conn.execute(text("CREATE DATABASE IF NOT EXISTS faker;"))

# Loading Connection (TiDB Cloud 'faker' Database)
TIDB_DB_URI = 'mysql+pymysql://4D7HRxU1YMyqocC.root:V8vprts060560f46@gateway01.ap-northeast-1.prod.aws.tidbcloud.com:4000/faker'
TIDB_engine = create_engine(TIDB_DB_URI, connect_args={"ssl": {"ssl_mode": "PREFERRED"}})


# ==========================================
# Phase 1: EXTRACT (From Local Source)
# ==========================================
print("Extracting data from local source...")

users = pd.read_sql("SELECT * FROM users LIMIT 50000", local_engine)
products = pd.read_sql("SELECT * FROM products LIMIT 50000", local_engine)
riders = pd.read_sql("SELECT * FROM riders LIMIT 50000", local_engine)
couriers = pd.read_sql("SELECT * FROM couriers LIMIT 50000", local_engine)
orders = pd.read_sql("SELECT * FROM orders LIMIT 100000", local_engine)
orderitems = pd.read_sql("SELECT * FROM orderitems LIMIT 100000", local_engine)


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
# Phase 3: LOAD (To TiDB Cloud)
# ==========================================
print("Preparing TiDB Data Warehouse...")

# Safely truncate existing tables if they exist
with TIDB_engine.begin() as conn:
    conn.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
    for table in ['fact_order_items', 'dim_delivery', 'dim_products', 'dim_users']:
        try:
            conn.execute(text(f"TRUNCATE TABLE {table};"))
        except Exception:
            pass  # Table does not exist yet; to_sql will create it automatically
    conn.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))

print("Loading transformed data into TiDB Cloud...")

dim_users.to_sql('dim_users', TIDB_engine, if_exists='append', index=False, chunksize=10000)
print("Loaded dim_users to TiDB Cloud.")

dim_products.to_sql('dim_products', TIDB_engine, if_exists='append', index=False, chunksize=10000)
print("Loaded dim_products to TiDB Cloud.")

dim_delivery.to_sql('dim_delivery', TIDB_engine, if_exists='append', index=False, chunksize=10000)
print("Loaded dim_delivery to TiDB Cloud.")

fact_order_items.to_sql('fact_order_items', TIDB_engine, if_exists='append', index=False, chunksize=10000)
print("Loaded fact_order_items to TiDB Cloud.")


# ==========================================
# Phase 4: INDEXING (Post-Load Optimization)
# ==========================================
print("Creating secondary indexes in TiDB Cloud...")

indexes = [
    "CREATE INDEX idx_order_date ON fact_order_items(order_date);",
    "CREATE INDEX idx_product_category ON dim_products(category);",
    "CREATE INDEX idx_user_location ON dim_users(country, city);"
]

with TIDB_engine.begin() as conn:
    for idx_sql in indexes:
        try:
            conn.execute(text(idx_sql))
            print(f"Executed: {idx_sql}")
        except Exception as e:
            print(f"Index notice (may already exist): {e}")

print("Indexing complete!")
print("Cloud Migration and ETL Pipeline completed successfully!")
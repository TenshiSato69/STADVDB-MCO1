import pandas as pd
from sqlalchemy import create_engine, text

# ==========================================
# 1. Database Connections (DUAL ENGINES)
# ==========================================
# Connection for EXTRACTION (Your Local Database)
LOCAL_DB_URI = 'mysql+pymysql://root:eighty80*six6@localhost:3306/faker'
local_engine = create_engine(LOCAL_DB_URI)

# Connection for LOADING (Your Aiven Cloud Database)
AIVEN_DB_URI = 'mysql+pymysql://avnadmin:AVNS_nYrrK36yeF2KYpse3G2@mysql-390fd756-virkato71-c11f.b.aivencloud.com:22255/faker'
aiven_engine = create_engine(AIVEN_DB_URI)


# ==========================================
# Phase 1: EXTRACT (From Local)
# ==========================================
print("Extracting data from local source...")

# Extracting using the local_engine
users = pd.read_sql("SELECT * FROM users LIMIT 50000", local_engine)
products = pd.read_sql("SELECT * FROM products LIMIT 50000", local_engine)
riders = pd.read_sql("SELECT * FROM riders LIMIT 50000", local_engine)
couriers = pd.read_sql("SELECT * FROM couriers LIMIT 50000", local_engine)
orders = pd.read_sql("SELECT * FROM orders LIMIT 100000", local_engine)
orderitems = pd.read_sql("SELECT * FROM orderitems LIMIT 100000", local_engine)

# ==========================================
# Phase 2: TRANSFORM (No changes)
# ==========================================
print("Transforming data...")

# --- Transform: User Dimension ---
dim_users = users[['id', 'username', 'firstName', 'lastName', 'city', 'country', 'gender']].copy()
dim_users.rename(columns={'id': 'user_id', 'firstName': 'first_name', 'lastName': 'last_name'}, inplace=True)
dim_users['city'] = dim_users['city'].fillna('Unknown City')
dim_users['country'] = dim_users['country'].fillna('Unknown Country')
dim_users['gender'] = dim_users['gender'].str.strip().str.title()
dim_users['gender'] = dim_users['gender'].fillna('Not Specified')
gender_mapping = {'M':'Male', 'F':'Female'}
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
# Phase 3: LOAD (To Aiven Cloud)
# ==========================================
print("Clearing existing data from the Aiven Data Warehouse...")

# Using aiven_engine.begin() to execute on the cloud
with aiven_engine.begin() as conn:
    conn.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
    conn.execute(text("TRUNCATE TABLE fact_order_items;"))
    conn.execute(text("TRUNCATE TABLE dim_delivery;"))
    conn.execute(text("TRUNCATE TABLE dim_products;"))
    conn.execute(text("TRUNCATE TABLE dim_users;"))
    conn.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))

print("Aiven Database cleared. Loading new data to cloud...")

# Loading into Aiven using aiven_engine
dim_users.to_sql('dim_users', aiven_engine, if_exists='append', index=False, chunksize=20000)
print("Loaded dim_users to Aiven.")

dim_products.to_sql('dim_products', aiven_engine, if_exists='append', index=False, chunksize=20000)
print("Loaded dim_products to Aiven.")

dim_delivery.to_sql('dim_delivery', aiven_engine, if_exists='append', index=False, chunksize=20000)
print("Loaded dim_delivery to Aiven.")

fact_order_items.to_sql('fact_order_items', aiven_engine, if_exists='append', index=False, chunksize=20000)
print("Loaded fact_order_items to Aiven.")

print("Cloud Migration and ETL Pipeline completed successfully!")
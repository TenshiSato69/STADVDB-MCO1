import streamlit as st
import pandas as pd
from sqlalchemy import create_engine

# --- Configuration & Connection ---
st.set_page_config(page_title="OLAP Data Warehouse Dashboard", layout="wide")

# No caching: Connection is re-initialized on every interaction
def init_connection():
    DB_URI = 'mysql+pymysql://avnadmin:AVNS_nYrrK36yeF2KYpse3G2@mysql-390fd756-virkato71-c11f.b.aivencloud.com:22255/faker'
    return create_engine(DB_URI)

engine = init_connection()

# No caching: Data is re-queried on every interaction
def get_data(query, params=None):
    return pd.read_sql(query, engine, params=params)

# --- Sidebar: Slice & Dice Filters ---
st.sidebar.header("OLAP Filters (Slice & Dice)")

years_query = "SELECT DISTINCT YEAR(order_date) as year FROM fact_order_items ORDER BY year;"
years_df = get_data(years_query)
selected_year = st.sidebar.selectbox("Select Year (Slice):", [None] + years_df['year'].tolist())

categories_query = "SELECT DISTINCT category FROM dim_products;"
categories_df = get_data(categories_query)
selected_categories = st.sidebar.multiselect("Select Categories (Dice):", categories_df['category'].tolist())

# --- Main Dashboard ---
st.title("Enterprise Sales & Delivery OLAP Dashboard (Unoptimized)")

# --- Section 1: Roll-up & Drill-down ---
st.header("1. Geographic & Product Hierarchy (Roll-up)")
st.write("Use the toggle below to adjust the granularity of the report.")

granularity = st.radio("Select Granularity Level:", ["Country (Roll-up)", "City (Drill-down)", "Product Category (Drill-down)"])

# Standard JOINs (Unoptimized execution plan)
rollup_query = """
    SELECT 
        COALESCE(u.country, 'All Countries') AS country,
        COALESCE(u.city, 'All Cities') AS city,
        COALESCE(p.category, 'All Categories') AS product_category,
        SUM(f.total_amount) AS total_revenue,
        SUM(f.quantity) AS total_items_sold
    FROM fact_order_items f
    JOIN dim_users u ON f.user_key = u.user_id
    JOIN dim_products p ON f.product_key = p.product_id
    GROUP BY u.country, u.city, p.category WITH ROLLUP;
"""
rollup_data = get_data(rollup_query)

if granularity == "Country (Roll-up)":
    filtered_rollup = rollup_data[(rollup_data['city'] == 'All Cities') & (rollup_data['country'] != 'All Countries')]
elif granularity == "City (Drill-down)":
    filtered_rollup = rollup_data[(rollup_data['product_category'] == 'All Categories') & (rollup_data['city'] != 'All Cities')]
else:
    filtered_rollup = rollup_data[(rollup_data['product_category'] != 'All Categories')]

st.dataframe(filtered_rollup, use_container_width=True)

# --- Section 2: Pivot Table ---
st.header("2. Revenue Pivot by User Gender")
st.write("Cross-tabulation comparing revenue by product category and gender.")

# Standard WHERE clauses (Unoptimized filtering)
pivot_query = """
    SELECT 
        p.category AS product_category,
        SUM(CASE WHEN LOWER(TRIM(u.gender)) IN ('male', 'm') THEN f.total_amount ELSE 0 END) AS revenue_male,
        SUM(CASE WHEN LOWER(TRIM(u.gender)) IN ('female', 'f') THEN f.total_amount ELSE 0 END) AS revenue_female,
        SUM(CASE WHEN LOWER(TRIM(u.gender)) NOT IN ('male', 'm', 'female', 'f') OR u.gender IS NULL THEN f.total_amount ELSE 0 END) AS revenue_unspecified,
        SUM(f.total_amount) AS total_revenue
    FROM fact_order_items f
    JOIN dim_users u ON f.user_key = u.user_id
    JOIN dim_products p ON f.product_key = p.product_id
    WHERE 1=1
"""
params = []

if selected_year:
    pivot_query += " AND YEAR(f.order_date) = %s"
    params.append(selected_year)

if selected_categories:
    format_strings = ','.join(['%s'] * len(selected_categories))
    pivot_query += f" AND p.category IN ({format_strings})"
    params.extend(selected_categories)

pivot_query += " GROUP BY p.category ORDER BY total_revenue DESC;"

pivot_data = get_data(pivot_query, params=tuple(params) if params else None)
st.dataframe(pivot_data, use_container_width=True)

if not pivot_data.empty:
    chart_data = pivot_data.set_index("product_category")[["revenue_male", "revenue_female"]]
    st.bar_chart(chart_data)
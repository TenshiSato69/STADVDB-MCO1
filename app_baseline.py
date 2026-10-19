import calendar
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine

# --- Page Config (Must be the FIRST Streamlit command) ---
st.set_page_config(page_title="OLAP Data Warehouse Dashboard", layout="wide")


# --- Configuration & Connection ---
def init_connection():
    DB_URI = "mysql+pymysql://avnadmin:AVNS_nYrrK36yeF2KYpse3G2@mysql-390fd756-virkato71-c11f.b.aivencloud.com:22255/faker"
    return create_engine(DB_URI)


engine = init_connection()


def get_data(query, params=None):
    return pd.read_sql(query, engine, params=params)


# ============ Individual Baseline Queries ============


def get_available_months():
    months_query = """
    SELECT DISTINCT EXTRACT(MONTH FROM order_date) as month
    FROM fact_order_items 
    WHERE order_date IS NOT NULL
    ORDER BY month;
    """
    return get_data(months_query)


def get_available_categories():
    categories_query = """
    SELECT DISTINCT category 
    FROM dim_products 
    ORDER BY category;
    """
    return get_data(categories_query)


def get_rollup_data():
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
    GROUP BY u.country, u.city, p.category 
    WITH ROLLUP;
    """
    return get_data(rollup_query)


def get_pivot_data(selected_month=None, selected_categories=None):
    pivot_query = """
    SELECT 
        p.category AS product_category,
        SUM(CASE WHEN LOWER(TRIM(u.gender)) 
            IN ('male', 'm') THEN f.total_amount ELSE 0 END) AS revenue_male,
        SUM(CASE WHEN LOWER(TRIM(u.gender)) 
            IN ('female', 'f') THEN f.total_amount ELSE 0 END) AS revenue_female,
        SUM(CASE WHEN LOWER(TRIM(u.gender)) 
            NOT IN ('male', 'm', 'female', 'f') OR u.gender IS NULL THEN f.total_amount ELSE 0 END) AS revenue_unspecified,
        SUM(f.total_amount) AS total_revenue
    FROM fact_order_items f
    JOIN dim_users u ON f.user_key = u.user_id
    JOIN dim_products p ON f.product_key = p.product_id
    WHERE 1=1
    """

    params = {}

    if selected_month is not None:
        pivot_query += " AND MONTH(f.order_date) = :selected_month"
        params["selected_month"] = selected_month

    if selected_categories:
        placeholders = []
        for index, category in enumerate(selected_categories):
            parameter_name = f"category_{index}"
            placeholders.append(f":{parameter_name}")
            params[parameter_name] = category

        pivot_query += f" AND p.category IN ({', '.join(placeholders)})"

    pivot_query += " GROUP BY p.category ORDER BY total_revenue DESC;"
    return get_data(pivot_query, params=params or None)


# ============== Streamlit UI ==============


def main():
    st.sidebar.header("OLAP Filters (Slice & Dice)")

    months_df = get_available_months()
    available_months = [None] + months_df["month"].dropna().astype(int).tolist()

    selected_month = st.sidebar.selectbox(
        "Select Month (Slice):",
        available_months,
        format_func=lambda month: (
            "All Months" if month is None else calendar.month_name[int(month)]
        ),
    )

    categories_df = get_available_categories()
    selected_categories = st.sidebar.multiselect(
        "Select Categories (Dice):",
        categories_df["category"].tolist(),
    )

    st.title("Enterprise Sales & Order OLAP Dashboard (Unoptimized)")

    # Section 1: Roll-up & Drill-down
    st.header("1. Geographic & Product Hierarchy (Roll-up)")
    st.write("Use the toggle below to adjust the granularity of the report.")

    granularity = st.radio(
        "Select Granularity Level:",
        [
            "Country (Roll-up)",
            "City (Drill-down)",
            "Product Category (Drill-down)",
        ],
    )

    rollup_data = get_rollup_data()

    if granularity == "Country (Roll-up)":
        filtered_rollup = rollup_data[
            (rollup_data["city"] == "All Cities")
            & (rollup_data["country"] != "All Countries")
        ]
    elif granularity == "City (Drill-down)":
        filtered_rollup = rollup_data[
            (rollup_data["product_category"] == "All Categories")
            & (rollup_data["city"] != "All Cities")
        ]
    else:
        filtered_rollup = rollup_data[
            rollup_data["product_category"] != "All Categories"
        ]

    st.dataframe(filtered_rollup, use_container_width=True)

    # Section 2: Pivot table
    st.header("2. Revenue Pivot by User Gender")
    st.write(
        "Cross-tabulation comparing revenue by product category and gender."
    )

    pivot_data = get_pivot_data(
        selected_month=selected_month,
        selected_categories=selected_categories,
    )
    st.dataframe(pivot_data, use_container_width=True)

    if not pivot_data.empty:
        chart_data = pivot_data.set_index("product_category")[
            ["revenue_male", "revenue_female"]
        ]
        st.bar_chart(chart_data)


if __name__ == "__main__":
    main()
"""
The tests use the query functions defined in app_optimized.py.
They do not insert, update, or delete database records.
"""

import os

import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app_optimized import (
    init_connection,
    get_available_months,
    get_available_categories,
    get_rollup_data,
    get_pivot_data,
)


# ============================================================
# TEST DATABASE CONNECTION WITH FALLBACK
# ============================================================

@pytest.fixture(scope="session")
def engine() -> Engine:
    """
    Create one database connection engine for the test session.

    Primary: Attempts connection via app_optimized.init_connection() (TiDB Cloud / secrets.toml).
    Fallback: Falls back to local MySQL environment credentials if primary connection fails.
    """
    database = os.getenv("TEST_SQL_DATABASE", "faker_indexed")
    db_engine = None

    # Primary Attempt: Try init_connection() (TiDB Cloud / Streamlit Secrets)
    try:
        db_engine = init_connection()
        with db_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as primary_exc:
        db_engine = None
        # Fallback Attempt: Connect using local environment credentials
        username = os.getenv("SQL_USERNAME")
        password = os.getenv("SQL_KEY")
        host = os.getenv("SQL_HOST", "localhost")
        port = os.getenv("SQL_PORT", "3306")

        if username and password:
            try:
                db_engine = create_engine(
                    f"mysql+pymysql://{username}:{password}@{host}:{port}/{database}"
                )
                with db_engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
            except Exception as fallback_exc:
                pytest.fail(
                    f"Primary connection (init_connection) failed: {primary_exc}\n"
                    f"Fallback local connection failed: {fallback_exc}"
                )
        else:
            pytest.fail(
                f"Primary connection (init_connection) failed: {primary_exc}\n"
                f"No fallback credentials (SQL_USERNAME / SQL_KEY) set in environment."
            )

    yield db_engine
    if db_engine:
        db_engine.dispose()


# ============================================================
# TEST 1: AVAILABLE MONTHS
# ============================================================

def test_available_months_are_valid_and_sorted(engine):
    """Months must be unique, valid, and in ascending order."""

    months = get_available_months(engine)

    assert "month" in months.columns
    assert months["month"].notna().all()

    values = months["month"].astype(int).tolist()

    assert all(1 <= month <= 12 for month in values)
    assert values == sorted(set(values))


def test_available_months_match_source_data(engine):
    """The query must return every distinct month in the source."""

    with engine.connect() as connection:
        expected = pd.read_sql_query(
            text("""
                SELECT DISTINCT EXTRACT(MONTH FROM order_date) AS month
                FROM fact_order_items
                WHERE order_date IS NOT NULL
                ORDER BY month
            """),
            connection,
        )

    actual = get_available_months(engine)

    pd.testing.assert_frame_equal(
        actual.reset_index(drop=True),
        expected.reset_index(drop=True),
        check_dtype=False,
    )


# ============================================================
# TEST 2: AVAILABLE PRODUCT CATEGORIES
# ============================================================

def test_categories_are_unique_and_sorted(engine):
    """Categories must be returned alphabetically without duplicates."""

    categories = get_available_categories(engine)

    assert "category" in categories.columns

    values = categories["category"].tolist()

    assert len(values) == len(set(values))
    assert values == sorted(
        values,
        key=lambda value: (
            value is not None,
            value.casefold() if value is not None else "",
        ),
    )


def test_categories_match_source_data(engine):
    """The returned categories must match the product dimension."""

    with engine.connect() as connection:
        expected = pd.read_sql_query(
            text("""
                SELECT DISTINCT category
                FROM dim_products
                ORDER BY category
            """),
            connection,
        )

    actual = get_available_categories(engine)

    assert set(actual["category"].tolist()) == set(
        expected["category"].tolist()
    )


# ============================================================
# TEST 3: ROLL-UP QUERY
# ============================================================

def test_rollup_has_expected_columns(engine):
    """The roll-up must expose all five dashboard columns."""

    result = get_rollup_data(engine)

    expected_columns = {
        "country",
        "city",
        "product_category",
        "total_revenue",
        "total_items_sold",
    }

    assert expected_columns.issubset(result.columns)


def test_rollup_contains_grand_total(engine):
    """The roll-up must include an overall total row."""

    result = get_rollup_data(engine)

    grand_total = result[
        (result["country"] == "All Countries")
        & (result["city"] == "All Cities")
        & (result["product_category"] == "All Categories")
    ]

    assert len(grand_total) == 1


def test_rollup_grand_total_matches_source(engine):
    """Revenue and quantity totals must match joined source rows."""

    with engine.connect() as connection:
        expected = connection.execute(
            text("""
                SELECT
                    SUM(f.total_amount) AS total_revenue,
                    SUM(f.quantity) AS total_items_sold
                FROM fact_order_items f
                JOIN dim_users u
                    ON f.user_key = u.user_id
                JOIN dim_products p
                    ON f.product_key = p.product_id
            """)
        ).mappings().one()

    result = get_rollup_data(engine)

    grand_total = result[
        (result["country"] == "All Countries")
        & (result["city"] == "All Cities")
        & (result["product_category"] == "All Categories")
    ].iloc[0]

    assert grand_total["total_revenue"] == pytest.approx(
        expected["total_revenue"]
    )
    assert grand_total["total_items_sold"] == pytest.approx(
        expected["total_items_sold"]
    )


# ============================================================
# TEST 4: PIVOT QUERY
# ============================================================

def test_pivot_has_expected_columns(engine):
    """The pivot must return revenue columns for all gender groups."""

    result = get_pivot_data(engine)

    expected_columns = {
        "product_category",
        "revenue_male",
        "revenue_female",
        "revenue_unspecified",
        "total_revenue",
    }

    assert expected_columns.issubset(result.columns)


def test_pivot_revenue_totals_are_consistent(engine):
    """
    For each category, the gender revenue groups must add up
    to the category's total revenue.
    """

    result = get_pivot_data(engine)

    assert (
        result["revenue_male"]
        + result["revenue_female"]
        + result["revenue_unspecified"]
    ).equals(result["total_revenue"]) or (
        (
            result["revenue_male"]
            + result["revenue_female"]
            + result["revenue_unspecified"]
        ).round(2).equals(result["total_revenue"].round(2))
    )


def test_pivot_is_sorted_by_revenue(engine):
    """Categories must be ordered from highest to lowest revenue."""

    result = get_pivot_data(engine)

    values = result["total_revenue"].tolist()

    assert values == sorted(values, reverse=True)


def test_month_filter_matches_independent_query(engine):
    """Filtering by month must match an independently computed result."""

    month = 1

    actual = get_pivot_data(engine, selected_month=month)

    with engine.connect() as connection:
        expected = pd.read_sql_query(
            text("""
                SELECT
                    p.category AS product_category,
                    SUM(
                        CASE
                            WHEN LOWER(TRIM(u.gender))
                                IN ('male', 'm')
                            THEN f.total_amount ELSE 0
                        END
                    ) AS revenue_male,
                    SUM(
                        CASE
                            WHEN LOWER(TRIM(u.gender))
                                IN ('female', 'f')
                            THEN f.total_amount ELSE 0
                        END
                    ) AS revenue_female,
                    SUM(
                        CASE
                            WHEN LOWER(TRIM(u.gender))
                                NOT IN ('male', 'm', 'female', 'f')
                                OR u.gender IS NULL
                            THEN f.total_amount ELSE 0
                        END
                    ) AS revenue_unspecified,
                    SUM(f.total_amount) AS total_revenue
                FROM fact_order_items f
                JOIN dim_users u
                    ON f.user_key = u.user_id
                JOIN dim_products p
                    ON f.product_key = p.product_id
                WHERE MONTH(f.order_date) = :month
                GROUP BY p.category
                ORDER BY total_revenue DESC
            """),
            connection,
            params={"month": month},
        )

    pd.testing.assert_frame_equal(
        actual.reset_index(drop=True),
        expected.reset_index(drop=True),
        check_dtype=False,
        check_exact=False,
        rtol=1e-6,
        atol=1e-6,
    )


def test_category_filter_returns_only_selected_categories(engine):
    """Category filtering must not return unselected categories."""

    available = get_available_categories(engine)

    if available.empty:
        pytest.skip("No product categories exist in the database.")

    category = available["category"].iloc[0]

    result = get_pivot_data(
        engine,
        selected_categories=[category],
    )

    assert result["product_category"].tolist() == [category]


def test_empty_category_filter_returns_all_categories(engine):
    """An empty selection must behave like no category filter."""

    without_filter = get_pivot_data(engine)
    with_empty_filter = get_pivot_data(engine, selected_categories=[])

    pd.testing.assert_frame_equal(
        with_empty_filter.reset_index(drop=True),
        without_filter.reset_index(drop=True),
        check_dtype=False,
        check_exact=False,
        rtol=1e-6,
        atol=1e-6,
    )
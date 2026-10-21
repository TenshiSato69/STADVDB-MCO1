import os
import sys
import subprocess
import streamlit as st

st.set_page_config(page_title="Functional Tests", page_icon="🧪", layout="wide")

st.title("🧪 Functional Test Suite")
st.markdown("Run automated `pytest` validation suites against the database layer.")

test_suite = st.selectbox(
    "Select Test Target:",
    options=[
        "All Suites (Baseline & Optimized)",
        "Baseline Suite (functional_test_baseline.py)",
        "Optimized Suite (functional_test_optimized.py)",
    ],
)

if test_suite == "Baseline Suite (functional_test_baseline.py)":
    target_files = ["functional_test_baseline.py"]
elif test_suite == "Optimized Suite (functional_test_optimized.py)":
    target_files = ["functional_test_optimized.py"]
else:
    target_files = ["functional_test_baseline.py", "functional_test_optimized.py"]

# Keep only files that actually exist in the root directory
existing_targets = [f for f in target_files if os.path.exists(f)]

if st.button("Run Selected Tests", type="primary"):
    if not existing_targets:
        st.warning(
            f"Specified test file(s) not found in root directory: {', '.join(target_files)}"
        )
    else:
        with st.spinner("Executing test suite against database connection..."):
            cmd = [
                sys.executable,
                "-m",
                "pytest",
                *existing_targets,
                "-v",
                "-p",
                "no:cacheprovider",
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
            )

        if result.returncode == 0:
            st.success("All executed tests passed successfully!")
        else:
            st.error("Some tests failed or encountered errors.")

        st.code(result.stdout + "\n" + result.stderr, language="bash")
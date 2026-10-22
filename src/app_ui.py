"""Shared Streamlit helpers: cached loaders and the disclaimer shown on every page."""

import streamlit as st

from src import app_data

REVIEW_STATEMENT = (
    "Case notes CASE-002 to CASE-024 and their QA assessments were drafted with an AI tool and reviewed by the "
    "project author for factual accuracy and consistency; CASE-001 was written by the author."
)
DISCLAIMER = (
    "**Synthetic data - portfolio project, not Barclays or professional casework.**  \n"
    "Transactions are from the synthetic SAML-D dataset and customer profiles are synthetic. "
    "The case notes and QA assessments were reviewed by the project author; this is a validation of the work, not an "
    "independent or blind QA review (see Methodology). "
    "Laundering labels and answer keys are never shown."
)
SHORT_NOTE = ("Synthetic portfolio data · case notes and QA assessments reviewed by the project author · "
              "not an independent QA review (see Methodology)")


def setup(title: str, full_disclaimer: bool = False) -> None:
    st.set_page_config(page_title=f"TM QA - {title}", layout="wide")
    st.title(title)
    if full_disclaimer:
        st.info(DISCLAIMER)
    else:
        st.caption(SHORT_NOTE)


@st.cache_data
def alerts():
    return app_data.read_processed("alerts.parquet")


@st.cache_data
def profiles():
    return app_data.read_processed("profiles.parquet")


@st.cache_data
def txns():
    return app_data.load_txns()


@st.cache_data
def effectiveness():
    return app_data.read_processed("scenario_effectiveness.csv")


@st.cache_data
def typology_coverage():
    return app_data.read_processed("typology_coverage.csv")


@st.cache_data
def cases():
    return app_data.load_cases()


@st.cache_data
def qa():
    return app_data.load_qa()


@st.cache_data
def worked_examples():
    return app_data.load_worked_examples()


@st.cache_data
def config(relpath: str):
    return app_data.load_yaml(relpath)

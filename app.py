"""Third Party Unified Gift Processor - Main Streamlit Application."""

import hashlib
import io
from datetime import date
from typing import Optional

import pandas as pd
import streamlit as st

from re_skyapi import RESkyAPI
from sources import SOURCE_REGISTRY
from utils.config import (
    get_secret,
    load_json_from_github,
    save_json_to_github,
    load_local_json,
    save_local_json,
)
from utils.cache import load_cache, save_cache, add_to_cache, clean_cache
from utils.excel_output import create_import_excel, create_grants_excel
from utils.date_utils import format_gl_post_date


st.set_page_config(
    page_title="Third Party Unified Gift Processor",
    page_icon="🎁",
    layout="wide"
)


def check_password() -> bool:
    """Check if user has entered the correct password."""
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False

    if st.session_state.password_correct:
        return True

    password = st.text_input("Enter password:", type="password")
    if st.button("Submit"):
        app_password = get_secret("app.password")
        if password == app_password:
            st.session_state.password_correct = True
            st.rerun()
        else:
            st.error("Incorrect password")

    return False


def init_session_state():
    """Initialize session state variables."""
    defaults = {
        "uploaded_files": {},
        "file_sources": {},
        "company_config": {},
        "entity_config": {},
        "cache_df": pd.DataFrame(),
        "part1_complete": False,
        "part1_result": None,
        "part1_grants": None,
        "benevity_rows": set(),
        "benevity_reason_rows": set(),
        "re_api": None,
        "re_tokens": None,
        "part2_query_results": None,
        "part2_cache_matches": {},
        "part2_result": None,
        "missing_companies": {},
        "use_github": True,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def load_configs():
    """Load company and entity configs from GitHub or local."""
    if st.session_state.use_github:
        try:
            config_repo = get_secret("github.config_repo")
            token = get_secret("github.access_token")

            st.session_state.company_config = load_json_from_github(
                config_repo, "config/company.json", token
            )
            st.session_state.entity_config = load_json_from_github(
                config_repo, "config/entity.json", token
            )
        except Exception as e:
            st.warning(f"Could not load configs from GitHub: {e}. Using local files.")
            st.session_state.use_github = False
            load_local_configs()
    else:
        load_local_configs()


def load_local_configs():
    """Load configs from local files."""
    try:
        st.session_state.company_config = load_local_json("config/company.json")
    except FileNotFoundError:
        st.session_state.company_config = {}

    try:
        st.session_state.entity_config = load_local_json("config/entity.json")
    except FileNotFoundError:
        st.session_state.entity_config = {}


def get_file_hash(content: bytes) -> str:
    """Get MD5 hash of file content."""
    return hashlib.md5(content).hexdigest()


def detect_source(raw_bytes: bytes) -> Optional[str]:
    """Auto-detect the source platform from file content."""
    try:
        df_raw = pd.read_csv(io.BytesIO(raw_bytes), nrows=5)
    except Exception:
        df_raw = pd.DataFrame()

    for source_name, source_class in SOURCE_REGISTRY.items():
        source = source_class()
        if source.detect(df_raw, raw_bytes):
            return source_name

    return None


def render_sidebar():
    """Render the sidebar with RE API auth and config status."""
    with st.sidebar:
        st.header("RE NXT Sky API")

        if st.session_state.re_api and st.session_state.re_api.is_authenticated():
            st.success("Authenticated")
            if st.button("Clear Authentication"):
                st.session_state.re_api = None
                st.session_state.re_tokens = None
                st.rerun()
        else:
            st.warning("Not authenticated")

            try:
                client_id = get_secret("re_api.client_id")
                client_secret = get_secret("re_api.client_secret")
                redirect_uri = get_secret("re_api.redirect_uri")
                subscription_key = get_secret("re_api.subscription_key")

                if st.session_state.re_api is None:
                    st.session_state.re_api = RESkyAPI(
                        client_id, client_secret, redirect_uri, subscription_key
                    )

                if st.button("Get Authorization URL"):
                    auth_url = st.session_state.re_api.get_authorization_url()
                    st.code(auth_url, language=None)
                    st.info("Visit this URL, authorize, then paste the code below.")

                auth_code = st.text_input("Authorization Code:")
                if st.button("Submit Code") and auth_code:
                    try:
                        st.session_state.re_api.exchange_code_for_tokens(auth_code)
                        st.session_state.re_tokens = st.session_state.re_api.get_tokens()
                        st.success("Authentication successful!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Authentication failed: {e}")

            except Exception as e:
                st.error(f"RE API not configured: {e}")

        st.divider()

        st.header("Configuration")
        source_label = "GitHub" if st.session_state.use_github else "Local"
        st.info(f"Config source: {source_label}")

        if st.button("Reload Configs"):
            load_configs()
            st.session_state.cache_df = load_cache(st.session_state.use_github)
            st.success("Configs reloaded")


def render_file_upload():
    """Render file upload section."""
    st.subheader("Step 1: Upload Files")

    uploaded = st.file_uploader(
        "Upload source files",
        type=["csv"],
        accept_multiple_files=True
    )

    if uploaded:
        for file in uploaded:
            content = file.read()
            file_hash = get_file_hash(content)

            if file_hash in st.session_state.uploaded_files:
                continue

            detected = detect_source(content)
            st.session_state.uploaded_files[file_hash] = {
                "name": file.name,
                "content": content,
                "detected_source": detected
            }
            st.session_state.file_sources[file_hash] = detected

    if st.session_state.uploaded_files:
        st.write("**Uploaded Files:**")

        for file_hash, file_info in list(st.session_state.uploaded_files.items()):
            col1, col2, col3 = st.columns([3, 2, 1])

            with col1:
                st.write(file_info["name"])

            with col2:
                source_options = list(SOURCE_REGISTRY.keys()) + ["None of the above"]
                current_source = st.session_state.file_sources.get(file_hash)
                default_idx = 0
                if current_source in source_options:
                    default_idx = source_options.index(current_source)
                elif current_source is None:
                    default_idx = len(source_options) - 1

                selected = st.selectbox(
                    "Source",
                    source_options,
                    index=default_idx,
                    key=f"source_{file_hash}",
                    label_visibility="collapsed"
                )
                st.session_state.file_sources[file_hash] = selected

            with col3:
                if st.button("Remove", key=f"remove_{file_hash}"):
                    del st.session_state.uploaded_files[file_hash]
                    del st.session_state.file_sources[file_hash]
                    st.rerun()

        none_selected = [
            f for f, s in st.session_state.file_sources.items()
            if s == "None of the above"
        ]
        if none_selected:
            st.warning(
                "One or more files have 'None of the above' selected. "
                "This file source has not been configured in this application. "
                "Please notify Amanda with the details of the source and send "
                "a copy of the raw, unmanipulated file from the platform."
            )


def render_missing_sources():
    """Render checklist of sources without uploaded files."""
    st.subheader("Step 2: Source Coverage")

    uploaded_sources = set(
        s for s in st.session_state.file_sources.values()
        if s in SOURCE_REGISTRY
    )
    all_sources = set(SOURCE_REGISTRY.keys())
    missing = all_sources - uploaded_sources

    if missing:
        st.info("The following sources have no file uploaded:")
        for source in sorted(missing):
            st.write(f"- {source}")
    else:
        st.success("All registered sources have files uploaded")


def check_missing_companies() -> dict[str, str]:
    """Check for companies not in company.json and return them."""
    missing = {}

    for file_hash, source_name in st.session_state.file_sources.items():
        if source_name not in SOURCE_REGISTRY:
            continue

        file_info = st.session_state.uploaded_files[file_hash]
        source_class = SOURCE_REGISTRY[source_name]
        source = source_class()
        df = source.read_file(file_info["content"])
        companies = source.get_companies(df)

        for company in companies:
            if company and company not in st.session_state.company_config:
                missing[company] = ""

    return missing


def render_company_validation():
    """Render company validation section."""
    st.subheader("Step 3: Company Validation")

    missing = check_missing_companies()

    if not missing:
        st.success("All companies are configured")
        return True

    st.warning(f"Found {len(missing)} companies not in configuration:")

    st.session_state.missing_companies = missing

    with st.form("company_form"):
        for company in missing:
            st.session_state.missing_companies[company] = st.text_input(
                f"RE Import ID for '{company}':",
                key=f"company_id_{company}"
            )

        if st.form_submit_button("Save Company Mappings"):
            all_filled = all(
                v.strip() for v in st.session_state.missing_companies.values()
            )

            if not all_filled:
                st.error("Please fill in all company Import IDs")
                return False

            for company, import_id in st.session_state.missing_companies.items():
                st.session_state.company_config[company] = import_id.strip()

            if st.session_state.use_github:
                try:
                    config_repo = get_secret("github.config_repo")
                    token = get_secret("github.access_token")
                    save_json_to_github(
                        config_repo,
                        "config/company.json",
                        st.session_state.company_config,
                        token,
                        f"Add company mappings: {', '.join(st.session_state.missing_companies.keys())}"
                    )
                    st.success("Company mappings saved to GitHub")
                except Exception as e:
                    st.error(f"Failed to save to GitHub: {e}")
                    return False
            else:
                save_local_json("config/company.json", st.session_state.company_config)
                st.success("Company mappings saved locally")

            st.session_state.missing_companies = {}
            st.rerun()

    return False


def process_part1():
    """Process Part 1 - Individuals."""
    all_unified = []
    all_grants = {}
    all_benevity_rows = set()
    all_benevity_reason_rows = set()
    row_offset = 0

    for file_hash, source_name in st.session_state.file_sources.items():
        if source_name not in SOURCE_REGISTRY:
            continue

        file_info = st.session_state.uploaded_files[file_hash]
        source_class = SOURCE_REGISTRY[source_name]
        source = source_class()

        df = source.read_file(file_info["content"])

        unified_df, grants_df, benevity_rows, benevity_reason_rows = source.transform_part1(
            df,
            st.session_state.company_config,
            st.session_state.entity_config
        )

        if not unified_df.empty:
            adjusted_benevity = {r + row_offset for r in benevity_rows}
            adjusted_reason = {r + row_offset for r in benevity_reason_rows}

            all_benevity_rows.update(adjusted_benevity)
            all_benevity_reason_rows.update(adjusted_reason)

            all_unified.append(unified_df)
            row_offset += len(unified_df)

        if not grants_df.empty:
            headers = list(df.columns)
            all_grants[source_name] = (headers, grants_df)

    if all_unified:
        combined = pd.concat(all_unified, ignore_index=True)
    else:
        combined = pd.DataFrame()

    return combined, all_grants, all_benevity_rows, all_benevity_reason_rows


def render_part1():
    """Render Part 1 tab content."""
    st.header("Part 1 - Individuals")

    render_file_upload()

    if not st.session_state.uploaded_files:
        return

    valid_files = [
        f for f, s in st.session_state.file_sources.items()
        if s in SOURCE_REGISTRY
    ]

    if not valid_files:
        st.warning("No valid source files to process")
        return

    render_missing_sources()

    companies_valid = render_company_validation()

    if not companies_valid:
        return

    st.subheader("Step 4: Process")

    if st.button("Process Part 1 - Individuals", type="primary"):
        with st.spinner("Processing..."):
            result, grants, benevity_rows, reason_rows = process_part1()

            st.session_state.part1_result = result
            st.session_state.part1_grants = grants
            st.session_state.benevity_rows = benevity_rows
            st.session_state.benevity_reason_rows = reason_rows

            st.success(f"Processed {len(result)} rows")

    if st.session_state.part1_result is not None and not st.session_state.part1_result.empty:
        st.subheader("Step 5: Preview & Download")

        st.dataframe(st.session_state.part1_result.head(50))

        if len(st.session_state.part1_result) > 50:
            st.info(f"Showing first 50 of {len(st.session_state.part1_result)} rows")

        col1, col2 = st.columns(2)

        with col1:
            excel_bytes = create_import_excel(
                st.session_state.part1_result,
                st.session_state.benevity_rows,
                st.session_state.benevity_reason_rows
            )

            today_str = date.today().strftime("%Y%m%d")
            filename = f"individual_gift_import_{today_str}.xlsx"

            if st.download_button(
                "Download Import File",
                data=excel_bytes,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ):
                non_anonymous = st.session_state.part1_result[
                    st.session_state.part1_result["RE Constituent ID"] != "22-2934"
                ]

                for _, row in non_anonymous.iterrows():
                    company = ""
                    for file_hash, source_name in st.session_state.file_sources.items():
                        if source_name in SOURCE_REGISTRY:
                            company = row.get("Soft Credit Company ID", "")
                            break

                    st.session_state.cache_df = add_to_cache(
                        st.session_state.cache_df,
                        pd.DataFrame([row]),
                        company,
                        ""
                    )

                save_cache(st.session_state.cache_df, st.session_state.use_github)

        with col2:
            if st.session_state.part1_grants:
                grants_bytes = create_grants_excel(st.session_state.part1_grants)
                grants_filename = f"grants_manual_add_{today_str}.xlsx"

                st.download_button(
                    "Download Grants File",
                    data=grants_bytes,
                    file_name=grants_filename,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

        st.divider()

        if st.checkbox("I have committed the Part 1 import in Raiser's Edge"):
            st.session_state.part1_complete = True
            st.success("Part 1 marked as complete. You can now proceed to Part 2.")


def render_part2():
    """Render Part 2 tab content."""
    st.header("Part 2 - Companies")

    if not st.session_state.part1_complete:
        st.warning(
            "Please complete Part 1 and confirm you have committed the import "
            "in Raiser's Edge before proceeding."
        )
        return

    if not st.session_state.re_api or not st.session_state.re_api.is_authenticated():
        st.error("Please authenticate with RE NXT Sky API in the sidebar")
        return

    st.subheader("Step 1: Retrieve RE Data")

    if st.button("Execute RE Query"):
        with st.spinner("Retrieving data from Raiser's Edge..."):
            try:
                query_id = get_secret("re_api.query_id")

                def status_callback(status):
                    st.write(status)

                results = st.session_state.re_api.execute_query(
                    query_id,
                    poll_interval=10,
                    status_callback=status_callback
                )

                st.session_state.part2_query_results = results
                st.success(f"Retrieved {len(results)} rows")

            except Exception as e:
                st.error(f"Query failed: {e}")

    if st.session_state.part2_query_results is None:
        return

    st.subheader("Step 2: Cache Matching")

    unmatched_cache = st.session_state.cache_df[
        (st.session_state.cache_df["Constituent ID"].isna()) |
        (st.session_state.cache_df["Constituent ID"] == "")
    ]

    if unmatched_cache.empty:
        st.info("No unmatched donors in cache")
    else:
        st.write(f"Found {len(unmatched_cache)} unmatched donors in cache")

        query_results = st.session_state.part2_query_results
        company_ids = set(st.session_state.company_config.values())
        entity_ids = set(st.session_state.entity_config.values())

        exact_matches = []
        fuzzy_candidates = []
        unmatched = []

        for idx, cache_row in unmatched_cache.iterrows():
            cache_first = str(cache_row.get("First Name", "")).lower()
            cache_last = str(cache_row.get("Last Name", "")).lower()
            cache_company = str(cache_row.get("Company", ""))
            cache_entity = str(cache_row.get("Entity", ""))
            cache_date = str(cache_row.get("Gift Date", ""))
            cache_amount = cache_row.get("Gift Amount", 0)

            found_exact = False
            found_fuzzy = False

            for result in query_results:
                result_first = str(result.get("First Name", "")).lower()
                result_last = str(result.get("Last Name", "")).lower()
                result_date = str(result.get("Gift Date", ""))
                result_amount = result.get("Gift Amount", 0)
                sc_id = result.get("SC Constituent ID", "")

                is_company_sc = sc_id in company_ids
                is_entity_sc = sc_id in entity_ids

                if not is_company_sc and not is_entity_sc:
                    continue

                if (cache_first == result_first and
                    cache_last == result_last and
                    cache_date == result_date and
                    cache_amount == result_amount):

                    exact_matches.append({
                        "cache_idx": idx,
                        "result": result,
                        "constituent_id": result.get("Constituent ID", ""),
                        "branch": result.get("Branch", "Main")
                    })
                    found_exact = True
                    break

                if (cache_last == result_last and
                    cache_date == result_date and
                    cache_amount == result_amount):

                    fuzzy_candidates.append({
                        "cache_idx": idx,
                        "cache_row": cache_row,
                        "result": result
                    })
                    found_fuzzy = True

            if not found_exact and not found_fuzzy:
                unmatched.append({"cache_idx": idx, "cache_row": cache_row})

        if exact_matches:
            st.write(f"**Round 1 - Exact Matches:** {len(exact_matches)}")
            for match in exact_matches:
                st.session_state.cache_df.loc[match["cache_idx"], "Constituent ID"] = match["constituent_id"]
                st.session_state.cache_df.loc[match["cache_idx"], "Branch"] = match["branch"]
            st.success(f"Auto-matched {len(exact_matches)} donors")

        if fuzzy_candidates:
            st.write(f"**Round 2 - Fuzzy Matches:** {len(fuzzy_candidates)}")

            for i, candidate in enumerate(fuzzy_candidates):
                with st.expander(f"Review match {i + 1}"):
                    col1, col2 = st.columns(2)

                    with col1:
                        st.write("**Source Platform Data:**")
                        st.write(f"Name: {candidate['cache_row'].get('First Name', '')} {candidate['cache_row'].get('Last Name', '')}")
                        st.write(f"Company: {candidate['cache_row'].get('Company', '')}")
                        st.write(f"Gift Date: {candidate['cache_row'].get('Gift Date', '')}")
                        st.write(f"Amount: {candidate['cache_row'].get('Gift Amount', '')}")

                    with col2:
                        st.write("**Raiser's Edge Data:**")
                        st.write(f"Name: {candidate['result'].get('First Name', '')} {candidate['result'].get('Last Name', '')}")
                        st.write(f"Constituent ID: {candidate['result'].get('Constituent ID', '')}")

                    col3, col4 = st.columns(2)

                    with col3:
                        if st.button("Yes, match", key=f"match_{i}"):
                            st.session_state.cache_df.loc[candidate["cache_idx"], "Constituent ID"] = candidate["result"].get("Constituent ID", "")
                            st.session_state.cache_df.loc[candidate["cache_idx"], "Branch"] = candidate["result"].get("Branch", "Main")
                            st.rerun()

                    with col4:
                        manual_id = st.text_input("Manual Constituent ID:", key=f"manual_id_{i}")
                        manual_branch = st.selectbox("Branch:", ["Main", "WSlope", "Wyoming"], key=f"manual_branch_{i}")
                        if st.button("No, use manual", key=f"no_match_{i}") and manual_id:
                            st.session_state.cache_df.loc[candidate["cache_idx"], "Constituent ID"] = manual_id
                            st.session_state.cache_df.loc[candidate["cache_idx"], "Branch"] = manual_branch
                            st.rerun()

        if unmatched:
            st.write(f"**Round 3 - Unmatched:** {len(unmatched)}")

            for i, item in enumerate(unmatched):
                with st.expander(f"Unmatched donor {i + 1}"):
                    st.write(f"Name: {item['cache_row'].get('First Name', '')} {item['cache_row'].get('Last Name', '')}")
                    st.write(f"Company: {item['cache_row'].get('Company', '')}")
                    st.write(f"Gift Date: {item['cache_row'].get('Gift Date', '')}")
                    st.write(f"Amount: {item['cache_row'].get('Gift Amount', '')}")

                    manual_id = st.text_input("Constituent ID:", key=f"unmatched_id_{i}")
                    manual_branch = st.selectbox("Branch:", ["Main", "WSlope", "Wyoming"], key=f"unmatched_branch_{i}")

                    if st.button("Save", key=f"save_unmatched_{i}") and manual_id:
                        st.session_state.cache_df.loc[item["cache_idx"], "Constituent ID"] = manual_id
                        st.session_state.cache_df.loc[item["cache_idx"], "Branch"] = manual_branch
                        st.rerun()

    st.subheader("Step 3: Process Companies")

    if st.button("Process Part 2 - Companies", type="primary"):
        with st.spinner("Processing..."):
            all_company_rows = []

            for file_hash, source_name in st.session_state.file_sources.items():
                if source_name not in SOURCE_REGISTRY:
                    continue

                file_info = st.session_state.uploaded_files[file_hash]
                source_class = SOURCE_REGISTRY[source_name]
                source = source_class()

                df = source.read_file(file_info["content"])
                company_df = source.transform_part2(
                    df,
                    st.session_state.company_config,
                    st.session_state.entity_config,
                    st.session_state.cache_df
                )

                if not company_df.empty:
                    all_company_rows.append(company_df)

            if all_company_rows:
                combined = pd.concat(all_company_rows, ignore_index=True)
            else:
                combined = pd.DataFrame()

            st.session_state.part2_result = combined
            st.success(f"Processed {len(combined)} company gift rows")

    if st.session_state.part2_result is not None and not st.session_state.part2_result.empty:
        st.subheader("Step 4: Preview & Download")

        st.dataframe(st.session_state.part2_result.head(50))

        today_str = date.today().strftime("%Y%m%d")
        filename = f"company_gift_import_{today_str}.xlsx"

        excel_bytes = create_import_excel(st.session_state.part2_result)

        if st.download_button(
            "Download Company Import File",
            data=excel_bytes,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ):
            st.session_state.cache_df = clean_cache(st.session_state.cache_df)
            save_cache(st.session_state.cache_df, st.session_state.use_github)
            st.success("Cache cleaned and saved")


def main():
    """Main application entry point."""
    st.title("Third Party Unified Gift Processor")
    st.caption("Food Bank of the Rockies")

    if not check_password():
        return

    init_session_state()

    if not st.session_state.company_config:
        load_configs()
        st.session_state.cache_df = load_cache(st.session_state.use_github)

    if st.session_state.re_tokens and st.session_state.re_api:
        st.session_state.re_api.set_tokens(**st.session_state.re_tokens)

    render_sidebar()

    tab1, tab2 = st.tabs(["Part 1 - Individuals", "Part 2 - Companies"])

    with tab1:
        render_part1()

    with tab2:
        render_part2()

    st.divider()
    st.caption(f"GL Post Date: {format_gl_post_date()}")


if __name__ == "__main__":
    main()

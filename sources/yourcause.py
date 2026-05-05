"""YourCause source transformer."""

import io
import pandas as pd

from .base import BaseSource
from utils.date_utils import format_date, format_gl_post_date
from utils.fiscal import get_campaign, get_appeal


class YourCauseSource(BaseSource):
    """Transformer for YourCause donation reports."""

    name = "YourCause"

    def detect(self, df_raw: pd.DataFrame, raw_bytes: bytes) -> bool:
        """Detect YourCause by first three column names."""
        try:
            cols = list(df_raw.columns)[:3]
            expected = ["Donation Date", "Company", "Transaction Id"]
            return cols == expected
        except Exception:
            return False

    def read_file(self, raw_bytes: bytes) -> pd.DataFrame:
        """Read YourCause file with headers on row 0."""
        return pd.read_csv(io.BytesIO(raw_bytes))

    def get_companies(self, df: pd.DataFrame) -> set:
        """Get unique company names from Company column."""
        if "Company" in df.columns:
            return set(df["Company"].dropna().unique())
        return set()

    def transform_part1(
        self,
        df: pd.DataFrame,
        company_config: dict,
        entity_config: dict
    ) -> tuple[pd.DataFrame, pd.DataFrame, set, set]:
        """Transform YourCause data for Part 1 import (Individual donations)."""
        gl_post_date = format_gl_post_date()
        unified_rows = []

        individual_df = df[df["Donor Type"] == "Individual"] if "Donor Type" in df.columns else df

        for _, row in individual_df.iterrows():
            company = str(row.get("Company", "")) if pd.notna(row.get("Company")) else ""
            gift_date = format_date(row.get("Donation Date"))

            full_name = str(row.get("Donor Full Name", "")) if pd.notna(row.get("Donor Full Name")) else ""
            is_anonymous = full_name.lower() == "anonymous"

            first_name = str(row.get("Donor First Name", "")) if pd.notna(row.get("Donor First Name")) else ""
            last_name = str(row.get("Donor Last Name", "")) if pd.notna(row.get("Donor Last Name")) else ""

            if is_anonymous:
                first_name = ""
                last_name = ""

            dedication = str(row.get("Dedication", "")) if pd.notna(row.get("Dedication")) and str(row.get("Dedication")).strip() else ""
            designation = str(row.get("Designation", "")) if pd.notna(row.get("Designation")) else ""

            gift_ref_parts = []
            if dedication:
                gift_ref_parts.append(dedication)

            branch = self._check_branch(designation)
            if branch == "WSlope":
                gift_ref_parts.append("designated WSlope")

            gift_reference = self._build_gift_reference(*gift_ref_parts, company=company)

            address1 = str(row.get("Donor Address", "")) if pd.notna(row.get("Donor Address")) else ""
            address2 = str(row.get("Donor Address 2", "")) if pd.notna(row.get("Donor Address 2")) else ""
            address = f"{address1} {address2}".strip()

            country = str(row.get("Donor Country", "")) if pd.notna(row.get("Donor Country")) else ""
            if not country:
                country = "United States"

            output_row = {
                "RE Constituent ID": "22-2934" if is_anonymous else "",
                "Gift Date": gift_date,
                "GL Post Date": gl_post_date,
                "Gift Amount": row.get("Transaction Amount", 0),
                "Campaign": get_campaign(gl_post_date) if gl_post_date else "",
                "Appeal": get_appeal(gl_post_date) if gl_post_date else "",
                "Donation Type": "",
                "Branch": branch,
                "Gift Reference": gift_reference,
                "Soft Credit Company ID": company_config.get(company, ""),
                "Soft Credit Entity ID": "",
                "First Name": "" if is_anonymous else first_name.title(),
                "Middle Name": "",
                "Last Name": "" if is_anonymous else last_name.title(),
                "Address": "" if is_anonymous else address,
                "City": "" if is_anonymous else (str(row.get("Donor City", "")) if pd.notna(row.get("Donor City")) else ""),
                "State": "" if is_anonymous else (str(row.get("Donor State", "")) if pd.notna(row.get("Donor State")) else ""),
                "ZIP": "" if is_anonymous else (str(row.get("Donor Postal Code", "")) if pd.notna(row.get("Donor Postal Code")) else ""),
                "Country": "" if is_anonymous else country,
                "Primary Phone": "",
                "Email": "" if is_anonymous else (str(row.get("Donor Email", "")) if pd.notna(row.get("Donor Email")) else ""),
            }

            unified_rows.append(output_row)

        unified_df = pd.DataFrame(unified_rows)
        grants_df = pd.DataFrame()

        return unified_df, grants_df, set(), set()

    def transform_part2(
        self,
        df: pd.DataFrame,
        company_config: dict,
        entity_config: dict,
        cache_df: pd.DataFrame
    ) -> pd.DataFrame:
        """Transform YourCause data for Part 2 (Company donations)."""
        gl_post_date = format_gl_post_date()
        company_rows = []

        company_df = df[df["Donor Type"] == "Company"] if "Donor Type" in df.columns else pd.DataFrame()

        for _, row in company_df.iterrows():
            company = str(row.get("Company", "")) if pd.notna(row.get("Company")) else ""
            gift_date = format_date(row.get("Donation Date"))
            amount = row.get("Transaction Amount", 0)

            match_first = str(row.get("Match Donor First Name", "")).lower() if pd.notna(row.get("Match Donor First Name")) else ""
            match_last = str(row.get("Match Donor Last Name", "")).lower() if pd.notna(row.get("Match Donor Last Name")) else ""
            match_email = str(row.get("Match Donor Email", "")).lower() if pd.notna(row.get("Match Donor Email")) else ""

            soft_credit_id = ""
            branch = "Main"

            if not cache_df.empty:
                for cache_idx in range(len(cache_df) - 1, -1, -1):
                    cache_row = cache_df.iloc[cache_idx]

                    cache_first = str(cache_row.get("First Name", "")).lower()
                    cache_last = str(cache_row.get("Last Name", "")).lower()
                    cache_company = str(cache_row.get("Company", ""))
                    cache_email = str(cache_row.get("Email", "")).lower()

                    if (cache_first == match_first and
                        cache_last == match_last and
                        cache_company == company and
                        cache_email == match_email):

                        soft_credit_id = str(cache_row.get("Constituent ID", ""))
                        branch = str(cache_row.get("Branch", "Main")) or "Main"
                        break

            display_first = str(row.get("Match Donor First Name", "")).title() if pd.notna(row.get("Match Donor First Name")) else ""
            display_last = str(row.get("Match Donor Last Name", "")).title() if pd.notna(row.get("Match Donor Last Name")) else ""

            gift_reference = self._build_gift_reference(company=company)
            if display_first and display_last:
                gift_reference = f"matching gift for {display_first} {display_last} ; {gift_reference}"

            output_row = {
                "RE Constituent ID": company_config.get(company, ""),
                "Gift Date": gift_date,
                "GL Post Date": gl_post_date,
                "Gift Amount": amount,
                "Campaign": get_campaign(gl_post_date) if gl_post_date else "",
                "Appeal": get_appeal(gl_post_date) if gl_post_date else "",
                "Branch": branch,
                "Gift Reference": gift_reference,
                "Soft Credit Individual ID": soft_credit_id,
                "Soft Credit Entity ID": "",
            }

            company_rows.append(output_row)

        return pd.DataFrame(company_rows)

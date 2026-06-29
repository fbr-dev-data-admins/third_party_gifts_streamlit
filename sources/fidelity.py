"""Fidelity Marketplace Giving source transformer."""

import io
from datetime import date
import pandas as pd

from .base import BaseSource
from utils.date_utils import format_date, format_gl_post_date
from utils.fiscal import get_campaign, get_appeal
from utils.name_parsing import parse_full_name


class FidelitySource(BaseSource):
    """Transformer for Fidelity Marketplace Giving donation reports."""

    name = "Fidelity Marketplace Giving"
    entity_constituent_id = "23-14720"

    def detect(self, df_raw: pd.DataFrame, raw_bytes: bytes) -> bool:
        """Detect Fidelity by header starting with specific columns."""
        try:
            cols = list(df_raw.columns)[:6]
            expected = ["id", "Type", "Source", "Amount", "Fee", "Net"]
            return cols == expected
        except Exception:
            return False

    def read_file(self, raw_bytes: bytes) -> pd.DataFrame:
        """Read Fidelity file with headers on row 0."""
        return pd.read_csv(io.BytesIO(raw_bytes))

    def get_companies(self, df: pd.DataFrame) -> set:
        """Get unique company names from Acknowledgment Name for matching gifts."""
        companies = set()

        if "Donation Type (metadata)" in df.columns and "Acknowledgment Name (metadata)" in df.columns:
            matching_df = df[df["Donation Type (metadata)"] == "Matching Gift"]
            companies.update(matching_df["Acknowledgment Name (metadata)"].dropna().unique())

        return companies

    def transform_part1(
        self,
        df: pd.DataFrame,
        company_config: dict,
        pass_through_agents: dict = None
    ) -> tuple[pd.DataFrame, pd.DataFrame, set, set]:
        """Transform Fidelity data for Part 1 import (Individual donations)."""
        gl_post_date = format_gl_post_date()
        unified_rows = []
        grants_rows = []

        donation_type_col = "Donation Type (metadata)"

        if donation_type_col in df.columns:
            individual_df = df[df[donation_type_col] == "Donation"]
            grants_df_source = df[df[donation_type_col] == "Corporate Grant"]
        else:
            individual_df = df
            grants_df_source = pd.DataFrame()

        for _, row in grants_df_source.iterrows():
            grants_rows.append(row)

        for _, row in individual_df.iterrows():
            amount = row.get("Amount", 0)
            try:
                amount = float(amount) if pd.notna(amount) else 0
            except (ValueError, TypeError):
                amount = 0

            if amount <= 0:
                continue

            gift_date = format_date(row.get("Created (UTC)"))

            ack_name = str(row.get("Acknowledgment Name (metadata)", "")) if pd.notna(row.get("Acknowledgment Name (metadata)")) else ""
            first_name, middle_name, last_name = parse_full_name(ack_name)

            email = str(row.get("Acknowledgment Email (metadata)", "")) if pd.notna(row.get("Acknowledgment Email (metadata)")) else ""

            gift_reference = self._build_gift_reference(company="")
            if not gift_reference:
                gift_reference = "Fidelity Marketplace Giving workplace giving"

            output_row = {
                "RE Constituent ID": "",
                "Gift Date": gift_date,
                "GL Post Date": gl_post_date,
                "Gift Amount": amount,
                "Campaign": get_campaign(gl_post_date) if gl_post_date else "",
                "Appeal": get_appeal(gl_post_date) if gl_post_date else "",
                "Donation Type": "",
                "Branch": "Main",
                "Gift Reference": gift_reference,
                "Soft Credit Company ID": "",
                "Soft Credit Entity ID": self.entity_constituent_id,
                "Soft Credit Entity ID 2": "",
                "First Name": first_name,
                "Middle Name": middle_name,
                "Last Name": last_name,
                "Address": "",
                "City": "",
                "State": "",
                "ZIP": "",
                "Country": "",
                "Primary Phone": "",
                "Email": email,
            }

            unified_rows.append(output_row)

        unified_df = pd.DataFrame(unified_rows)
        grants_df = pd.DataFrame(grants_rows)

        return unified_df, grants_df, set(), set()

    def transform_part2(
        self,
        df: pd.DataFrame,
        company_config: dict,
        cache_df: pd.DataFrame,
        pass_through_agents: dict = None
    ) -> tuple[pd.DataFrame, set]:
        """Transform Fidelity data for Part 2 (Company/Matching Gift donations)."""
        gl_post_date = format_gl_post_date()
        today_str = date.today().strftime("%m/%d/%Y")
        company_rows = []
        stale_cache_rows = set()

        donation_type_col = "Donation Type (metadata)"

        if donation_type_col in df.columns:
            matching_df = df[df[donation_type_col] == "Matching Gift"]
        else:
            matching_df = pd.DataFrame()

        for _, row in matching_df.iterrows():
            amount = row.get("Amount", 0)
            try:
                amount = float(amount) if pd.notna(amount) else 0
            except (ValueError, TypeError):
                amount = 0

            if amount <= 0:
                continue

            gift_date = format_date(row.get("Created (UTC)"))

            company_name = str(row.get("Acknowledgment Name (metadata)", "")) if pd.notna(row.get("Acknowledgment Name (metadata)")) else ""

            original_donations = str(row.get("Original Donations (metadata)", "")) if pd.notna(row.get("Original Donations (metadata)")) else ""
            first, middle, last = parse_full_name(original_donations)

            is_anonymous = not first and not last
            soft_credit_id = "22-2934" if is_anonymous else ""
            branch = "Main"

            if not is_anonymous and not cache_df.empty:
                for cache_idx in range(len(cache_df) - 1, -1, -1):
                    cache_row = cache_df.iloc[cache_idx]

                    cache_first = str(cache_row.get("First Name", "")).lower()
                    cache_last = str(cache_row.get("Last Name", "")).lower()

                    if cache_first == first.lower() and cache_last == last.lower():
                        soft_credit_id = str(cache_row.get("Constituent ID", ""))
                        branch = str(cache_row.get("Branch", "Main")) or "Main"
                        cache_added = str(cache_row.get("Date Added to Cache", ""))
                        if cache_added != today_str:
                            stale_cache_rows.add(len(company_rows))
                        break

            if is_anonymous:
                gift_reference = "matching gift for Anonymous"
            elif first and last:
                gift_reference = f"matching gift for {first} {last}"
            elif not soft_credit_id and (first or last):
                name = " ".join(p for p in [first, last] if p)
                gift_reference = f"matching gift for {name}"
            else:
                gift_reference = self._build_gift_reference(company=self._company_re_name(company_config, company_name))

            output_row = {
                "RE Constituent ID": self._company_id(company_config, company_name),
                "Gift Date": gift_date,
                "GL Post Date": gl_post_date,
                "Gift Amount": amount,
                "Campaign": get_campaign(gl_post_date) if gl_post_date else "",
                "Appeal": get_appeal(gl_post_date) if gl_post_date else "",
                "Branch": branch,
                "Gift Reference": gift_reference,
                "Soft Credit Individual ID": soft_credit_id,
                "Soft Credit Entity ID": self.entity_constituent_id,
                "Soft Credit Entity ID 2": "",
            }

            company_rows.append(output_row)

        return pd.DataFrame(company_rows), stale_cache_rows

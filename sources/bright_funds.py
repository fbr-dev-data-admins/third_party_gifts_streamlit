"""Bright Funds source transformer."""

import io
from datetime import date
import pandas as pd

from .base import BaseSource
from utils.date_utils import format_date, format_gl_post_date
from utils.fiscal import get_campaign, get_appeal
from utils.name_parsing import parse_full_name


class BrightFundsSource(BaseSource):
    """Transformer for Bright Funds donation reports."""

    name = "Bright Funds"
    entity_constituent_id = "141437"

    def detect(self, df_raw: pd.DataFrame, raw_bytes: bytes) -> bool:
        """Detect Bright Funds by header starting with specific columns."""
        try:
            cols = list(df_raw.columns)[:4]
            expected = ["ID", "Created", "Company Name", "Donor Name"]
            return cols == expected
        except Exception:
            return False

    def read_file(self, raw_bytes: bytes) -> pd.DataFrame:
        """Read Bright Funds file (CSV or XLSX) with headers on row 0."""
        if raw_bytes[:4] == b'PK\x03\x04':
            return pd.read_excel(io.BytesIO(raw_bytes))
        return pd.read_csv(io.BytesIO(raw_bytes))

    def get_companies(self, df: pd.DataFrame) -> set:
        """Get unique company names from Company Name and Donor Name columns."""
        companies = set()

        individual_df = df[df["Company Name"] != "-"] if "Company Name" in df.columns else pd.DataFrame()
        if "Company Name" in individual_df.columns:
            companies.update(individual_df["Company Name"].dropna().unique())

        company_df = df[df["Company Name"] == "-"] if "Company Name" in df.columns else pd.DataFrame()
        if "Donor Name" in company_df.columns:
            companies.update(company_df["Donor Name"].dropna().unique())

        companies.discard("-")
        return companies

    def transform_part1(
        self,
        df: pd.DataFrame,
        company_config: dict,
        pass_through_agents: dict = None
    ) -> tuple[pd.DataFrame, pd.DataFrame, set, set]:
        """Transform Bright Funds data for Part 1 import (Individual donations)."""
        gl_post_date = format_gl_post_date()
        unified_rows = []

        individual_df = df[df["Company Name"] != "-"] if "Company Name" in df.columns else df

        for _, row in individual_df.iterrows():
            company = str(row.get("Company Name", "")) if pd.notna(row.get("Company Name")) else ""
            if company == "-":
                continue

            gift_date = format_date(row.get("Created"))

            donor_name = str(row.get("Donor Name", "")) if pd.notna(row.get("Donor Name")) else ""
            first_name, middle_name, last_name = parse_full_name(donor_name)

            is_anonymous = donor_name.lower() in ["private", "anon anon"]

            email = str(row.get("Donor Email", "")) if pd.notna(row.get("Donor Email")) else ""
            if email.lower() == "private" or "@cisco.com" in email.lower():
                email = ""

            designation = str(row.get("Designation", "")) if pd.notna(row.get("Designation")) else ""
            gift_reference = self._build_gift_reference(designation if designation else None, company=self._company_re_name(company_config, company))

            branch = self._check_branch(designation)

            output_row = {
                "RE Constituent ID": "22-2934" if is_anonymous else "",
                "Gift Date": gift_date,
                "GL Post Date": gl_post_date,
                "Gift Amount": row.get("Amount", 0),
                "Campaign": get_campaign(gl_post_date) if gl_post_date else "",
                "Appeal": get_appeal(gl_post_date) if gl_post_date else "",
                "Donation Type": "",
                "Branch": branch,
                "Gift Reference": gift_reference,
                "Soft Credit Company ID": self._company_id(company_config, company),
                "Soft Credit Entity ID": self.entity_constituent_id,
                "Soft Credit Entity ID 2": "",
                "First Name": "" if is_anonymous else first_name,
                "Middle Name": "" if is_anonymous else middle_name,
                "Last Name": "" if is_anonymous else last_name,
                "Address": "",
                "City": "",
                "State": "",
                "ZIP": "",
                "Country": "",
                "Primary Phone": "",
                "Email": "" if is_anonymous else email,
            }

            unified_rows.append(output_row)

        unified_df = pd.DataFrame(unified_rows)
        grants_df = pd.DataFrame()

        return unified_df, grants_df, set(), set()

    def transform_part2(
        self,
        df: pd.DataFrame,
        company_config: dict,
        cache_df: pd.DataFrame
    ) -> tuple[pd.DataFrame, set]:
        """Transform Bright Funds data for Part 2 (Company donations)."""
        gl_post_date = format_gl_post_date()
        today_str = date.today().strftime("%m/%d/%Y")
        company_rows = []
        stale_cache_rows = set()

        company_df = df[df["Company Name"] == "-"] if "Company Name" in df.columns else pd.DataFrame()

        for _, row in company_df.iterrows():
            company_name = str(row.get("Donor Name", "")) if pd.notna(row.get("Donor Name")) else ""
            gift_date = format_date(row.get("Created"))
            amount = row.get("Amount", 0)

            on_behalf_of = str(row.get("On Behalf Of", "")) if pd.notna(row.get("On Behalf Of")) else ""

            is_anonymous = on_behalf_of.lower() in ["private", "anon anon"]
            soft_credit_id = "22-2934" if is_anonymous else ""
            branch = "Main" if is_anonymous else ""

            if not is_anonymous and on_behalf_of and not cache_df.empty:
                first, middle, last = parse_full_name(on_behalf_of)

                for cache_idx in range(len(cache_df) - 1, -1, -1):
                    cache_row = cache_df.iloc[cache_idx]

                    cache_first = str(cache_row.get("First Name", "")).lower()
                    cache_last = str(cache_row.get("Last Name", "")).lower()
                    cache_company = str(cache_row.get("Company", ""))

                    if (cache_first == first.lower() and
                        cache_last == last.lower() and
                        cache_company == self._company_id(company_config, company_name)):

                        soft_credit_id = str(cache_row.get("Constituent ID", ""))
                        branch = str(cache_row.get("Branch", "Main")) or "Main"
                        cache_added = str(cache_row.get("Date Added to Cache", ""))
                        if cache_added != today_str:
                            stale_cache_rows.add(len(company_rows))
                        break

            first, middle, last = parse_full_name(on_behalf_of)
            if is_anonymous:
                gift_reference = "matching gift for Anonymous"
            elif first and last:
                gift_reference = f"matching gift for {first} {last}"
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
            }

            company_rows.append(output_row)

        return pd.DataFrame(company_rows), stale_cache_rows

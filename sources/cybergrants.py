"""CyberGrants source transformer."""

import io
from datetime import date
import pandas as pd

from .base import BaseSource
from utils.date_utils import format_date, format_gl_post_date
from utils.fiscal import get_campaign, get_appeal


class CyberGrantsSource(BaseSource):
    """Transformer for CyberGrants donation reports."""

    name = "CyberGrants"
    entity_constituent_id = "20-175516"

    def detect(self, df_raw: pd.DataFrame, raw_bytes: bytes) -> bool:
        """Detect CyberGrants by column index 2 containing 'CyberGrants'."""
        try:
            if len(df_raw.columns) > 2:
                col_value = str(df_raw.columns[2])
                return "CyberGrants" in col_value
        except Exception:
            pass
        return False

    def read_file(self, raw_bytes: bytes) -> pd.DataFrame:
        """Read CyberGrants file with headers on row 0."""
        return pd.read_csv(io.BytesIO(raw_bytes))

    def get_companies(self, df: pd.DataFrame) -> set:
        """Get unique company names from Company Name column."""
        if "Company Name" in df.columns:
            return set(df["Company Name"].dropna().unique())
        return set()

    def get_pass_through_agents(self, df: pd.DataFrame) -> set:
        """Get unique non-blank Pass-through Agent names."""
        if "Pass-through Agent" in df.columns:
            agents = df["Pass-through Agent"].dropna()
            return set(a for a in agents.unique() if str(a).strip())
        return set()

    def transform_part1(
        self,
        df: pd.DataFrame,
        company_config: dict,
        pass_through_agents: dict = None
    ) -> tuple[pd.DataFrame, pd.DataFrame, set, set]:
        """Transform CyberGrants data for Part 1 import (employee donations)."""
        gl_post_date = format_gl_post_date()
        unified_rows = []
        pass_through_agents = pass_through_agents or {}

        employee_df = df[df["Payment Funding Source"].str.lower() == "employee"] if "Payment Funding Source" in df.columns else df

        for _, row in employee_df.iterrows():
            company = str(row.get("Company Name", "")) if pd.notna(row.get("Company Name")) else ""
            gift_date = format_date(row.get("Donation Start Date"))

            frequency = str(row.get("Donation Frequency", "")) if pd.notna(row.get("Donation Frequency")) else ""
            donation_type = "Recurring" if frequency.lower() == "recurring" else ""

            gift_reference = self._build_gift_reference(company=self._company_re_name(company_config, company))
            branch = "Main"

            country = str(row.get("Donor Country", "")) if pd.notna(row.get("Donor Country")) else ""
            if not country:
                country = "United States"

            agent_name = str(row.get("Pass-through Agent", "")).strip() if pd.notna(row.get("Pass-through Agent")) else ""
            entity_id_2 = pass_through_agents.get(agent_name, "") if agent_name else ""

            output_row = {
                "RE Constituent ID": "",
                "Gift Date": gift_date,
                "GL Post Date": gl_post_date,
                "Gift Amount": row.get("Donation Amount", 0),
                "Campaign": get_campaign(gl_post_date) if gl_post_date else "",
                "Appeal": get_appeal(gl_post_date) if gl_post_date else "",
                "Donation Type": donation_type,
                "Branch": branch,
                "Gift Reference": gift_reference,
                "Soft Credit Company ID": self._company_id(company_config, company),
                "Soft Credit Entity ID": self.entity_constituent_id,
                "Soft Credit Entity ID 2": entity_id_2,
                "First Name": str(row.get("Donor First Name", "")).title() if pd.notna(row.get("Donor First Name")) else "",
                "Middle Name": "",
                "Last Name": str(row.get("Donor Last Name", "")).title() if pd.notna(row.get("Donor Last Name")) else "",
                "Address": str(row.get("Donor Address", "")) if pd.notna(row.get("Donor Address")) else "",
                "City": str(row.get("Donor City", "")) if pd.notna(row.get("Donor City")) else "",
                "State": str(row.get("Donor State", "")) if pd.notna(row.get("Donor State")) else "",
                "ZIP": self._clean_zip(row.get("Donor ZIP/Postal Code")),
                "Country": (
                    (
                        ("United States" if str(row.get("Country", "")).upper() == "US" else str(row.get("Country", "")))
                        if str(row.get("Country", "")).strip() not in ["", "Not shared by donor", "nan"] else (
                            "United States" if any([
                                str(row.get("Address", "")).strip() not in ["", "Not shared by donor", "nan"],
                                str(row.get("City", "")).strip() not in ["", "Not shared by donor", "nan"],
                                str(row.get("State/Province", "")).strip() not in ["", "Not shared by donor", "nan"],
                                str(row.get("Postal Code", "")).strip() not in ["", "Not shared by donor", "nan"],
                            ]) else ""
                        )
                    )
                ),
                "Primary Phone": str(row.get("Donor Telephone", "")) if pd.notna(row.get("Donor Telephone")) else "",
                "Email": str(row.get("Donor Email Address", "")) if pd.notna(row.get("Donor Email Address")) else "",
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
        """Transform CyberGrants data for Part 2 (company donations)."""
        gl_post_date = format_gl_post_date()
        today_str = date.today().strftime("%m/%d/%Y")
        company_rows = []
        stale_cache_rows = set()

        company_df = df[df["Payment Funding Source"].str.lower() == "company"] if "Payment Funding Source" in df.columns else pd.DataFrame()

        for _, row in company_df.iterrows():
            company = str(row.get("Company Name", "")) if pd.notna(row.get("Company Name")) else ""
            gift_date = format_date(row.get("Donation Start Date"))

            first_name = str(row.get("Donor First Name", "")).lower() if pd.notna(row.get("Donor First Name")) else ""
            last_name = str(row.get("Donor Last Name", "")).lower() if pd.notna(row.get("Donor Last Name")) else ""
            donation_amount = row.get("Donation Amount", 0)

            try:
                donation_amount = float(donation_amount) if pd.notna(donation_amount) else 0
            except (ValueError, TypeError):
                donation_amount = 0

            is_anonymous = not first_name and not last_name
            soft_credit_id = "22-2934" if is_anonymous else ""
            branch = "Main"

            if not is_anonymous and not cache_df.empty:
                for cache_idx in range(len(cache_df) - 1, -1, -1):
                    cache_row = cache_df.iloc[cache_idx]

                    cache_first = str(cache_row.get("First Name", "")).lower()
                    cache_last = str(cache_row.get("Last Name", "")).lower()
                    cache_company = str(cache_row.get("Company", ""))
                    cache_amount = cache_row.get("Gift Amount", 0)

                    try:
                        cache_amount = float(cache_amount) if pd.notna(cache_amount) else 0
                    except (ValueError, TypeError):
                        cache_amount = 0

                    if (cache_last == last_name and
                        cache_company == self._company_id(company_config, company) and
                        cache_amount == donation_amount):

                        soft_credit_id = str(cache_row.get("Constituent ID", ""))
                        branch = str(cache_row.get("Branch", "Main")) or "Main"
                        cache_added = str(cache_row.get("Date Added to Cache", ""))
                        if cache_added != today_str:
                            stale_cache_rows.add(len(company_rows))
                        break

            match_amount = row.get("Match Amount", 0)
            try:
                match_amount = float(match_amount) if pd.notna(match_amount) else 0
            except (ValueError, TypeError):
                match_amount = 0

            display_first = str(row.get("Donor First Name", "")).title() if pd.notna(row.get("Donor First Name")) else ""
            display_last = str(row.get("Donor Last Name", "")).title() if pd.notna(row.get("Donor Last Name")) else ""

            if is_anonymous:
                gift_reference = "matching gift for Anonymous"
            elif display_first and display_last:
                gift_reference = f"matching gift for {display_first} {display_last}"
            else:
                gift_reference = self._build_gift_reference(company=self._company_re_name(company_config, company))

            output_row = {
                "RE Constituent ID": self._company_id(company_config, company),
                "Gift Date": gift_date,
                "GL Post Date": gl_post_date,
                "Gift Amount": match_amount,
                "Campaign": get_campaign(gl_post_date) if gl_post_date else "",
                "Appeal": get_appeal(gl_post_date) if gl_post_date else "",
                "Branch": branch,
                "Gift Reference": gift_reference,
                "Soft Credit Individual ID": soft_credit_id,
                "Soft Credit Entity ID": self.entity_constituent_id,
            }

            company_rows.append(output_row)

        return pd.DataFrame(company_rows), stale_cache_rows

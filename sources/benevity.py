"""Benevity source transformer."""

import io
from datetime import date
import pandas as pd

from .base import BaseSource
from utils.date_utils import format_date, format_gl_post_date
from utils.fiscal import get_campaign, get_appeal


class BenevitySource(BaseSource):
    """Transformer for Benevity donation reports."""

    name = "Benevity"
    entity_constituent_id = "146545"

    def detect(self, df_raw: pd.DataFrame, raw_bytes: bytes) -> bool:
        """Detect Benevity by first line containing 'Donations Report,'."""
        try:
            first_line = raw_bytes.decode("utf-8", errors="ignore").split("\n")[0]
            return first_line.strip().startswith("Donations Report,")
        except Exception:
            return False

    def read_file(self, raw_bytes: bytes) -> pd.DataFrame:
        """Read Benevity file with data headers on row index 11."""
        df = pd.read_csv(io.BytesIO(raw_bytes), skiprows=11)
        first_col = df.columns[0]
        totals_idx = df.index[df[first_col].astype(str).str.strip() == "Totals"]
        if not totals_idx.empty:
            df = df.iloc[:totals_idx[0]]
        return df

    def get_companies(self, df: pd.DataFrame) -> set:
        """Get unique company names from Company column."""
        if "Company" in df.columns:
            return set(df["Company"].dropna().unique())
        return set()

    def transform_part1(
        self,
        df: pd.DataFrame,
        company_config: dict,
        pass_through_agents: dict = None
    ) -> tuple[pd.DataFrame, pd.DataFrame, set, set]:
        """Transform Benevity data for Part 1 import."""
        gl_post_date = format_gl_post_date()
        unified_rows = []
        grants_rows = []
        benevity_amount_rows = set()
        benevity_reason_rows = set()

        for idx, row in df.iterrows():
            reason = str(row.get("Reason", "")) if pd.notna(row.get("Reason")) else ""

            if "grant" in reason.lower():
                grants_rows.append(row)
                continue

            is_anonymous = False
            first_name = row.get("Donor First Name", "")
            last_name = row.get("Donor Last Name", "")

            if str(first_name) == "Not shared by donor" or str(last_name) == "Not shared by donor":
                is_anonymous = True

            company = str(row.get("Company", "")) if pd.notna(row.get("Company")) else ""
            gift_date = format_date(row.get("Donation Date"))

            comment = str(row.get("Comment", "")) if pd.notna(row.get("Comment")) and str(row.get("Comment")).strip() else ""
            gift_ref_parts = []
            if comment:
                gift_ref_parts.append(comment)

            if reason and reason not in ["User Donation", "User Portfolio Donation", "Anonymous Donation", "Match", ""]:
                gift_ref_parts.append(reason)

            gift_reference = self._build_gift_reference(*gift_ref_parts, company=self._company_re_name(company_config, company))

            frequency = str(row.get("Donation Frequency", "")) if pd.notna(row.get("Donation Frequency")) else ""
            donation_type = "Recurring" if frequency.lower() == "recurring" else ""

            branch = self._check_branch(comment)

            amount = row.get("Total Donation to be Acknowledged", 0)
            try:
                amount = float(amount) if pd.notna(amount) else 0
            except (ValueError, TypeError):
                amount = 0

            if amount == 0:
                continue

            output_row = {
                "RE Constituent ID": "22-2934" if is_anonymous else "",
                "Gift Date": gift_date,
                "GL Post Date": gl_post_date,
                "Gift Amount": amount,
                "Campaign": get_campaign(gl_post_date) if gl_post_date else "",
                "Appeal": get_appeal(gl_post_date) if gl_post_date else "",
                "Donation Type": donation_type,
                "Branch": branch,
                "Gift Reference": gift_reference,
                "Soft Credit Company ID": self._company_id(company_config, company),
                "Soft Credit Entity ID": self.entity_constituent_id,
                "Soft Credit Entity ID 2": "",
                "First Name": "" if is_anonymous else str(first_name).title() if pd.notna(first_name) else "",
                "Middle Name": "",
                "Last Name": "" if is_anonymous else str(last_name).title() if pd.notna(last_name) else "",
                "Address": "" if is_anonymous else (str(row.get("Address", "")) if pd.notna(row.get("Address")) and str(row.get("Address")) != "Not shared by donor" else ""),
                "City": "" if is_anonymous else (str(row.get("City", "")) if pd.notna(row.get("City")) and str(row.get("City")) != "Not shared by donor" else ""),
                "State": "" if is_anonymous else (str(row.get("State/Province", "")) if pd.notna(row.get("State/Province")) and str(row.get("State/Province")) != "Not shared by donor" else ""),
                "ZIP": "" if is_anonymous else (self._clean_zip(row.get("Postal Code")) if pd.notna(row.get("Postal Code")) and str(row.get("Postal Code")) != "Not shared by donor" else ""),
                "Country": "" if is_anonymous else ("United States" if any([
                    str(row.get("Address", "")) not in ["", "Not shared by donor", "nan"],
                    str(row.get("City", "")) not in ["", "Not shared by donor", "nan"],
                    str(row.get("State/Province", "")) not in ["", "Not shared by donor", "nan"],
                    str(row.get("Postal Code", "")) not in ["", "Not shared by donor", "nan"],
                ]) else ""),
                "Primary Phone": "",
                "Email": "" if is_anonymous else (str(row.get("Email", "")) if pd.notna(row.get("Email")) and str(row.get("Email")) != "Not shared by donor" else ""),
            }

            row_idx = len(unified_rows)

            if amount >= 1000:
                benevity_amount_rows.add(row_idx)

            if reason and reason not in ["User Donation", ""]:
                benevity_reason_rows.add(row_idx)

            unified_rows.append(output_row)

        unified_df = pd.DataFrame(unified_rows)
        grants_df = pd.DataFrame(grants_rows)

        return unified_df, grants_df, benevity_amount_rows, benevity_reason_rows

    def transform_part2(
        self,
        df: pd.DataFrame,
        company_config: dict,
        cache_df: pd.DataFrame,
        pass_through_agents: dict = None
    ) -> tuple[pd.DataFrame, set]:
        """Transform Benevity data for Part 2 (Companies) import."""
        gl_post_date = format_gl_post_date()
        today_str = date.today().strftime("%m/%d/%Y")
        company_rows = []
        stale_cache_rows = set()

        for _, row in df.iterrows():
            match_amount = row.get("Match Amount", 0)
            try:
                match_amount = float(match_amount) if pd.notna(match_amount) else 0
            except (ValueError, TypeError):
                match_amount = 0

            if match_amount == 0:
                continue

            company = str(row.get("Company", "")) if pd.notna(row.get("Company")) else ""
            gift_date = format_date(row.get("Donation Date"))

            first_name = str(row.get("Donor First Name", "")) if pd.notna(row.get("Donor First Name")) else ""
            last_name = str(row.get("Donor Last Name", "")) if pd.notna(row.get("Donor Last Name")) else ""

            is_anonymous = first_name == "Not shared by donor" or last_name == "Not shared by donor"

            soft_credit_id = "22-2934" if is_anonymous else ""
            branch = "Main" if is_anonymous else ""

            if not is_anonymous and not cache_df.empty:
                donor_amount = row.get("Total Donation to be Acknowledged", 0)
                try:
                    donor_amount = float(donor_amount) if pd.notna(donor_amount) else 0
                except (ValueError, TypeError):
                    donor_amount = 0

                for cache_idx in range(len(cache_df) - 1, -1, -1):
                    cache_row = cache_df.iloc[cache_idx]

                    cache_first = str(cache_row.get("First Name", "")).lower()
                    cache_last = str(cache_row.get("Last Name", "")).lower()
                    cache_company = str(cache_row.get("Company", ""))
                    cache_date = str(cache_row.get("Gift Date", ""))
                    cache_amount = cache_row.get("Gift Amount", 0)

                    try:
                        cache_amount = float(cache_amount) if pd.notna(cache_amount) else 0
                    except (ValueError, TypeError):
                        cache_amount = 0

                    if (cache_first == first_name.lower() and
                        cache_last == last_name.lower() and
                        cache_company == self._company_id(company_config, company) and
                        cache_date == gift_date and
                        cache_amount == donor_amount):

                        soft_credit_id = str(cache_row.get("Constituent ID", ""))
                        branch = str(cache_row.get("Branch", "Main")) or "Main"
                        cache_added = str(cache_row.get("Date Added to Cache", ""))
                        if cache_added != today_str:
                            stale_cache_rows.add(len(company_rows))
                        break

            if is_anonymous:
                gift_reference = "matching gift for Anonymous"
            elif first_name and last_name:
                gift_reference = f"matching gift for {first_name.title()} {last_name.title()}"
            elif not soft_credit_id and (first_name or last_name):
                name = " ".join(p.title() for p in [first_name, last_name] if p)
                gift_reference = f"matching gift for {name}"
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
                "Soft Credit Entity ID 2": "",
            }

            company_rows.append(output_row)

        return pd.DataFrame(company_rows), stale_cache_rows

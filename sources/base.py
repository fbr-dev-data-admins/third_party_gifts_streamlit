"""Abstract base class for source transformers."""

from abc import ABC, abstractmethod
from typing import Optional
import pandas as pd


class BaseSource(ABC):
    """Abstract base class for workplace giving platform source transformers."""

    name: str = "Base"
    entity_constituent_id: str = ""

    @abstractmethod
    def detect(self, df_raw: pd.DataFrame, raw_bytes: bytes) -> bool:
        """
        Detect if this source matches the uploaded file.

        Args:
            df_raw: DataFrame read without skipping rows
            raw_bytes: Raw file bytes for text inspection

        Returns:
            True if this source matches the file
        """
        raise NotImplementedError

    @abstractmethod
    def read_file(self, raw_bytes: bytes) -> pd.DataFrame:
        """
        Read the file with source-specific parsing (skip rows, etc.).

        Args:
            raw_bytes: Raw file bytes

        Returns:
            DataFrame with proper headers
        """
        raise NotImplementedError

    @abstractmethod
    def transform_part1(
        self,
        df: pd.DataFrame,
        company_config: dict,
        pass_through_agents: dict = None
    ) -> tuple[pd.DataFrame, pd.DataFrame, set, set]:
        """
        Transform source data for Part 1 (Individuals) import.

        Args:
            df: Source DataFrame
            company_config: Company name -> {"id": RE Import ID, "re_name": Raiser's Edge name} mapping

        Returns:
            Tuple of:
                - unified_individuals_df: DataFrame for unified import
                - grants_df: DataFrame for grants file (raw source rows)
                - benevity_rows: Set of row indices from Benevity with amount >= 1000
                - benevity_reason_rows: Set of row indices with non-standard Reason
        """
        raise NotImplementedError

    @abstractmethod
    def transform_part2(
        self,
        df: pd.DataFrame,
        company_config: dict,
        cache_df: pd.DataFrame
    ) -> tuple[pd.DataFrame, set]:
        """
        Transform source data for Part 2 (Companies) import.

        Args:
            df: Source DataFrame
            company_config: Company name -> {"id": RE Import ID, "re_name": Raiser's Edge name} mapping
            cache_df: Donor cache DataFrame for matching

        Returns:
            Tuple of:
                - unified_companies_df: DataFrame for unified companies import
                - stale_cache_rows: Set of row indices (0-based) where the matched
                  cache entry was not added today
        """
        raise NotImplementedError

    def get_companies(self, df: pd.DataFrame) -> set:
        """
        Get all unique company names from the source data.

        Override in subclasses to specify the correct column name.

        Args:
            df: Source DataFrame

        Returns:
            Set of company names
        """
        return set()

    def get_pass_through_agents(self, df: pd.DataFrame) -> set:
        """Get unique pass-through agent names. Override in CyberGrants."""
        return set()

    @staticmethod
    def _clean_zip(val) -> str:
        """Convert ZIP to string, stripping trailing .0 from numeric reads."""
        if pd.isna(val) or str(val).strip() in ("", "nan"):
            return ""
        s = str(val).strip()
        if s.endswith(".0"):
            s = s[:-2]
        return s

    def _company_id(self, company_config: dict, company: str) -> str:
        """
        Look up the RE Import ID for a company from the company config.

        Args:
            company_config: Company name -> {"id": RE Import ID, "re_name": Raiser's Edge name} mapping
            company: Company display name as read from the source file

        Returns:
            RE Import ID string, or empty string if not configured
        """
        return company_config.get(company, {}).get("id", "")

    def _company_re_name(self, company_config: dict, company: str) -> str:
        """
        Look up the Raiser's Edge display name for a company from the company config.
        Falls back to the raw source name if re_name is not set.

        Args:
            company_config: Company name -> {"id": RE Import ID, "re_name": Raiser's Edge name} mapping
            company: Company display name as read from the source file

        Returns:
            Raiser's Edge display name, or raw company name as fallback
        """
        re_name = company_config.get(company, {}).get("re_name", "")
        return re_name if re_name else company

    def _check_branch(self, text: Optional[str]) -> str:
        """
        Check if text contains branch indicators.

        Args:
            text: Text to check (gift reference, designation, etc.)

        Returns:
            'WSlope' if branch indicator found, 'Main' otherwise
        """
        if not text or pd.isna(text):
            return "Main"

        text_lower = str(text).lower()
        if any(term in text_lower for term in ["wslope", "western slope", "western slopes"]):
            return "WSlope"
        return "Main"

    def _build_gift_reference(self, *parts: Optional[str], company: str = "") -> str:
        """
        Build gift reference by joining non-empty parts with ' ; '.

        Always appends "{Company} workplace giving" at the end.

        Args:
            *parts: Variable number of reference parts
            company: Company name to append

        Returns:
            Formatted gift reference string
        """
        valid_parts = [str(p).strip() for p in parts if p and pd.notna(p) and str(p).strip()]

        if company:
            valid_parts.append(f"{company} workplace giving")

        return " ; ".join(valid_parts)

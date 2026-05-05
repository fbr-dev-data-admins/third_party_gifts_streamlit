"""Donor cache management for GitHub and local storage."""

import io
from datetime import date, timedelta
from typing import Optional
import pandas as pd

from .config import get_secret, load_json_from_github, save_json_to_github


CACHE_COLUMNS = [
    "Date Added to Cache",
    "Constituent ID",
    "First Name",
    "Last Name",
    "Gift Date",
    "Gift Amount",
    "Company",
    "Entity",
    "Branch",
    "Email"
]


def load_cache(use_github: bool = True) -> pd.DataFrame:
    """
    Load the donor cache from GitHub or create an empty cache.

    Args:
        use_github: If True, load from GitHub; otherwise use local storage

    Returns:
        DataFrame with cache data
    """
    if use_github:
        try:
            cache_repo = get_secret("github.cache_repo")
            token = get_secret("github.access_token")

            from .config import _parse_repo_url
            import requests
            import base64

            owner, repo = _parse_repo_url(cache_repo)
            api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/donor_cache.csv"

            headers = {
                "Accept": "application/vnd.github.v3+json",
                "Authorization": f"token {token}"
            }

            response = requests.get(api_url, headers=headers)

            if response.status_code == 200:
                content = response.json()
                decoded = base64.b64decode(content["content"]).decode("utf-8")
                df = pd.read_csv(io.StringIO(decoded))
                for col in CACHE_COLUMNS:
                    if col not in df.columns:
                        df[col] = ""
                return df
            else:
                return pd.DataFrame(columns=CACHE_COLUMNS)

        except Exception:
            return pd.DataFrame(columns=CACHE_COLUMNS)
    else:
        try:
            df = pd.read_csv("donor_cache.csv")
            for col in CACHE_COLUMNS:
                if col not in df.columns:
                    df[col] = ""
            return df
        except FileNotFoundError:
            return pd.DataFrame(columns=CACHE_COLUMNS)


def save_cache(df: pd.DataFrame, use_github: bool = True) -> bool:
    """
    Save the donor cache to GitHub or local storage.

    Args:
        df: DataFrame with cache data
        use_github: If True, save to GitHub; otherwise use local storage

    Returns:
        True if successful
    """
    if use_github:
        try:
            cache_repo = get_secret("github.cache_repo")
            token = get_secret("github.access_token")

            from .config import _parse_repo_url
            import requests
            import base64

            owner, repo = _parse_repo_url(cache_repo)
            api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/donor_cache.csv"

            headers = {
                "Accept": "application/vnd.github.v3+json",
                "Authorization": f"token {token}"
            }

            existing_sha = None
            response = requests.get(api_url, headers=headers)
            if response.status_code == 200:
                existing_sha = response.json()["sha"]

            csv_content = df.to_csv(index=False)
            content = base64.b64encode(csv_content.encode("utf-8")).decode("utf-8")

            payload = {
                "message": "Update donor cache",
                "content": content
            }
            if existing_sha:
                payload["sha"] = existing_sha

            response = requests.put(api_url, headers=headers, json=payload)
            response.raise_for_status()
            return True

        except Exception as e:
            print(f"Error saving cache to GitHub: {e}")
            return False
    else:
        df.to_csv("donor_cache.csv", index=False)
        return True


def add_to_cache(
    cache_df: pd.DataFrame,
    rows: pd.DataFrame,
    company: str,
    entity: str
) -> pd.DataFrame:
    """
    Add new donor rows to the cache.

    Args:
        cache_df: Existing cache DataFrame
        rows: New rows to add (from transform output)
        company: Company name
        entity: Entity name (can be empty)

    Returns:
        Updated cache DataFrame
    """
    today = date.today().strftime("%m/%d/%Y")

    new_cache_rows = []
    for _, row in rows.iterrows():
        new_cache_rows.append({
            "Date Added to Cache": today,
            "Constituent ID": "",
            "First Name": row.get("First Name", ""),
            "Last Name": row.get("Last Name", ""),
            "Gift Date": row.get("Gift Date", ""),
            "Gift Amount": row.get("Gift Amount", ""),
            "Company": company,
            "Entity": entity,
            "Branch": "",
            "Email": row.get("Email", "")
        })

    if new_cache_rows:
        new_df = pd.DataFrame(new_cache_rows)
        cache_df = pd.concat([cache_df, new_df], ignore_index=True)

    return cache_df


def clean_cache(cache_df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean the cache by removing old entries and duplicates.

    Rules:
        - Remove rows where Date Added to Cache > 400 days ago
        - Remove duplicate Constituent IDs, keeping most recently added

    Args:
        cache_df: Cache DataFrame to clean

    Returns:
        Cleaned cache DataFrame
    """
    if cache_df.empty:
        return cache_df

    cutoff_date = date.today() - timedelta(days=400)

    cache_df["_parsed_date"] = pd.to_datetime(
        cache_df["Date Added to Cache"],
        format="%m/%d/%Y",
        errors="coerce"
    )

    cache_df = cache_df[
        cache_df["_parsed_date"].isna() |
        (cache_df["_parsed_date"].dt.date > cutoff_date)
    ]

    has_constituent_id = cache_df["Constituent ID"].notna() & (cache_df["Constituent ID"] != "")

    with_id = cache_df[has_constituent_id].copy()
    without_id = cache_df[~has_constituent_id].copy()

    if not with_id.empty:
        with_id = with_id.drop_duplicates(subset=["Constituent ID"], keep="last")

    cache_df = pd.concat([without_id, with_id], ignore_index=True)

    cache_df = cache_df.drop(columns=["_parsed_date"], errors="ignore")

    return cache_df

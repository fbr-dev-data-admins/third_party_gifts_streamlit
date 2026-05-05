"""Configuration and secrets management with GitHub file I/O abstraction."""

import base64
import json
import os
from typing import Any, Optional

import requests


def get_secret(key_path: str) -> Any:
    """
    Retrieve a secret value by key path.

    In Streamlit: reads from st.secrets using dot notation (e.g., "github.access_token")
    In Flask: reads from environment variables (e.g., "GITHUB_ACCESS_TOKEN")
    """
    try:
        import streamlit as st
        parts = key_path.split(".")
        value = st.secrets
        for part in parts:
            value = value[part]
        return value
    except ImportError:
        env_key = key_path.replace(".", "_").upper()
        return os.environ.get(env_key)
    except KeyError:
        env_key = key_path.replace(".", "_").upper()
        return os.environ.get(env_key)


def _parse_repo_url(repo_url: str) -> tuple[str, str]:
    """Parse GitHub repo URL into owner and repo name."""
    repo_url = repo_url.rstrip("/")
    if repo_url.endswith(".git"):
        repo_url = repo_url[:-4]
    parts = repo_url.split("/")
    return parts[-2], parts[-1]


def load_json_from_github(repo_url: str, file_path: str, token: Optional[str] = None) -> dict:
    """
    Load a JSON file from a GitHub repository.

    Args:
        repo_url: Full GitHub repository URL
        file_path: Path to the file within the repository
        token: GitHub access token (required for private repos)

    Returns:
        Parsed JSON as a dictionary
    """
    owner, repo = _parse_repo_url(repo_url)
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}"

    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"

    response = requests.get(api_url, headers=headers)
    response.raise_for_status()

    content = response.json()
    decoded = base64.b64decode(content["content"]).decode("utf-8")
    return json.loads(decoded)


def save_json_to_github(
    repo_url: str,
    file_path: str,
    data: dict,
    token: str,
    commit_message: str
) -> bool:
    """
    Save a JSON file to a GitHub repository.

    Args:
        repo_url: Full GitHub repository URL
        file_path: Path to the file within the repository
        data: Dictionary to save as JSON
        token: GitHub access token
        commit_message: Commit message for the update

    Returns:
        True if successful
    """
    owner, repo = _parse_repo_url(repo_url)
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}"

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {token}"
    }

    existing_sha = None
    response = requests.get(api_url, headers=headers)
    if response.status_code == 200:
        existing_sha = response.json()["sha"]

    content = base64.b64encode(json.dumps(data, indent=2).encode("utf-8")).decode("utf-8")

    payload = {
        "message": commit_message,
        "content": content
    }
    if existing_sha:
        payload["sha"] = existing_sha

    response = requests.put(api_url, headers=headers, json=payload)
    response.raise_for_status()
    return True


def load_text_list_from_github(
    repo_url: str,
    file_path: str,
    token: Optional[str] = None
) -> list[str]:
    """
    Load a text file from GitHub and return as a list of lines.

    Args:
        repo_url: Full GitHub repository URL
        file_path: Path to the file within the repository
        token: GitHub access token (required for private repos)

    Returns:
        List of non-empty lines from the file
    """
    owner, repo = _parse_repo_url(repo_url)
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}"

    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"

    response = requests.get(api_url, headers=headers)
    response.raise_for_status()

    content = response.json()
    decoded = base64.b64decode(content["content"]).decode("utf-8")
    return [line.strip() for line in decoded.split("\n") if line.strip()]


def save_multiple_files_to_github(
    repo_url: str,
    files: dict[str, Any],
    token: str,
    commit_message: str
) -> bool:
    """
    Save multiple files to GitHub in a single atomic commit using Git Data API.

    Args:
        repo_url: Full GitHub repository URL
        files: Dictionary mapping file paths to content (dict for JSON, str for text)
        token: GitHub access token
        commit_message: Commit message for the update

    Returns:
        True if successful
    """
    owner, repo = _parse_repo_url(repo_url)
    base_url = f"https://api.github.com/repos/{owner}/{repo}"

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {token}"
    }

    ref_response = requests.get(f"{base_url}/git/ref/heads/main", headers=headers)
    ref_response.raise_for_status()
    base_sha = ref_response.json()["object"]["sha"]

    commit_response = requests.get(f"{base_url}/git/commits/{base_sha}", headers=headers)
    commit_response.raise_for_status()
    base_tree_sha = commit_response.json()["tree"]["sha"]

    tree_items = []
    for file_path, content in files.items():
        if isinstance(content, dict):
            content_str = json.dumps(content, indent=2)
        else:
            content_str = str(content)

        blob_response = requests.post(
            f"{base_url}/git/blobs",
            headers=headers,
            json={"content": content_str, "encoding": "utf-8"}
        )
        blob_response.raise_for_status()
        blob_sha = blob_response.json()["sha"]

        tree_items.append({
            "path": file_path,
            "mode": "100644",
            "type": "blob",
            "sha": blob_sha
        })

    tree_response = requests.post(
        f"{base_url}/git/trees",
        headers=headers,
        json={"base_tree": base_tree_sha, "tree": tree_items}
    )
    tree_response.raise_for_status()
    new_tree_sha = tree_response.json()["sha"]

    commit_response = requests.post(
        f"{base_url}/git/commits",
        headers=headers,
        json={
            "message": commit_message,
            "tree": new_tree_sha,
            "parents": [base_sha]
        }
    )
    commit_response.raise_for_status()
    new_commit_sha = commit_response.json()["sha"]

    ref_update = requests.patch(
        f"{base_url}/git/refs/heads/main",
        headers=headers,
        json={"sha": new_commit_sha}
    )
    ref_update.raise_for_status()

    return True


def load_local_json(file_path: str) -> dict:
    """Load JSON from local filesystem."""
    with open(file_path, "r") as f:
        return json.load(f)


def save_local_json(file_path: str, data: dict) -> bool:
    """Save JSON to local filesystem."""
    with open(file_path, "w") as f:
        json.dump(data, f, indent=2)
    return True

# Third Party Unified Gift Processor

A Streamlit application for transforming workplace giving platform exports into unified RE NXT import files.

## Supported Platforms

- Benevity
- CyberGrants
- YourCause
- Bright Funds
- Fidelity Marketplace Giving

## Quick Start

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Configure secrets (see [Secrets Configuration](#secrets-configuration))

3. Run the app:
   ```bash
   streamlit run app.py
   ```

## Adding a New Source

To add support for a new workplace giving platform:

1. Create a new file in `sources/` (e.g., `sources/newsource.py`)

2. Implement the source class:
   ```python
   from .base import BaseSource
   
   class NewSource(BaseSource):
       name = "New Source"
       entity_constituent_id = "12345"  # RE Constituent ID for this platform's entity soft credit
       
       def detect(self, df_raw, raw_bytes):
           # Return True if this file matches your source
           pass
       
       def read_file(self, raw_bytes):
           # Parse the file and return a DataFrame
           pass
       
       def get_companies(self, df):
           # Return set of company names from the data
           pass
       
       def transform_part1(self, df, company_config):
           # Transform individual donations
           # Return (unified_df, grants_df, benevity_rows, reason_rows)
           pass
       
       def transform_part2(self, df, company_config, cache_df):
           # Transform company/matching gifts
           # Return unified_companies_df
           pass
   ```

3. Register in `sources/__init__.py`:
   ```python
   from .newsource import NewSource
   
   SOURCE_REGISTRY = {
       # ... existing sources ...
       "New Source": NewSource,
   }
   ```

## Configuration Files

### company.json

Maps company display names (as read from source files) to their RE Import ID
and their name as it appears in Raiser's Edge:

```json
{
  "Acme Corporation": {
    "id": "12345",
    "re_name": "Acme Corp"
  },
  "Widget Inc.": {
    "id": "67890",
    "re_name": "Widget Incorporated"
  }
}
```

The configuration file is stored in GitHub (configured in secrets) and synced
automatically. New companies encountered during processing are prompted for
both their RE Constituent ID and Raiser's Edge name via the UI.

Each source's RE Constituent ID for entity soft credits (e.g. Benevity,
CyberGrants) is hardcoded as the `entity_constituent_id` class attribute on
the source transformer in `sources/`.

## Secrets Configuration

### For Streamlit Cloud

Paste the following into the Secrets section of your app settings:

```toml
[app]
password = "your_app_password"

[github]
config_repo = "https://github.com/org/config-repo"
cache_repo = "https://github.com/org/private-cache-repo"
access_token = "ghp_your_github_personal_access_token"

[re_api]
client_id = "blackbaud_client_id"
client_secret = "blackbaud_client_secret"
redirect_uri = "https://your-streamlit-app.streamlit.app/callback"
subscription_key = "blackbaud_subscription_key"
query_id = "saved_query_id"
```

### For Local Development

Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in values.

### GitHub PAT Permissions

The GitHub Personal Access Token requires:
- `repo` (Full control of private repositories) - for cache repo access
- `public_repo` - for config repo if public

## RE Sky API Authorization

The app uses OAuth 2.0 to authenticate with Blackbaud Sky API. Authorization flow:

1. Click "Get Authorization URL" in the sidebar
2. Visit the URL and log in with your Blackbaud credentials
3. Authorize the application
4. Copy the authorization code from the redirect URL
5. Paste the code into the app and click "Submit Code"

### Re-authorization

Refresh tokens expire after 1 year. When expired:
1. Clear existing authentication in the sidebar
2. Follow the authorization flow again

## Architecture Notes

### Secrets Abstraction

All secrets are accessed via `utils/config.get_secret(key_path)`. This allows easy migration from Streamlit to Flask:

- Streamlit: reads from `st.secrets`
- Flask: reads from environment variables (e.g., `GITHUB_ACCESS_TOKEN`)

### GitHub I/O Abstraction

All GitHub operations use helpers in `utils/config.py`:
- `load_json_from_github()` - fetch JSON files
- `save_json_to_github()` - commit JSON files
- `save_multiple_files_to_github()` - atomic multi-file commits

### Session State

All session data is stored in Streamlit's `st.session_state`. For Flask migration, replace with server-side session storage.

## Troubleshooting

### "Config source: Local" instead of GitHub

Check that:
- `github.config_repo` and `github.access_token` are set correctly
- The GitHub PAT has not expired
- The repository URLs are correct

### RE API Authentication Fails

- Verify `client_id`, `client_secret`, and `subscription_key` are correct
- Check that `redirect_uri` matches exactly what's configured in Blackbaud Developer Portal
- Ensure the Blackbaud environment (sandbox vs. production) matches your credentials

### Company Not Found

If a company name from a source file is not in `company.json`:
1. The app will block processing and prompt for the RE Import ID
2. Enter the Import ID from Raiser's Edge
3. Click "Save Company Mappings" to update the configuration

### Cache Issues

The donor cache is stored in a private GitHub repository. If cache operations fail:
- Verify `github.cache_repo` and `github.access_token` are correct
- Ensure the PAT has write access to the private repository
- Check if `donor_cache.csv` exists in the repository root

## File Output

### Individual Import File

Excel file with:
- Bold headers with blue fill
- Auto-fitted column widths
- Conditional formatting:
  - Yellow highlight on State column if blank but ZIP is not blank
  - Orange highlight on Benevity gifts >= $1,000
  - Yellow highlight on Gift Reference for non-standard Benevity Reason values

### Grants File

Excel file containing raw source rows for grants that need manual processing:
- Source headers as section dividers
- Multiple sources stacked vertically
- Only generated if grant rows exist

### Company Import File

Excel file with company matching gift data, formatted similarly to the individual import file.

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "NekoMail"
    database_url: str
    secret_key: str
    mail_encryption_key: str
    # Raw .eml storage root. Same convention as DATABASE_URL: relative path
    # resolved from the process cwd on the host, overridden to the
    # in-container path by docker-compose (both live under the ./data bind mount).
    mail_storage_path: str = "./data/mail"
    # Safety-net full poll (all folders, all accounts) -- IDLE covers INBOX
    # near-instantly, this catches everything else and any missed pushes.
    poll_interval_seconds: int = 300
    # How often the account-watcher list is reconciled against the DB (new
    # accounts get an IDLE watcher, removed/deactivated ones get stopped).
    idle_reconcile_interval_seconds: int = 30
    admin_username: str = "admin"
    admin_password: str
    debug: bool = False
    # Set to True in production when serving over HTTPS
    cookie_secure: bool = False

    # Outlook OAuth2 account linking (Phase 7) -- optional. Blank client_id
    # disables the "Link Outlook Account" flow entirely; NekoMail's core has
    # no Microsoft dependency without it. See NEXT_STEPS.md for the exact
    # Azure App Registration shape this requires.
    azure_client_id: str = ""
    azure_authority: str = "https://login.microsoftonline.com/common"
    # Must exactly match both what NekoMail is actually reached at AND the
    # redirect URI registered on the Azure app (this + the fixed
    # /api/accounts/oauth/outlook/callback path).
    public_base_url: str = "http://localhost:8090"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

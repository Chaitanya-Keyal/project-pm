from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    pm_database_url: str = "sqlite+aiosqlite:///./project-pm.db"
    lens_config_dir: str = ""
    host: str = "0.0.0.0"
    port: int = 8420
    debug: bool = False
    admin_token: str = ""
    github_client_id: str = ""
    github_client_secret: str = ""
    session_secret_key: str = ""
    base_url: str = ""
    admin_github_usernames: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def admin_usernames_set(self) -> set[str]:
        """Parse comma-separated admin usernames into a set."""
        if not self.admin_github_usernames:
            return set()
        return {u.strip().lower() for u in self.admin_github_usernames.split(",") if u.strip()}

    def validate_lens_config(self) -> None:
        if not self.lens_config_dir:
            raise ValueError("LENS_CONFIG_DIR is required in .env")
        if not Path(self.lens_config_dir).is_dir():
            raise ValueError(f"Lens config directory not found: {self.lens_config_dir}")


settings = Settings()

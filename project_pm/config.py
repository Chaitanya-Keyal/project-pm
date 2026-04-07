from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    pm_database_url: str = "sqlite+aiosqlite:///./project-pm.db"
    lens_config_dir: str = ""
    host: str = "0.0.0.0"
    port: int = 8420
    debug: bool = False
    admin_token: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}

    def validate_lens_config(self) -> None:
        if not self.lens_config_dir:
            raise ValueError("LENS_CONFIG_DIR is required in .env")
        if not Path(self.lens_config_dir).is_dir():
            raise ValueError(f"Lens config directory not found: {self.lens_config_dir}")


settings = Settings()

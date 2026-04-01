from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    pm_database_url: str = "sqlite+aiosqlite:///./project-pm.db"
    lens_database_path: str = ""
    host: str = "0.0.0.0"
    port: int = 8420
    debug: bool = False
    admin_token: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def lens_database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.lens_database_path}"

    def validate_lens_path(self) -> None:
        if not self.lens_database_path:
            raise ValueError("LENS_DATABASE_PATH is required in .env")
        if not Path(self.lens_database_path).exists():
            raise ValueError(f"Lens database not found: {self.lens_database_path}")


settings = Settings()

from text_to_sql_agent.config import get_settings
from text_to_sql_agent.database import initialize_database


def main() -> None:
    settings = get_settings()
    initialize_database(settings.database_source)
    print(f"Initialized {settings.database_dialect} database at {settings.database_source}")


if __name__ == "__main__":
    main()

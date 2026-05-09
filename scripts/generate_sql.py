import argparse

from text_to_sql_agent.sql_generator import generate_sql


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate SQL for a natural-language question.")
    parser.add_argument("question", help="Natural-language question to convert to SQL.")
    args = parser.parse_args()
    print(generate_sql(args.question))


if __name__ == "__main__":
    main()


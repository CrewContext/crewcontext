"""CLI for CrewContext."""
import click
from .utils import load_env


@click.group()
@click.version_option(version="0.1.0")
def main():
    """CrewContext - Context coordination for multi-agent workflows."""
    load_env()


@main.group()
def demo():
    """Run demo scenarios."""
    pass


@demo.command("vendor-discrepancy")
def vendor_discrepancy():
    """Run the vendor discrepancy demo."""
    from .demos.vendor_discrepancy import run_demo
    run_demo()


@main.command("init-db")
@click.option("--db-url", envvar="CREWCONTEXT_DB_URL", default=None)
def init_db(db_url):
    """Initialise the database schema."""
    from .store.postgres import PostgresStore
    store = PostgresStore(db_url)
    store.connect()
    store.init_schema()
    store.close()
    click.echo("Database schema initialised.")


if __name__ == "__main__":
    main()

import click

from jerald import __version__


@click.group()
@click.version_option(__version__, prog_name="jerald")
def main() -> None:
    """Jerald: a statistical regression harness for AI agents."""


if __name__ == "__main__":
    main()

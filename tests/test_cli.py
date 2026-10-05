from click.testing import CliRunner

from jerald.cli import main


def test_version() -> None:
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "jerald" in result.output

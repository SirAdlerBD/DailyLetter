import pytest

from dailyletter.cli import clean_secret, read_env_value

TOKEN = "3f" * 32


@pytest.mark.parametrize("pasted", [
    TOKEN,
    f"  {TOKEN}\r",
    f"\x1b[200~{TOKEN}\x1b[201~",
    f'"{TOKEN}"',
    f"MCP_ACCESS_TOKEN={TOKEN}",
])
def test_clean_secret_removes_what_a_paste_adds(pasted):
    assert clean_secret(pasted) == TOKEN


def test_read_env_value(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# comment\nGARMIN_PERSONAL_API_KEY=abc\n"
        f"MCP_ACCESS_TOKEN= {TOKEN} \nHTTP_PORT=3001\n",
        encoding="utf-8",
    )
    assert read_env_value(str(env), "MCP_ACCESS_TOKEN") == TOKEN
    with pytest.raises(KeyError):
        read_env_value(str(env), "MISSING")

"""Known-issues #11: the library never reads a .env from its working directory;
only the platform server (or an explicit EIDOLON_ENV_FILE) does."""

import subprocess
import sys

from eidolon.config import ENV_FILE_VAR, Settings, get_settings, use_env_file


def test_a_library_ignores_the_env_file_where_it_runs(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("EIDOLON_AUTONOMY_DIAL=observe\nEIDOLON_SAGE_BACKEND=postgres\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(ENV_FILE_VAR, raising=False)
    get_settings.cache_clear()
    try:
        assert Settings().autonomy_dial == "autonomous"
        assert get_settings().sage_backend == "memory"
    finally:
        get_settings.cache_clear()


def test_the_server_opts_in(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("EIDOLON_AUTONOMY_DIAL=observe\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(ENV_FILE_VAR, raising=False)
    try:
        use_env_file()
        assert get_settings().autonomy_dial == "observe"
        assert Settings().autonomy_dial == "autonomous"  # direct construction still reads the environment only
    finally:
        get_settings.cache_clear()


def test_importing_the_api_package_opts_in(tmp_path):
    (tmp_path / ".env").write_text("EIDOLON_AUTONOMY_DIAL=draft\n")
    code = ("import eidolon.config as c; assert c.get_settings().autonomy_dial == 'autonomous'; "
            "c.get_settings.cache_clear(); import eidolon.api; "
            "assert c.get_settings().autonomy_dial == 'draft'")
    env = {k: v for k, v in __import__("os").environ.items() if k != ENV_FILE_VAR}
    subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, check=True)

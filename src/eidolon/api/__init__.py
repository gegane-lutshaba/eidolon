"""FastAPI service surface exposing the EIDOLON seams."""

from eidolon.config import use_env_file

# The platform server reads .env from where it runs; the library never does (known-issues #11).
use_env_file()

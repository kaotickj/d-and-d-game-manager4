"""Windows PyInstaller entrypoint using package-safe imports."""
from dndgm4.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())

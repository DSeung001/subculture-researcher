"""Entry point kept at the project root; the code lives in subculture.web.app."""

from subculture.web.app import app, main  # noqa: F401 (`app` for `flask --app app`)

if __name__ == "__main__":
    main()

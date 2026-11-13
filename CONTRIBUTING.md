# Contributing

Thanks for looking. Blip is a work-in-progress hobby project.

- Open an issue with the bug report template (version from the About tab, board, serial monitor output, what the phone showed).
- Pull requests are welcome. By contributing you agree that your contribution is licensed under the same PolyForm Noncommercial License 1.0.0 as the rest of the project, with copyright credited to you in the commit history.
- Before a PR: run `python3 tests/test_parser_py.py`, build `tests/test_parser.cpp`, run `python3 tools/embed_web.py` if you touched the UI, and `python3 tools/draw_illustrations.py` if you touched pins.
- First real-hardware reports are the most valuable contribution right now: which board, which arduino-esp32 version, what compiled, what didn't.

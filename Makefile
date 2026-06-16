build_and_copy:
	cmake -S . -B build && cmake --build build && cp build/fallout-ce ~/Downloads/fallout_folder/

start_app:
	companion_app/.venv/bin/python -m companion_app --config companion_app/config.example.json
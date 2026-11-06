"""Local web UI: live view of a run's workflow (from trace.jsonl) and the single-vs-multi comparison.

    p2e serve            # http://127.0.0.1:8765

`data.py` turns the run directories into JSON; `server.py` serves it with the standard library, no extra
dependencies; `index.html` is the whole frontend.
"""

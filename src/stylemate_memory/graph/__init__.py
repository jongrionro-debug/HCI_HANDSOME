"""ADR 0013 graph engine (STYLEMATE_ENGINE=graph).

Pure modules (situations, parse, hypotheses, intent, scoring, grid) need no
extra dependency. ``engine`` imports langgraph lazily and is only loaded when
the graph engine is selected.
"""

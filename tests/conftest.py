"""Shared setup for the whole suite, and the reason exactcsv and flowcases import from every
subfolder.

pytest's default prepend import mode puts this file's folder, tests/, at the front of sys.path
when it loads it, before it imports any test module. So test modules in tests/flow and the other
subfolders import exactcsv and flowcases by their bare names, whatever order pytest collects them
in and whichever single file is run.
"""

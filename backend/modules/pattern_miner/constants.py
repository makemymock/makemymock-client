"""Collection names for the mined catalog.

Both collections live on the PYQ cluster (see db.py) and are populated by the
standalone Pattern_Miner pipeline. This module only reads them.
"""

PATTERNS_COLLECTION = "patterns"
ASSIGNMENTS_COLLECTION = "pattern_assignments"

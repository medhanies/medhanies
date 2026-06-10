"""AML Transaction Flagging Engine.

A rules-based transaction monitoring pipeline modeled on U.S. Bank Secrecy
Act / FinCEN regulations, OFAC sanctions programs, and FATF guidance. The
engine generates synthetic banking data with planted suspicious patterns,
runs a catalog of documented detection rules against it, scores the results,
and produces a SAR-candidate worklist for investigator triage.

Educational/portfolio project. All data is synthetic; jurisdiction lists are
point-in-time snapshots and must be re-verified before any real-world use.
"""

__version__ = "1.0.0"

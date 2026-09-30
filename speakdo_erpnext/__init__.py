# Canonical version of the SpeakDo ERPNext companion: the ONLY place where it is
# written. pyproject.toml declares it dynamic (flit reads it from here); every
# other surface derives from it (constants.COMPANION_VERSION, User-Agent,
# proofs, SpeakDo Settings.companion_version, admin page). See docs/RELEASE.md.
__version__ = "1.0.0"

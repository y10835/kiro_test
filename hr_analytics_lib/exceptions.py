"""Exception classes for the HR Analytics Library.

This module defines the error types raised by the generator and serializer
when configuration is invalid or output conflicts are detected.
"""


class ConfigError(ValueError):
    """Raised when GenerationConfig parameters violate constraints.
    
    Guarantees: no Data_Tables are produced when this is raised (fail-fast).
    The message always names the offending parameter.
    """
    pass


class OutputExistsError(OSError):
    """Raised when the target output directory already contains files.
    
    The serializer will NOT overwrite existing files. The user must
    explicitly clear the directory or use a different path.
    """
    pass

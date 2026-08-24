"""Platform parsers used by F2Media.

All parsers return F2Media's normalized media-result dictionary.  Parser modules may
perform HTTP/API requests while parsing, but must never write media files.
"""

from .common import normalize_external_result, has_downloadable_media

__all__ = ["normalize_external_result", "has_downloadable_media"]

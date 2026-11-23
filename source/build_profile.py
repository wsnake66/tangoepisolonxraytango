"""Build-time feature flags.

Release packagers rewrite this module in their isolated staging tree. The
working source tree remains a development build so local diagnostics stay
available.
"""

IS_PRODUCTION_BUILD = False

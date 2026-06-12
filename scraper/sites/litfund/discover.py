from __future__ import annotations

import re

# Auction ids are numeric with an optional session suffix (757, 671s1, 739.2).
# Matching ``/auction/<id>/`` covers both catalog links and lot links (a lot url
# ``/auction/752/2/`` still reveals auction 752); utility pages like
# ``/auction/archives/`` or ``/auction/rules/`` do not match because they lack
# the leading digits.
_AUCTION_HREF_RE = re.compile(r"/auction/(\d+(?:[.s]\d+)?)/")


def extract_auction_ids(html: str) -> list[str]:
    """Return auction ids found in ``html`` in document (recency) order, deduped.

    The litfund archive lists auctions newest-first, so first-seen order is the
    recency order we want to preserve.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for match in _AUCTION_HREF_RE.finditer(html or ""):
        auction_id = match.group(1)
        if auction_id not in seen:
            seen.add(auction_id)
            ordered.append(auction_id)
    return ordered

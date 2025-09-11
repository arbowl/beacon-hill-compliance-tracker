""" Test the collection of committees. """

from components.models import Committee


def test_step1_get_committees(
    committees: list[Committee], base_url: str
) -> list[str]:
    """ Run a few basic sanity checks on the committees. """
    problems = []
    if not committees:
        problems.append("No committees found")
    ids = [c.id for c in committees]
    if len(set(ids)) != len(ids):
        problems.append("Duplicate committee IDs encountered")
    bad_ids = [
        c.id
        for c in committees
        if not (c.id and c.id[0] in ("J", "H"))
    ]
    if bad_ids:
        problems.append(f"Non House/Joint IDs present: {bad_ids}")
    bad_urls = [
        c.url
        for c in committees
        if not c.url.startswith(base_url + "/Committees/Detail/")
    ]
    if bad_urls:
        problems.append(f"Unexpected detail URL shapes: {bad_urls[:3]}")
    bad_names = [c.name for c in committees if not c.name or c.name.isspace()]
    if bad_names:
        problems.append("One or more committees have blank names")
    return problems

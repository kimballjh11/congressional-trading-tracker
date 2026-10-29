# test_enricher.py — tests for enricher.py's Senate committee-assignment scraper
#
# Context: fetch_senate_committee_data() splits senate.gov's committee
# assignments page into one block per senator using the anchor tags the
# page embeds right before each senator's name, e.g. <a name="BaldwinWI">.
# The split regex used to capture the anchor value with `\w+`, which only
# matches word characters (letters/digits/underscore). Real anchor values
# are NOT always a single word — multi-word last names render with a
# literal space ("Blunt RochesterDE", "Cortez MastoNV", "Van HollenMD"),
# hyphenated names keep their hyphen ("Hyde-SmithMS"), and accented names
# appear percent-encoded ("Luj%C3%A1nNM"). For every one of these, the old
# `\w+` anchor regex failed to match the anchor tag at all, so re.split()
# never split on it — that senator's own committee block silently merged
# into the END of the PRECEDING senator's block instead of starting a new
# one. Confirmed live against the real senate.gov page (2026-10-29): this
# dropped Blunt Rochester (DE), Cortez Masto (NV), Hyde-Smith (MS), Luján
# (NM), and Van Hollen (MD) from the map entirely (zero committees, so
# score_committee_match() can never fire for their real trades) while
# attributing their committees to whichever senator happened to be listed
# immediately before them (a false committee/sector-match signal risk for
# that unrelated senator's trades).
#
# Fix: match up to the closing quote (`[^"]+`) instead of `\w+`, so the
# anchor's full value is captured regardless of spaces/hyphens/encoding.

import enricher


# A minimal but structurally real fixture reproducing the exact failure
# mode: three consecutive senators, the middle one ("Blunt Rochester, DE")
# has a last name containing a space in its anchor. Committee markup/CSS
# is trimmed to the pieces fetch_senate_committee_data() actually parses.
SENATE_HTML_FIXTURE = """
<div style="float:left; width:25%; font-weight:bold; min-width:200px;">
<a name="BlumenthalCT">&nbsp;</a><a href="https://www.blumenthal.senate.gov">Blumenthal, Richard</a> (D-CT)</div>
<div style="float:left; width:72%; min-width:200px;">
<ul>
<li><strong><a href="/general/committee_membership/committee_memberships_SSAS.htm">Committee on Armed Services</a></strong></li>
<li><strong><a href="/general/committee_membership/committee_memberships_SSJU.htm">Committee on the Judiciary</a></strong></li>
</ul>
</div>
<hr>
<div style="float:left; width:25%; font-weight:bold; min-width:200px;">
<a name="Blunt RochesterDE">&nbsp;</a><a href="https://www.bluntrochester.senate.gov/">Blunt Rochester, Lisa</a> (D-DE)</div>
<div style="float:left; width:72%; min-width:200px;">
<ul>
<li><strong><a href="/general/committee_membership/committee_memberships_SSBK.htm">Committee on Banking, Housing, and Urban Affairs</a></strong></li>
<li><strong><a href="/general/committee_membership/committee_memberships_SSHR.htm">Committee on Health, Education, Labor, and Pensions</a></strong></li>
</ul>
</div>
<hr>
<div style="float:left; width:25%; font-weight:bold; min-width:200px;">
<a name="BoozmanAR">&nbsp;</a><a href="https://www.boozman.senate.gov/">Boozman, John</a> (R-AR)</div>
<div style="float:left; width:72%; min-width:200px;">
<ul>
<li><strong><a href="/general/committee_membership/committee_memberships_SSAF.htm">Committee on Agriculture, Nutrition, and Forestry</a></strong></li>
</ul>
</div>
"""


def _fetch_with_fixture(monkeypatch, html):
    class FakeResponse:
        status_code = 200
        text = html

    monkeypatch.setattr(enricher.requests, "get", lambda *a, **k: FakeResponse())
    return enricher.fetch_senate_committee_data()


def test_multiword_lastname_senator_is_not_dropped(monkeypatch):
    comms = _fetch_with_fixture(monkeypatch, SENATE_HTML_FIXTURE)
    assert "Blunt Rochester, Lisa|DE" in comms


def test_multiword_lastname_senator_gets_own_committees_only(monkeypatch):
    comms = _fetch_with_fixture(monkeypatch, SENATE_HTML_FIXTURE)
    assert comms["Blunt Rochester, Lisa|DE"] == [
        "Committee on Banking, Housing, and Urban Affairs",
        "Committee on Health, Education, Labor, and Pensions",
    ]


def test_preceding_senator_does_not_inherit_next_senators_committees(monkeypatch):
    """
    Before the fix, Blumenthal's block never ended at his own closing tag —
    it silently absorbed Blunt Rochester's committees too, since the
    anchor-based split never fired on her entry.
    """
    comms = _fetch_with_fixture(monkeypatch, SENATE_HTML_FIXTURE)
    assert comms["Blumenthal, Richard|CT"] == [
        "Committee on Armed Services",
        "Committee on the Judiciary",
    ]


def test_senator_after_the_affected_one_is_unaffected(monkeypatch):
    comms = _fetch_with_fixture(monkeypatch, SENATE_HTML_FIXTURE)
    assert comms["Boozman, John|AR"] == ["Committee on Agriculture, Nutrition, and Forestry"]


def test_hyphenated_and_percent_encoded_anchor_values_also_split_correctly(monkeypatch):
    """
    The same `\\w+`-vs-`[^"]+` gap also broke hyphenated last names
    (Hyde-Smith) and percent-encoded accented names (Luján) — not just
    anchors containing a literal space.
    """
    html = """
<div style="float:left; width:25%; font-weight:bold; min-width:200px;">
<a name="HustedOH">&nbsp;</a><a href="https://www.husted.senate.gov/">Husted, Jon</a> (R-OH)</div>
<div style="float:left; width:72%; min-width:200px;">
<ul><li><strong><a href="/x/committee_memberships_A.htm">Committee on Commerce, Science, and Transportation</a></strong></li></ul>
</div>
<hr>
<div style="float:left; width:25%; font-weight:bold; min-width:200px;">
<a name="Hyde-SmithMS">&nbsp;</a><a href="https://www.hydesmith.senate.gov/">Hyde-Smith, Cindy</a> (R-MS)</div>
<div style="float:left; width:72%; min-width:200px;">
<ul><li><strong><a href="/x/committee_memberships_B.htm">Committee on Appropriations</a></strong></li></ul>
</div>
"""
    comms = _fetch_with_fixture(monkeypatch, html)
    assert comms["Hyde-Smith, Cindy|MS"] == ["Committee on Appropriations"]
    assert comms["Husted, Jon|OH"] == ["Committee on Commerce, Science, and Transportation"]

from generate_notes import ATTACHMENT_SECTION_CAP, trim_attachments


def test_trim_attachments_caps_each_section() -> None:
    md = ("# Agenda attachment excerpts\n\nintro\n\n"
          "## Expenditures - Complete\n\n" + ("x" * 5000) + "\n\n"
          "## Small One\n\nGrand Total $5,000\n")
    out = trim_attachments(md)
    assert "## Expenditures - Complete" in out
    assert "[... truncated ...]" in out
    assert "Grand Total $5,000" in out  # small sections pass through whole
    # each section body is bounded
    for body in out.split("## ")[1:]:
        assert len(body) < ATTACHMENT_SECTION_CAP + 200


def test_trim_attachments_passthrough_when_small() -> None:
    md = "# Agenda attachment excerpts\n\n## A\n\nshort\n"
    assert "[... truncated ...]" not in trim_attachments(md)

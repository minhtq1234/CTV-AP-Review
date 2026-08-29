import io

from PIL import Image

from test_fixtures import demo_case


def test_page_image_is_a_readable_png_of_the_requested_size():
    data = demo_case.page_png("HỢP ĐỒNG DỊCH VỤ", ["Bên A: VNG", "Bên B: NGUYEN VAN MOT"],
                              width=1000, height=1400)

    image = Image.open(io.BytesIO(data))
    assert image.format == "PNG"
    assert image.size == (1000, 1400)
    # Not a blank sheet: something was drawn. getcolors rather than getdata,
    # which Pillow deprecated.
    assert len(image.convert("L").getcolors()) > 1


def test_page_image_is_deterministic():
    """The same inputs must give the same bytes, or every rebuild of the demo
    case shows as a change and the fixture stops being a fixture."""
    first = demo_case.page_png("A", ["b"], width=200, height=300)
    second = demo_case.page_png("A", ["b"], width=200, height=300)
    assert first == second


def test_the_demo_people_are_the_repository_s_one_fabricated_series():
    """Two sets of invented identities in one repo means a number in a fixture
    no longer means one person. The demo's identities come from the workbook
    fixture; only the payment detail is added here."""
    from test_fixtures.combined_workbook import PEOPLE as identities

    assert [person["name"] for person in demo_case.PEOPLE] == [
        name for name, _, _ in identities
    ]
    assert [person["cccd"] for person in demo_case.PEOPLE] == [
        cccd for _, cccd, _ in identities
    ]
    assert [person["mst"] for person in demo_case.PEOPLE] == [
        mst for _, _, mst in identities
    ]


def test_every_fabricated_number_is_recognisably_synthetic():
    """The guard that keeps a real contractor out of a committed fixture: every
    identifier belongs to a reserved synthetic range."""
    for person in demo_case.PEOPLE:
        for key in ("cccd", "mst", "tk"):
            value = person[key]
            assert value.isdigit(), f"{key} is not digits: {value}"
            assert value.startswith(("0011", "1900")), (
                f"{key}={value} is outside the synthetic ranges"
            )

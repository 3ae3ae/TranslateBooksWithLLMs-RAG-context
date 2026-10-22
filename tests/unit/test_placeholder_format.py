from src.common.placeholder_format import PlaceholderFormat


def test_parse_requires_the_entire_placeholder():
    placeholder_format = PlaceholderFormat.from_config()

    assert placeholder_format.parse("[id42]") == 42
    assert placeholder_format.parse("[id42]trailing") is None

from src.core.epub.tag_preservation import TagPreserver


def test_repeated_operations_stable():
    """Repeated operations give consistent results."""
    preserver = TagPreserver(protect_technical=True)

    html = "<p>The $V_{cm}$ is 10 Mbps.</p>"

    # Run multiple times
    results = []
    for _ in range(10):
        result, tag_map = preserver.preserve_tags_and_technical_content(html)
        results.append((result, tag_map))

    # All results should be identical
    first_result = results[0]
    for result, tag_map in results[1:]:
        assert result == first_result[0]
        assert tag_map == first_result[1]

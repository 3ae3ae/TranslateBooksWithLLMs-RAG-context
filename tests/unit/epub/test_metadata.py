from lxml import etree

from src.core.epub.translator import _update_epub_metadata


def test_original_identifier_preserved(tmp_path):
    opf_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        'unique-identifier="BookId">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:opf="http://www.idpf.org/2007/opf">'
        '<dc:title>Sample</dc:title>'
        '<dc:language>en</dc:language>'
        '<dc:identifier id="BookId">urn:isbn:0000000000</dc:identifier>'
        '</metadata>'
        '<manifest/><spine/>'
        '</package>'
    )
    opf_path = tmp_path / "content.opf"
    tree = etree.ElementTree(etree.fromstring(opf_xml.encode("utf-8")))
    _update_epub_metadata(tree, str(opf_path), "French")
    result = opf_path.read_text(encoding="utf-8")

    assert "urn:isbn:0000000000" in result
    assert 'id="BookId"' in result

from uc_steamos_agent.games.vdf import parse


def test_parse_flat_key_values():
    text = '"AppState"\n{\n\t"appid"\t\t"1686940"\n\t"name"\t\t"Bopl Battle"\n}\n'
    result = parse(text)
    assert result == {"AppState": {"appid": "1686940", "name": "Bopl Battle"}}


def test_parse_nested_blocks():
    text = (
        '"UserLocalConfigStore"\n{\n'
        '\t"Software"\n\t{\n'
        '\t\t"Valve"\n\t\t{\n'
        '\t\t\t"Steam"\n\t\t\t{\n'
        '\t\t\t\t"apps"\n\t\t\t\t{\n'
        '\t\t\t\t\t"1686940"\n\t\t\t\t\t{\n'
        '\t\t\t\t\t\t"LastPlayed"\t\t"1787507429"\n'
        '\t\t\t\t\t}\n'
        '\t\t\t\t}\n'
        '\t\t\t}\n'
        '\t\t}\n'
        '\t}\n'
        '}\n'
    )
    result = parse(text)
    apps = result["UserLocalConfigStore"]["Software"]["Valve"]["Steam"]["apps"]
    assert apps == {"1686940": {"LastPlayed": "1787507429"}}


def test_parse_handles_escaped_quotes_in_values():
    text = '"name"\t\t"Say \\"hi\\""\n'
    result = parse(text)
    assert result == {"name": 'Say "hi"'}


def test_parse_empty_block():
    text = '"UserConfig"\n{\n}\n'
    result = parse(text)
    assert result == {"UserConfig": {}}


def test_parse_multiple_sibling_apps():
    text = (
        '"apps"\n{\n'
        '\t"111"\n\t{\n\t\t"LastPlayed"\t\t"100"\n\t}\n'
        '\t"222"\n\t{\n\t\t"LastPlayed"\t\t"200"\n\t}\n'
        '}\n'
    )
    result = parse(text)
    assert result == {"apps": {"111": {"LastPlayed": "100"}, "222": {"LastPlayed": "200"}}}


def test_parse_empty_text_returns_empty_dict():
    assert parse("") == {}

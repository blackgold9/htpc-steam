from uc_steamos_agent.commands import keycodes as kc


def test_no_duplicate_command_names_across_simple_and_combo():
    overlap = set(kc.SIMPLE_KEY_COMMANDS) & set(kc.COMBO_KEY_COMMANDS)
    assert not overlap


def test_all_keycodes_covers_every_referenced_code():
    used = set(kc.SIMPLE_KEY_COMMANDS.values())
    for combo in kc.COMBO_KEY_COMMANDS.values():
        used.update(combo)
    assert used == set(kc.ALL_KEYCODES)


def test_gamescope_hotkeys_use_ctrl_combos():
    # docs/command-mapping.md: Ctrl+1 = Steam button, Ctrl+2 = QAM, Ctrl+6 = L3
    assert kc.COMBO_KEY_COMMANDS["steam_home"] == (kc.KEY_LEFTCTRL, kc.KEY_1)
    assert kc.COMBO_KEY_COMMANDS["steam_qam"] == (kc.KEY_LEFTCTRL, kc.KEY_2)
    assert kc.COMBO_KEY_COMMANDS["steam_l3"] == (kc.KEY_LEFTCTRL, kc.KEY_6)

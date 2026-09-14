from tools.runs.reset_artifacts import script


def test_cleanup_uses_only_inspected_names_and_rejects_newer_replacements():
    dry = script('D:/gicg_dev')
    apply = script('D:/gicg_dev', True)
    assert 'Remove-Item' not in dry
    assert '$dirs | Remove-Item -Recurse -Force' in apply
    assert 'Get-Item -LiteralPath (Join-Path $art $_)' in apply
    assert '2026-07-01T00:00:00Z' in apply
    assert 'ReparsePoint' in apply
    assert 'Python processes present' in apply
    assert '_*.log' not in apply
    assert 'Get-CimInstance' not in apply
    assert "'replays_final_fixed_F1D4'" in apply

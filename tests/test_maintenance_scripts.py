"""Static checks of the maintenance scripts run on Windows PCs (no PowerShell here)."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding='utf-8-sig')


class UpdateScript(unittest.TestCase):
    def test_follows_mcp_neolab_and_never_goes_back(self):
        script = text('scripts', 'update_warehouse_windows.ps1')
        self.assertIn("[string]$Branch = 'mcp-neolab'", script)
        guard = script.index("compare/$current...$latest")
        self.assertIn("'behind', 'diverged'", script[guard:])
        # the guard runs before any code is copied into the container
        self.assertLess(guard, script.index('docker cp "$($source.FullName)'))

    def test_refreshes_its_own_copies_and_the_skill(self):
        script = text('scripts', 'update_warehouse_windows.ps1')
        for name in ('update_warehouse_windows.ps1', 'publish_prebuilt_image.ps1'):
            self.assertIn(f"'{name}'", script)
            self.assertTrue((ROOT / 'scripts' / name).exists())
        self.assertIn(r"scripts\claude_skill\neolab-warehouse\SKILL.md", script)
        self.assertTrue((ROOT / 'scripts' / 'claude_skill' / 'neolab-warehouse' / 'SKILL.md').exists())

    def test_windows_scripts_keep_bom(self):
        for name in ('update_warehouse_windows.ps1', 'publish_prebuilt_image.ps1', 'install_from_registry_windows.ps1'):
            self.assertTrue((ROOT / 'scripts' / name).read_bytes().startswith(b'\xef\xbb\xbf'), name)


class PublishScript(unittest.TestCase):
    def test_no_windows_path_split_nor_quoted_entrypoint(self):
        script = text('scripts', 'publish_prebuilt_image.ps1')
        self.assertNotRegex(script, r'Split-Path[^\n]*\$pgdata')   # turned /var/lib/... into \var\lib\...
        self.assertNotIn('ENTRYPOINT', script)                      # PowerShell 5.1 breaks the quotes


class ContainerUpdate(unittest.TestCase):
    def test_ctd_links_are_restored_when_missing(self):
        update = text('docker', 'allinone', 'neolab-update')
        self.assertIn("link_method = 'proximity'", update)
        self.assertIn('neolab-load-ctd', update)
        self.assertIn('ctd_loaded', text('docker', 'allinone', 'neolab-load-ctd'))
        # a CTD failure warns but does not hide the rest of the update
        self.assertRegex(update, r'if ! bash /opt/neolab/IDEA/docker/allinone/neolab-load-ctd')

    def test_commands_installed_in_image_and_by_update(self):
        dockerfile = text('docker', 'allinone', 'Dockerfile')
        update = text('docker', 'allinone', 'neolab-update')
        for command in ('neolab-load-ctd', 'neolab-status', 'neolab-check', 'neolab-mcp'):
            self.assertIn(f'/usr/local/bin/{command}', dockerfile)
            self.assertIn(f'/usr/local/bin/{command}', update)


class Skill(unittest.TestCase):
    def test_skill_frontmatter_and_safety_rules(self):
        skill = text('scripts', 'claude_skill', 'neolab-warehouse', 'SKILL.md')
        head = re.match(r'---\nname: neolab-warehouse\ndescription: .+\n---\n', skill)
        self.assertIsNotNone(head)
        for rule in ('docker volume rm', 'jeton', 'mcp-neolab', 'MSYS_NO_PATHCONV=1', 'Ne rien pousser'):
            self.assertIn(rule, skill)


if __name__ == '__main__':
    unittest.main()

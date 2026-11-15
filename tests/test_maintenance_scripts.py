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

    def test_extracts_with_windows_tar(self):
        # From Git Bash, Git's tar came first and failed on "C:\..." ("Cannot connect to C: resolve failed").
        script = text('scripts', 'update_warehouse_windows.ps1')
        self.assertIn(r"Join-Path $env:SystemRoot 'System32\tar.exe'", script)
        self.assertNotRegex(script, r'(?m)^& tar\.exe ')

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


class CodePackage(unittest.TestCase):
    """Colleagues update from the small :code package of the image's own private package (read:packages)."""

    def test_publisher_ships_tracked_code_its_history_and_version_label(self):
        script = text('scripts', 'publish_code_image.ps1')
        self.assertIn('git -C $root -c core.autocrlf=false archive', script)   # tracked files only, LF
        self.assertIn('rev-parse "origin/$Branch"', script)     # what is on GitHub, not local work
        self.assertIn('.neolab_commits', script)
        self.assertIn('LABEL neolab.commit=$sha', script)
        self.assertIn('/neolab-warehouse"', script)              # same package as the image: same access
        self.assertTrue((ROOT / 'scripts' / 'publish_code_image.ps1').read_bytes().startswith(b'\xef\xbb\xbf'))

    def test_windows_update_uses_the_package_without_repository_token(self):
        script = text('scripts', 'update_warehouse_windows.ps1')
        self.assertIn("[ValidateSet('auto', 'github', 'registry')][string]$Source = 'auto'", script)
        self.assertIn("if (Test-Path $tokenFile) { 'github' } else { 'registry' }", script)
        self.assertIn("neolab-warehouse:code", script)
        guard = script.index('$earlier -notcontains $current')
        self.assertLess(guard, script.index('docker cp "$($source.FullName)'))   # checked before any copy

    def test_mac_update_never_goes_back_and_is_bash_3(self):
        script = text('scripts', 'update_warehouse.sh')
        self.assertIn('neolab-warehouse:code', script)
        guard = script.index('grep -qx "$current" "$work/IDEA/.neolab_commits"')
        self.assertLess(guard, script.index('docker cp "$work/IDEA/."'))
        self.assertNotIn('declare -A', script)
        self.assertNotIn('mapfile', script)
        self.assertNotIn(b'\r\n', subprocess_free_bytes('scripts', 'update_warehouse.sh'))

    def test_no_windows_line_endings_reach_the_container(self):
        # git archive follows core.autocrlf: on Windows it wrote CRLF and broke neolab-update (14 November 2026).
        self.assertIn('-c core.autocrlf=false archive', text('scripts', 'publish_code_image.ps1'))
        self.assertIn('$probe -contains 13', text('scripts', 'publish_code_image.ps1'))
        windows = text('scripts', 'update_warehouse_windows.ps1')
        self.assertLess(windows.index('-contains 13'), windows.index('docker cp "$($source.FullName)'))
        mac = text('scripts', 'update_warehouse.sh')
        self.assertLess(mac.index("printf '\\r'"), mac.index('docker cp "$work/IDEA/."'))

    def test_installers_apply_latest_code_and_leave_the_updater(self):
        windows = text('scripts', 'install_from_registry_windows.ps1')
        self.assertIn("-File $updater -Source registry", windows)
        mac = text('scripts', 'install_from_registry.sh')
        self.assertIn('bash "$here/update_warehouse.sh"', mac)
        self.assertIn('$HOME/neolab/update_warehouse.sh', mac)
        self.assertLess(mac.index('update_warehouse.sh'), mac.index('step "5/5'))


def subprocess_free_bytes(*parts: str) -> bytes:
    """Committed bytes of a script (git normalises to LF); the working copy may be CRLF on Windows."""
    import subprocess
    rel = '/'.join(parts)
    try:
        return subprocess.run(['git', '-C', str(ROOT), 'show', f':{rel}'], capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return ROOT.joinpath(*parts).read_bytes().replace(b'\r\n', b'\n')


class Skill(unittest.TestCase):
    def test_skill_frontmatter_and_safety_rules(self):
        skill = text('scripts', 'claude_skill', 'neolab-warehouse', 'SKILL.md')
        head = re.match(r'---\nname: neolab-warehouse\ndescription: .+\n---\n', skill)
        self.assertIsNotNone(head)
        for rule in ('docker volume rm', 'jeton', 'mcp-neolab', 'MSYS_NO_PATHCONV=1', 'Ne rien pousser'):
            self.assertIn(rule, skill)


if __name__ == '__main__':
    unittest.main()

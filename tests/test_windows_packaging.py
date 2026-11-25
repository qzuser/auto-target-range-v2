"""Regression checks for the Windows desktop packaging boundary."""
from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]


class WindowsPackagingTests(unittest.TestCase):
    def test_builder_owns_the_python_runtime_step(self) -> None:
        script = (PACKAGE / "packaging" / "windows" / "build-desktop.ps1").read_text(encoding="utf-8")
        self.assertIn("build-backend-runtime.ps1", script)
        self.assertIn("build-traffic-proxy.ps1", script)
        self.assertIn("spiritscout-traffic-proxy.exe", script)
        self.assertIn("dist\\windows\\desktop", script)
        self.assertIn("SpiritScout-$version-windows-x64.zip", script)
        self.assertNotIn("build-portable.ps1", script)
        self.assertNotIn("SpiritScoutDesktop.cs", script)

    def test_removed_webview_shell_is_not_part_of_the_source_tree(self) -> None:
        removed = (
            "launcher",
            "desktop/SpiritScoutCompose",
        )
        for relative in removed:
            self.assertFalse((PACKAGE / relative).exists(), relative)

    def test_compose_desktop_entrypoint_is_present(self) -> None:
        self.assertTrue(
            (PACKAGE / "desktop" / "src" / "main" / "kotlin"
             / "com" / "spiritscout" / "desktop" / "Main.kt").is_file()
        )
        self.assertTrue(
            (PACKAGE / "desktop" / "src" / "main" / "resources" / "favicon.png").is_file()
        )
        self.assertTrue((PACKAGE / "packaging" / "windows" / "icon.ico").is_file())
        self.assertTrue((PACKAGE / "packaging" / "windows" / "build-traffic-proxy.ps1").is_file())

    def test_gradle_uses_domestic_mirrors_with_official_fallbacks(self) -> None:
        settings = (PACKAGE / "desktop" / "settings.gradle.kts").read_text(encoding="utf-8")
        for mirror in (
            "https://maven.aliyun.com/repository/gradle-plugin",
            "https://maven.aliyun.com/repository/google",
            "https://maven.aliyun.com/repository/public",
        ):
            self.assertIn(mirror, settings)
        for fallback in ("google()", "mavenCentral()", "gradlePluginPortal()"):
            self.assertIn(fallback, settings)

    def test_desktop_runtime_includes_websocket_support(self) -> None:
        project = tomllib.loads((PACKAGE / "pyproject.toml").read_text(encoding="utf-8"))
        dependencies = project["project"]["dependencies"]
        self.assertTrue(any(item.lower().startswith("websockets") for item in dependencies))

    def test_source_manifest_includes_reproducible_project_inputs(self) -> None:
        manifest = (PACKAGE / "MANIFEST.in").read_text(encoding="utf-8")
        for required in (
            "graft desktop",
            "graft frontend",
            "graft scripts",
            "graft tests",
            "graft tools/experience-export",
            "graft traffic-proxy",
            "include Start-SpiritScout.cmd",
            "include desktop/src/main/resources/favicon.png",
        ):
            self.assertIn(required, manifest)
        self.assertNotIn("graft skills", manifest)
        self.assertNotIn("global-exclude *.png", manifest)

    def test_root_has_one_windows_entrypoint(self) -> None:
        self.assertTrue((PACKAGE / "Start-SpiritScout.cmd").is_file())
        for removed in (
            "启动服务.cmd",
            "start-local.ps1",
            "launch.cmd",
            "launch.ps1",
        ):
            self.assertFalse((PACKAGE / removed).exists(), removed)
        self.assertTrue((PACKAGE / "scripts" / "windows" / "start-web.ps1").is_file())
        self.assertTrue((PACKAGE / "scripts" / "windows" / "start-web.cmd").is_file())

    def test_release_workflows_have_one_owner(self) -> None:
        workflows = {
            path.name
            for path in (PACKAGE / ".github" / "workflows").glob("*.yml")
        }
        self.assertEqual(workflows, {"ci.yml", "package.yml", "release.yml"})

    def test_package_workflow_checks_a_shipped_frontend_asset(self) -> None:
        workflow = (PACKAGE / ".github" / "workflows" / "package.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("web/static/app/session.js", workflow)
        self.assertNotIn("web/static/js/count.js", workflow)


if __name__ == "__main__":
    unittest.main()

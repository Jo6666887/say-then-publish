import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build-share-skill.py"
PUBLIC_SKILL = ROOT / "skill-package" / "say-then-publish"


class ShareSkillPackageTests(unittest.TestCase):
    def test_public_skill_is_fixed_to_xiaohongshu_and_agent_native(self):
        text = (PUBLIC_SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("The platform is always `小红书`", text)
        self.assertIn("run this before asking the user anything", text)
        self.assertIn("checks whether the Agent's current working directory", text)
        self.assertIn("Never call an external layout or polish AI", text)
        self.assertIn("Personal creator memory", text)
        self.assertIn("assets/app/", text)
        self.assertNotIn("git clone", text)

    def test_builder_embeds_only_allowlisted_generic_application_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "output"
            subprocess.run(
                [sys.executable, str(BUILDER), "--output-dir", str(output_dir)],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            archive = output_dir / "say-then-publish-skill.zip"
            self.assertTrue(archive.is_file())
            with zipfile.ZipFile(archive) as bundle:
                names = set(bundle.namelist())
                self.assertIn("say-then-publish/assets/app/server.py", names)
                self.assertIn("say-then-publish/assets/app/src/app.js", names)
                self.assertIn("say-then-publish/scripts/bootstrap.py", names)
                self.assertIn("say-then-publish/scripts/creator_memory.py", names)
                self.assertFalse(any("runtime-data" in name for name in names))
                self.assertFalse(any("backups" in name for name in names))
                self.assertFalse(any(name.endswith("/.env") for name in names))
                combined = b"\n".join(bundle.read(name) for name in names).decode("utf-8")
                for private_value in ("/Users/", "junwenzheng", "Jo6666887", "Jo8888s", "科技米线"):
                    self.assertNotIn(private_value, combined)

    def test_extracted_initializer_keeps_identity_outside_share_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            output_dir = temporary_path / "output"
            subprocess.run(
                [sys.executable, str(BUILDER), "--output-dir", str(output_dir)],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            archive = output_dir / "say-then-publish-skill.zip"
            extracted = temporary_path / "extracted"
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(extracted)
            skill_root = extracted / "say-then-publish"
            config_home = temporary_path / "config"
            content_dir = temporary_path / "content"
            environment = os.environ.copy()
            environment["SAY_THEN_PUBLISH_HOME"] = str(config_home)
            result = subprocess.run(
                [
                    sys.executable,
                    str(skill_root / "scripts" / "bootstrap.py"),
                    "init",
                    "--account-name",
                    "测试创作者",
                    "--content-dir",
                    str(content_dir),
                    "--port",
                    "5189",
                    "--no-start",
                ],
                env=environment,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertIn('"platform": "小红书"', result.stdout)
            installed_profile = content_dir / ".say-then-publish" / "app" / "src" / "user-profile.js"
            self.assertIn("测试创作者", installed_profile.read_text(encoding="utf-8"))
            bundled_profile = skill_root / "assets" / "app" / "src" / "user-profile.js"
            self.assertNotIn("测试创作者", bundled_profile.read_text(encoding="utf-8"))
            self.assertEqual(0o600, (config_home / "install.json").stat().st_mode & 0o777)
            memory_path = config_home / "creator-memory.json"
            self.assertEqual(0o600, memory_path.stat().st_mode & 0o777)
            self.assertIn("测试创作者", memory_path.read_text(encoding="utf-8"))
            self.assertNotIn("测试创作者", (skill_root / "SKILL.md").read_text(encoding="utf-8"))

    def test_start_recovers_existing_application_without_onboarding_questions(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            config_home = temporary_path / "config"
            application = temporary_path / "existing-app"
            (application / "scripts").mkdir(parents=True)
            (application / "src").mkdir()
            for relative in ("server.py", "index.html", "requirements.txt", "scripts/wtp.py", "src/app.js"):
                (application / relative).write_text("# marker\n", encoding="utf-8")
            environment = os.environ.copy()
            environment["SAY_THEN_PUBLISH_HOME"] = str(config_home)
            subprocess.run(
                [
                    sys.executable,
                    str(PUBLIC_SKILL / "scripts" / "creator_memory.py"),
                    "init",
                    "--account-name",
                    "已有创作者",
                ],
                env=environment,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            result = subprocess.run(
                [sys.executable, str(PUBLIC_SKILL / "scripts" / "bootstrap.py"), "status"],
                cwd=application,
                env=environment,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            payload = result.stdout
            self.assertIn('"recoveredExistingApp": true', payload)
            self.assertIn('"installationMode": "existing-app"', payload)
            self.assertIn('"accountName": "已有创作者"', payload)
            install_record = (config_home / "install.json").read_text(encoding="utf-8")
            self.assertIn(str(application), install_record)
            self.assertEqual(0o600, (config_home / "install.json").stat().st_mode & 0o777)

    def test_noninteractive_init_reuses_remembered_account_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            output_dir = temporary_path / "output"
            subprocess.run(
                [sys.executable, str(BUILDER), "--output-dir", str(output_dir)],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            extracted = temporary_path / "extracted"
            with zipfile.ZipFile(output_dir / "say-then-publish-skill.zip") as bundle:
                bundle.extractall(extracted)
            skill_root = extracted / "say-then-publish"
            config_home = temporary_path / "config"
            content_dir = temporary_path / "content"
            environment = os.environ.copy()
            environment["SAY_THEN_PUBLISH_HOME"] = str(config_home)
            subprocess.run(
                [
                    sys.executable,
                    str(skill_root / "scripts" / "creator_memory.py"),
                    "init",
                    "--account-name",
                    "记忆中的名称",
                ],
                env=environment,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(skill_root / "scripts" / "bootstrap.py"),
                    "init",
                    "--content-dir",
                    str(content_dir),
                    "--no-start",
                ],
                env=environment,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertIn('"accountName": "记忆中的名称"', result.stdout)

    def test_creator_memory_refuses_secret_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            environment = os.environ.copy()
            environment["SAY_THEN_PUBLISH_HOME"] = str(Path(temporary) / "memory")
            command = [
                sys.executable,
                str(PUBLIC_SKILL / "scripts" / "creator_memory.py"),
                "remember",
                "--category",
                "device",
                "--key",
                "API Key",
                "--value",
                "do-not-store-this",
            ]
            result = subprocess.run(command, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertEqual(1, result.returncode)
            self.assertIn("拒绝保存", result.stderr)


if __name__ == "__main__":
    unittest.main()

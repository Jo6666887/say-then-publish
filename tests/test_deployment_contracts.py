import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeploymentContractTests(unittest.TestCase):
    def test_systemd_service_is_isolated_from_existing_application(self):
        unit = (ROOT / "deploy/write-then-publish.service").read_text(encoding="utf-8")

        self.assertIn("User=write-then-publish", unit)
        self.assertIn("WorkingDirectory=/opt/write-then-publish/current", unit)
        self.assertIn("StateDirectory=write-then-publish", unit)
        self.assertIn("ProtectSystem=strict", unit)
        self.assertNotIn("ai-pic-demo", unit)
        self.assertNotIn("nginx", unit)

    def test_server_bootstrap_uses_separate_directories_and_service(self):
        script = (ROOT / "deploy/bootstrap-server.sh").read_text(encoding="utf-8")

        self.assertIn('APP_ROOT="/opt/write-then-publish"', script)
        self.assertIn('CONFIG_DIR="/etc/write-then-publish"', script)
        self.assertIn('STATE_DIR="/var/lib/write-then-publish"', script)
        self.assertIn('BUILD_USER="write-then-publish-build"', script)
        self.assertIn("python3 -m venv", script)
        self.assertIn("WTP_TLS_CERT_FILE=", script)
        self.assertIn("WTP_ALLOW_INSECURE_HTTP=1", script)
        self.assertIn('TRANSPORT="${3:-https}"', script)
        self.assertIn("URL=${TRANSPORT}://", script)
        self.assertIn("WTP_BASIC_AUTH_PASSWORD=", script)
        self.assertNotIn("systemctl restart ai-pic-demo", script)
        self.assertNotIn("systemctl stop ai-pic-demo", script)

    def test_release_activation_is_atomic_and_only_restarts_its_own_unit(self):
        script = (ROOT / "deploy/activate-release.sh").read_text(encoding="utf-8")

        self.assertIn('SERVICE_NAME="write-then-publish.service"', script)
        self.assertIn('mv -Tf -- "$NEXT_LINK" "$CURRENT_LINK"', script)
        self.assertIn("flock -n 9", script)
        self.assertIn("部署包完整性校验失败", script)
        self.assertIn("rollback_current", script)
        self.assertIn("不能包含符号链接或硬链接", script)
        self.assertIn("--no-cache-dir", script)
        self.assertIn("runuser -u \"$BUILD_USER\"", script)
        self.assertIn("pre-release-", script)
        self.assertIn('URL_SCHEME="http"', script)
        self.assertIn('CURL_TRANSPORT_ARGS=()', script)
        self.assertNotIn("ai-pic-demo", script)
        self.assertNotIn("git pull", script)

    def test_future_sync_packages_a_clean_exact_commit_without_github_pull(self):
        script = (ROOT / "scripts/deploy-server.zsh").read_text(encoding="utf-8")

        self.assertIn("git -C \"$PROJECT_DIR\" archive", script)
        self.assertIn("status --porcelain", script)
        self.assertIn('DEPLOY_HOST="${WTP_DEPLOY_HOST:-}"', script)
        self.assertIn("grep -Eq '^[A-Za-z0-9._-]+@[A-Za-z0-9.-]+$'", script)
        self.assertIn("scp ", script)
        self.assertNotIn("115.190.212.2", script)
        self.assertNotIn("git pull", script)
        self.assertNotIn(".env ", script)


if __name__ == "__main__":
    unittest.main()

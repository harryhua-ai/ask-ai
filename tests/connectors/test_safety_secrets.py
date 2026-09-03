"""Secrets Technical Safety 测试(S0 / PD-1)。

验收映射:
- A:.env / 私钥 / 凭证 fixture → Technical Safety reject
- B:Admin file_types 显式包含禁入秘密 → 仍 reject(不可绕过)
- C:普通合法配置/模板/公证书 → 不误杀
- D:既有 .hef/.so/.bin 防线保持(test_safety.py 既有用例回归 + 本文件补充)
"""

import pytest

from backend.connectors.registry import SourceConfig
from backend.connectors.safety import (
    KnowledgeRole,
    TechnicalSafetyPolicy,
    secret_content_reason,
    secret_path_reason,
)


def _policy(**cfg) -> TechnicalSafetyPolicy:
    return TechnicalSafetyPolicy(cfg)


# ------------------------------------------------------- A:名字层拒绝


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "app/.env",
        ".env.production",
        ".env.local",
        "deploy/.env.staging",
        "ssh/id_rsa",
        "keys/id_rsa.old",
        "keys/id_ed25519_backup",
        "id_dsa",
        "certs/server.pfx",
        "store/main.jks",
        "app.keystore",
        "vault/db.kdbx",
        "access.htpasswd",
        "ops/server.key",
        ".git-credentials",
        ".netrc",
        "config/secrets.yaml",
        "gcp/credentials.json",
        "secret.properties",
    ],
)
def test_secret_named_paths_rejected(path):
    v = _policy().check_path(path, 100)
    assert not v.safe, path
    assert v.reason == "secret_file", path


def test_putty_private_key_rejected():
    v = _policy().check_path("ops/gateway.ppk", 100)
    assert not v.safe and v.reason == "secret_file"


# ------------------------------------------------------- A:内容层拒绝


@pytest.mark.parametrize(
    "armor",
    [
        "-----BEGIN RSA PRIVATE KEY-----",
        "-----BEGIN OPENSSH PRIVATE KEY-----",
        "-----BEGIN EC PRIVATE KEY-----",
        "-----BEGIN PRIVATE KEY-----",
        "-----BEGIN ENCRYPTED PRIVATE KEY-----",
        "-----BEGIN PGP PRIVATE KEY BLOCK-----",
    ],
)
def test_private_key_armor_rejected_regardless_of_extension(armor):
    body = armor + "\n" + "b3BlbnNzaCBkYXRh" * 40 + "\n-----END RSA PRIVATE KEY-----\n"
    # 扩展名伪装:证书链惯用名 .pem / 文档名 .txt 都必须被内容证据拦下
    for path in ("certs/fullchain.pem", "docs/notes.txt", "noext"):
        v = _policy().check_path(path, len(body))
        if v.safe:
            v = _policy().check_content(body)
        assert not v.safe, (path, armor)
        assert v.reason == "secret_content", (path, armor)


def test_secret_content_reason_helper_machine_readable():
    reason, detail = secret_content_reason(
        "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAAB3NzaC1kc3MAAACB\n"
    )
    assert reason == "secret_content"
    assert "OPENSSH" in detail


# ------------------------------------------------------- B:管理员不可绕过


def test_admin_file_types_cannot_whitelist_secrets(tmp_path):
    """file_types 显式含 .key:白名单放行,技术安全仍拒绝(验收 B)。

    注:.env 是 dotfile(suffix 为空),会被扩展名白名单自然挡下;
    本用例选 `server.key`(suffix 可进白名单)证明 safety 判定先于白名单放行。
    """
    from unittest.mock import MagicMock, patch

    from backend.connectors.github import GitHubConnector

    (tmp_path / "keys").mkdir()
    (tmp_path / "keys" / "server.key").write_text("-----BEGIN PRIVATE KEY-----\n")
    (tmp_path / "readme.md").write_text("# ok\n")
    cfg = SourceConfig(
        id="t-secret",
        type="github",
        product="t",
        enabled=True,
        config={
            "repo_url": "https://github.com/x/y.git",
            "clone_path": str(tmp_path),
            # PD-1:管理员把 .key 显式加入白名单 → 仍不可进入知识库
            "file_types": [".key", ".md"],
        },
        sync_interval="24h",
    )
    conn = GitHubConnector(cfg)
    with patch(
        "backend.connectors.github.subprocess.run",
        return_value=MagicMock(returncode=0, stdout="", stderr=""),
    ):
        docs = list(conn.fetch_all())
    assert [d.metadata["path"] for d in docs] == ["readme.md"]
    assert conn.safety_stats["reasons"].get("secret_file") == 1


def test_policy_config_cannot_disable_secret_check():
    """TechnicalSafetyPolicy 的尺寸/阈值可配,秘密禁列无任何配置开关。"""
    # 构造极端配置(允许的键全部给到):秘密判定不受影响
    p = _policy(review_size_limit=64 * 1024 * 1024, hard_size_ceiling=64 * 1024 * 1024)
    assert p.check_path(".env", 10).safe is False
    assert p.check_path("id_rsa", 10).safe is False


# ------------------------------------------------------- C:不误杀


@pytest.mark.parametrize(
    "path",
    [
        ".env.example",
        "config/.env.sample",
        ".env.template",
        "deploy/.env.dist",
        "env.schema",
        "cfg/app.yaml",
        "config/settings.json",
        "pyproject.toml",
        "docs/secrets-management.md",  # 讲秘密管理的文档(.md 非数据扩展名)
        "src/secrets.py",  # 代码文件(读代码不是读密钥)
        "keys/README.txt",
    ],
)
def test_legitimate_config_and_docs_not_rejected(path):
    assert _policy().check_path(path, 1_000).safe, path


def test_env_template_is_adjacent_not_banned():
    """模板 env:技术安全,角色=SECRETS 推荐排除,管理员确认后可纳入。"""
    a = _policy().admission(".env.example", 200, content="API_KEY=changeme\n")
    assert a.technical_safe
    assert a.knowledge_role == KnowledgeRole.SECRETS.value
    assert a.recommendation == "exclude"


def test_public_certificate_not_rejected():
    """公钥/证书链(nginx fullchain.pem 惯例)不被无依据硬禁。"""
    pem = (
        "-----BEGIN CERTIFICATE-----\nMIIFazCCA1OgAwIBAgIRAIIQz7DSQONZRGPgu2OCiwAw\n"
        "-----END CERTIFICATE-----\n"
    )
    v = _policy().check_path("certs/fullchain.pem", len(pem))
    assert v.safe
    v2 = _policy().check_content(pem)
    assert v2.safe


@pytest.mark.parametrize("name", ["public.key", "keys/public-server.key", "host.pub", "id_rsa.pub"])
def test_public_key_names_not_rejected(name):
    assert secret_path_reason(name) is None, name


def test_generic_yaml_json_toml_not_blanket_banned():
    """PD-1 红线:generic 数据格式不得一刀切(只有 secrets/credentials 惯用名命中)。"""
    for p in ("chart/values.yaml", "manifest/deploy.yaml", "tsconfig.json", "Cargo.toml"):
        assert _policy().check_path(p, 500).safe, p


# ------------------------------------------------------- 角色与推荐一致性


def test_secrets_role_recommended_exclude_and_eligible_false():
    a = _policy().admission("deploy/.env", 50, content="DB_PASS=x\n")
    assert not a.technical_safe
    assert a.technical_reason == "secret_file"
    assert a.knowledge_role == KnowledgeRole.SECRETS.value
    assert a.eligible is False
    assert a.recommendation == "exclude"


def test_pem_content_secret_upgrades_to_unsafe():
    """cert.pem 内藏私钥:名字层放行,内容层拦下(admission 全链)。"""
    body = "-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEII\n-----END EC PRIVATE KEY-----\n"
    a = _policy().admission("certs/fullchain.pem", len(body), content=body)
    assert not a.technical_safe
    assert a.technical_reason == "secret_content"
    assert a.knowledge_role == KnowledgeRole.SECRETS.value


# ------------------------------------------------------- D:既有防线回归


@pytest.mark.parametrize("ext", [".hef", ".so", ".bin", ".onnx", ".elf", ".exe"])
def test_existing_artifact_defense_unchanged(ext):
    assert _policy().check_path(f"m/model{ext}", 10).safe is False
    assert _policy().check_path(f"m/model{ext}", 10).reason == "model_artifact_ext"

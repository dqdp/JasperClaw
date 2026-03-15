from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
IMAGES_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "images.yml"
DEPLOY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-prod.yml"


def test_images_workflow_publishes_platform_db_admin_image() -> None:
    workflow_text = IMAGES_WORKFLOW.read_text(encoding="utf-8")

    assert "service: platform-db" in workflow_text
    assert "image_name: local-assistant-db-admin" in workflow_text
    assert "context: ." in workflow_text
    assert "dockerfile: platform-db/Dockerfile" in workflow_text


def test_images_workflow_uses_repo_root_relative_dockerfiles_for_subdir_contexts() -> None:
    workflow_text = IMAGES_WORKFLOW.read_text(encoding="utf-8")

    assert "service: stt-service" in workflow_text
    assert "context: ./services/stt-service" in workflow_text
    assert "dockerfile: services/stt-service/Dockerfile" in workflow_text
    assert "service: tts-service" in workflow_text
    assert "context: ./services/tts-service" in workflow_text
    assert "dockerfile: services/tts-service/Dockerfile" in workflow_text


def test_deploy_workflow_exports_selected_git_ref_for_rollout_scripts() -> None:
    workflow_text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")

    assert "export APP_VERSION=${{ inputs.app_version }}" in workflow_text
    assert "export DEPLOY_GIT_REF=${{ inputs.app_version }}" in workflow_text

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.media_provenance import write_render_manifest
from app.publishing_quality_gate import PublishingQualityError, require_publishable_provenance


def _fixture(tmp_path: Path, quality_report=None):
    output = tmp_path / "generated_videos" / "clip.mp4"
    output.parent.mkdir()
    output.write_bytes(b"verified-mp4-payload")
    asset = tmp_path / "assets" / "scene.jpg"
    asset.parent.mkdir()
    asset.write_bytes(b"scene")
    manifest = write_render_manifest(
        data_dir=tmp_path, run_id="a" * 32, format_id="shorts", topic="test",
        output_path=output, asset_paths=[asset], quality_report=quality_report,
    )
    return output, manifest


def test_gate_requires_persisted_pass_quality_report(tmp_path):
    output, _ = _fixture(tmp_path)
    with pytest.raises(PublishingQualityError, match="no persisted PASS"):
        require_publishable_provenance(data_dir=tmp_path, output_path=output)


def test_gate_accepts_exact_hash_with_pass_report(tmp_path):
    output, manifest = _fixture(tmp_path, {"verified": True, "resolution": "720x1280"})
    result = require_publishable_provenance(data_dir=tmp_path, output_path=output)
    assert result["status"] == "PASS"
    assert result["output_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert result["manifest_path"] == manifest["manifest_path"]


def test_gate_blocks_changed_mp4_after_quality_pass(tmp_path):
    output, _ = _fixture(tmp_path, {"verified": True})
    output.write_bytes(b"changed-after-audit")
    with pytest.raises(PublishingQualityError, match="no provenance manifest"):
        require_publishable_provenance(data_dir=tmp_path, output_path=output)


def test_gate_blocks_symlink_and_outside_path(tmp_path):
    output, _ = _fixture(tmp_path, {"verified": True})
    alias = tmp_path / "alias.mp4"
    alias.symlink_to(output)
    with pytest.raises(PublishingQualityError, match="unsafe"):
        require_publishable_provenance(data_dir=tmp_path, output_path=alias)
    outside = tmp_path.parent / "outside.mp4"
    outside.write_bytes(b"outside")
    with pytest.raises(PublishingQualityError, match="outside"):
        require_publishable_provenance(data_dir=tmp_path, output_path=outside)


def test_gate_blocks_manifest_quality_report_without_verified_true(tmp_path):
    output, manifest = _fixture(tmp_path, {"verified": False})
    manifest_path = tmp_path / manifest["manifest_path"]
    data = json.loads(manifest_path.read_text())
    data["quality_check"]["verified"] = False
    manifest_path.write_text(json.dumps(data))
    with pytest.raises(PublishingQualityError, match="no persisted PASS"):
        require_publishable_provenance(data_dir=tmp_path, output_path=output)

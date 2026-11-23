"""STEP 24.4.2 — Focused Security Verification Suite for Visual Renderer & Prototype Isolation.

Tests:
1. Native Sandbox Verification: Chrome execution does not use --no-sandbox.
2. Profile Isolation: Dedicated, ephemeral browser profile directory (--user-data-dir) used per render.
3. CSS @import Disallowed: CSS @import rules are blocked and stripped.
4. Meta Refresh & Base Disallowed: Redirects and base tag hijacking are blocked and stripped.
5. External Network Resources Disallowed: http/https/protocol-relative URLs are blocked and stripped.
6. Arbitrary Local Files Disallowed: file://, ../ traversal, and absolute paths are blocked and stripped.
7. Authorized Brand Assets Allowed: jester_logo.svg, favicon.ico, and inline data:image URIs are permitted.
8. Fail-Closed Policy: If security isolation cannot be verified, rendering falls back to generic SVG with is_browser_screenshot=False.
9. Generic SVG Classification: Distinct fallback classification is preserved.
10. Live Native Sandbox Screenshot: Chrome captures screenshots with native sandbox enabled.
"""

import hashlib
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import MagicMock, patch
import pytest

from jester_ai_company.design_concept import (
    AUTHORIZED_BRAND_ASSETS,
    DesignConcept,
    PreviewProvenanceError,
    compute_sha256_text,
    is_authorized_resource_target,
    sanitize_prototype_html,
    validate_preview_provenance,
    validate_untrusted_prototype_html,
)
from jester_ai_company.prototype_renderer import (
    PrototypeRenderResult,
    capture_browser_screenshot,
    compute_file_sha256,
    ensure_authorized_brand_assets,
    find_available_browser,
    render_prototype_previews,
)


CLEAN_PROTOTYPE_HTML = """<!DOCTYPE html>
<html lang="ka">
<head>
    <meta charset="utf-8">
    <title>JESTER Registration</title>
    <style>
        body { margin: 0; background-color: #FAF7F2; font-family: system-ui, sans-serif; }
        .hero { padding: 40px; text-align: center; }
        h1 { color: #222630; font-size: 28px; }
        button { background: #FF7A2F; color: #FFFFFF; border: none; padding: 12px 24px; border-radius: 8px; }
    </style>
</head>
<body>
    <div class="hero">
        <img src="jester_logo.svg" alt="Jester Logo" width="120">
        <h1>შექმენი შენი კოსმიური პროფილი</h1>
        <p>შეიყვანეთ ელფოსტა და პაროლი</p>
        <button>რეგისტრაცია</button>
    </div>
</body>
</html>"""


# -----------------------------------------------------------------------------
# Test 1 & 2: Native Sandbox & Ephemeral User Data Dir Enforced
# -----------------------------------------------------------------------------
def test_1_and_2_native_sandbox_and_ephemeral_user_data_dir():
    """Verify Chrome command excludes --no-sandbox and includes ephemeral --user-data-dir."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_p = Path(tmp_dir)
        fake_browser = tmp_p / "browser.exe"
        fake_browser.write_text("fake binary", encoding="utf-8")
        html_file = tmp_p / "test.html"
        html_file.write_text("<html></html>", encoding="utf-8")
        output_png = tmp_p / "output.png"

        captured_cmds = []

        def mock_subprocess_run(cmd, *args, **kwargs):
            captured_cmds.append(list(cmd))
            output_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)
            res = MagicMock()
            res.returncode = 0
            return res

        with patch("subprocess.run", side_effect=mock_subprocess_run):
            ok = capture_browser_screenshot(
                browser_path=fake_browser,
                html_path=html_file,
                output_png_path=output_png,
                width=1280,
                height=800,
            )
            assert ok is True

        assert len(captured_cmds) == 1
        cmd = captured_cmds[0]

        # 1. Requirement: Remove --no-sandbox
        assert "--no-sandbox" not in cmd, "CRITICAL SECURITY FLAW: --no-sandbox must not be present in browser command!"

        # 2. Requirement: Use isolated temporary browser profiles
        user_data_dirs = [arg for arg in cmd if arg.startswith("--user-data-dir=")]
        assert len(user_data_dirs) == 1, "An isolated --user-data-dir must be provided."
        profile_path = user_data_dirs[0].split("=", 1)[1]
        assert "jester_render_profile_" in profile_path
        # Temporary profile must be cleaned up after execution
        assert not Path(profile_path).exists(), "Temporary browser profile must be cleaned up after capture."

        # Verify other hardening flags
        assert "--disable-javascript" in cmd
        assert "--disable-background-networking" in cmd
        assert "--disable-local-storage" in cmd
        assert "--disable-databases" in cmd


# -----------------------------------------------------------------------------
# Test 3: CSS @import Disallowed & Stripped
# -----------------------------------------------------------------------------
def test_3_css_import_disallowed_and_stripped():
    """Verify CSS @import rules are detected as violations and stripped by sanitizer."""
    evil_html = """<!DOCTYPE html>
<html>
<head>
    <style>
        @import url("https://fonts.googleapis.com/css2?family=Roboto");
        @import 'local_leak.css';
        h1 { color: #FF7A2F; }
    </style>
</head>
<body><h1>ტესტი</h1></body>
</html>"""

    # Validation detects @import
    is_valid, violations = validate_untrusted_prototype_html(evil_html)
    assert is_valid is False
    assert any("@import" in v for v in violations)

    # Sanitizer completely strips @import
    sanitized = sanitize_prototype_html(evil_html)
    assert "@import" not in sanitized
    assert "local_leak.css" not in sanitized
    assert "https://fonts.googleapis.com" not in sanitized

    # Sanitized output is now safe
    is_safe, _ = validate_untrusted_prototype_html(sanitized)
    assert is_safe is True


# -----------------------------------------------------------------------------
# Test 4: Meta Refresh & Base Tags Disallowed & Stripped
# -----------------------------------------------------------------------------
def test_4_meta_refresh_and_base_tags_disallowed():
    """Verify <meta http-equiv='refresh'> and <base> tags are blocked and stripped."""
    evil_html = """<!DOCTYPE html>
<html>
<head>
    <meta http-equiv="refresh" content="0; url=https://evil.com/phish">
    <base href="https://evil.com/">
</head>
<body><h1>ტესტი</h1></body>
</html>"""

    is_valid, violations = validate_untrusted_prototype_html(evil_html)
    assert is_valid is False
    assert any("refresh" in v.lower() for v in violations)
    assert any("base" in v.lower() for v in violations)

    sanitized = sanitize_prototype_html(evil_html)
    assert "refresh" not in sanitized.lower()
    assert "<base" not in sanitized.lower()
    assert "https://evil.com" not in sanitized

    is_safe, _ = validate_untrusted_prototype_html(sanitized)
    assert is_safe is True


# -----------------------------------------------------------------------------
# Test 5: External Network Resources Disallowed & Stripped
# -----------------------------------------------------------------------------
def test_5_external_network_resources_disallowed():
    """Verify external HTTP/HTTPS/protocol-relative resources are blocked and stripped."""
    evil_html = """<!DOCTYPE html>
<html>
<head>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap.css">
    <style>
        .banner { background-image: url("https://tracking.com/pixel.png"); }
        .hero { background: url('//cdn.example.com/asset.jpg'); }
    </style>
</head>
<body>
    <img src="https://external.com/logo.png">
    <video src="http://streaming.com/video.mp4"></video>
</body>
</html>"""

    is_valid, violations = validate_untrusted_prototype_html(evil_html)
    assert is_valid is False
    assert any("external network resource" in v.lower() for v in violations)

    sanitized = sanitize_prototype_html(evil_html)
    assert "https://cdn.jsdelivr.net" not in sanitized
    assert "https://tracking.com" not in sanitized
    assert "//cdn.example.com" not in sanitized
    assert "https://external.com" not in sanitized
    assert "http://streaming.com" not in sanitized


# -----------------------------------------------------------------------------
# Test 6: Arbitrary Local Files & Traversal Disallowed
# -----------------------------------------------------------------------------
def test_6_arbitrary_local_files_disallowed():
    """Verify file:// URIs, ../ traversal, and arbitrary local files are blocked."""
    evil_html = """<!DOCTYPE html>
<html>
<head><title>Attack</title></head>
<body>
    <img src="../passwords.txt">
    <img src="file:///etc/shadow">
    <img src="C:/Windows/System32/drivers/etc/hosts">
    <img src="arbitrary_unapproved.png">
</body>
</html>"""

    is_valid, violations = validate_untrusted_prototype_html(evil_html)
    assert is_valid is False
    assert any("traversal" in v.lower() for v in violations)
    assert any("file://" in v.lower() for v in violations)
    assert any("unauthorized" in v.lower() for v in violations)

    sanitized = sanitize_prototype_html(evil_html)
    assert "../passwords.txt" not in sanitized
    assert "file:///etc/shadow" not in sanitized
    assert "C:/Windows" not in sanitized
    assert "arbitrary_unapproved.png" not in sanitized


# -----------------------------------------------------------------------------
# Test 7: Authorized Brand Assets & Data URIs Allowed
# -----------------------------------------------------------------------------
def test_7_authorized_brand_assets_and_data_uris_allowed():
    """Verify explicitly authorized brand assets and inline data URIs pass validation."""
    data_uri_svg = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg'><circle r='10'/></svg>"
    safe_html = f"""<!DOCTYPE html>
<html>
<head>
    <link rel="icon" href="favicon.ico">
    <style>
        .brand-icon {{ background-image: url("jester_logo.svg"); }}
    </style>
</head>
<body>
    <img src="jester_logo.svg" alt="Jester">
    <img src="JESTER_Logo_Stacked_Outlined.svg" alt="Jester Stacked">
    <img src="{data_uri_svg}" alt="Inline Data">
</body>
</html>"""

    is_valid, violations = validate_untrusted_prototype_html(safe_html)
    assert is_valid is True, f"Expected clean pass but got violations: {violations}"

    # Verify check_resource_ref directly
    ok, _ = is_authorized_resource_target("jester_logo.svg")
    assert ok is True
    ok, _ = is_authorized_resource_target("favicon.ico")
    assert ok is True
    ok, _ = is_authorized_resource_target(data_uri_svg)
    assert ok is True
    ok, _ = is_authorized_resource_target("unauthorized_secret.pdf")
    assert ok is False


# -----------------------------------------------------------------------------
# Test 8: Fail-Closed Policy on Security Violations
# -----------------------------------------------------------------------------
def test_8_fail_closed_policy_on_security_violations():
    """Verify renderer fails closed if security validation fails: fallback to SVG, never claim screenshot."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_dir = Path(tmp_dir)

        # Mock validate_untrusted_prototype_html to simulate an unresolvable isolation failure
        with patch("jester_ai_company.prototype_renderer.validate_untrusted_prototype_html", return_value=(False, ["Critical sandbox isolation failure"])):
            result = render_prototype_previews(
                html_source=CLEAN_PROTOTYPE_HTML,
                output_dir=out_dir,
                concept_id="concept_fail_closed",
                force_svg_fallback=False,
            )

            # Must fail closed:
            assert result.is_browser_screenshot is False
            assert result.rendering_method == "GENERIC_SVG_FALLBACK"
            assert result.desktop_file.name.endswith(".svg")
            assert result.mobile_file.name.endswith(".svg")


# -----------------------------------------------------------------------------
# Test 9: Generic SVG Classification Preserved
# -----------------------------------------------------------------------------
def test_9_generic_svg_classification_preserved():
    """Verify generic SVG preview is distinctly classified and cannot masquerade as screenshot."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_dir = Path(tmp_dir)
        result = render_prototype_previews(
            html_source=CLEAN_PROTOTYPE_HTML,
            output_dir=out_dir,
            concept_id="concept_fallback",
            force_svg_fallback=True,
        )

        assert result.is_browser_screenshot is False
        assert result.rendering_method == "GENERIC_SVG_FALLBACK"

        # Claiming this is a browser screenshot must raise PreviewProvenanceError
        fraudulent_concept = DesignConcept(
            concept_id="concept_fraud",
            name="Fraudulent Concept",
            design_rationale="...",
            ux_specification="...",
            html_prototype=CLEAN_PROTOTYPE_HTML,
            desktop_preview_path=str(result.desktop_file),
            mobile_preview_path=str(result.mobile_file),
            desktop_preview_sha256=result.desktop_sha,
            mobile_preview_sha256=result.mobile_sha,
            rendering_method="HEADLESS_BROWSER_SCREENSHOT",
            is_browser_screenshot=True,  # FRAUD
        )

        with pytest.raises(PreviewProvenanceError):
            validate_preview_provenance(fraudulent_concept)


# -----------------------------------------------------------------------------
# Test 10: Live Headless Chrome Renders with Native Sandbox (No --no-sandbox)
# -----------------------------------------------------------------------------
def test_10_live_headless_chrome_renders_with_native_sandbox():
    """Verify installed Chrome renders real PNG screenshots using native sandbox."""
    browser = find_available_browser()
    if not browser:
        pytest.skip("No local browser installed.")

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_dir = Path(tmp_dir)
        result = render_prototype_previews(
            html_source=CLEAN_PROTOTYPE_HTML,
            output_dir=out_dir,
            concept_id="concept_live_secure",
            browser_path=browser,
            force_svg_fallback=False,
        )

        assert isinstance(result, PrototypeRenderResult)
        assert result.is_browser_screenshot is True
        assert result.rendering_method == "HEADLESS_BROWSER_SCREENSHOT"

        # Check real PNG files created on disk
        assert result.desktop_file.is_file()
        assert result.mobile_file.is_file()
        assert result.desktop_file.stat().st_size > 0
        assert result.mobile_file.stat().st_size > 0

        # Verify PNG magic bytes
        assert result.desktop_file.read_bytes()[:4] == b"\x89PNG"
        assert result.mobile_file.read_bytes()[:4] == b"\x89PNG"

        # Verify brand asset was localized
        logo_file = out_dir / "jester_logo.svg"
        assert logo_file.is_file()
        assert logo_file.stat().st_size > 0

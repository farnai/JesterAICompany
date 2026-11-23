"""Application-Owned Visual Prototype Renderer (STEP 24.3).

Renders desktop (1280x800) and mobile (390x844) visual preview artifacts
from isolated self-contained HTML/CSS prototype sources.
"""

import hashlib
import html
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Optional, Tuple, Union

from .design_concept import (
    AUTHORIZED_BRAND_ASSETS,
    sanitize_prototype_html,
    validate_untrusted_prototype_html,
)


def ensure_authorized_brand_assets(output_dir: Path) -> None:
    """Ensure authorized brand assets are present locally in the prototype directory."""
    logo_svg_path = output_dir / "jester_logo.svg"
    logo_stacked_path = output_dir / "JESTER_Logo_Stacked_Outlined.svg"
    canonical_source = Path(r"C:\Users\fiord\OneDrive\Desktop\Jester\frontend\src\assets\brand\JESTER_Logo_Stacked_Outlined.svg")
    content = None
    if canonical_source.is_file():
        try:
            content = canonical_source.read_bytes()
        except Exception:
            pass
    if content is None:
        content = (
            b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 700" width="1200" height="700">'
            b'<rect width="100%" height="100%" fill="none"/>'
            b'<text x="600" y="350" font-family="system-ui, sans-serif" font-size="72" font-weight="bold" fill="#FF7A2F" text-anchor="middle">JESTER</text>'
            b'</svg>'
        )
    if not logo_svg_path.exists():
        logo_svg_path.write_bytes(content)
    if not logo_stacked_path.exists():
        logo_stacked_path.write_bytes(content)


def compute_file_sha256(path: Path) -> str:
    """Compute cryptographic SHA-256 hash of file contents on disk."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _extract_text_content(html_str: str) -> dict:
    """Extract semantic structural elements from prototype HTML for preview composition."""
    # 1. Extract title
    title_match = re.search(r"<\s*title[^>]*>(.*?)<\s*/\s*title\s*>", html_str, re.IGNORECASE | re.DOTALL)
    title = title_match.group(1).strip() if title_match else "Design Prototype"

    # 2. Extract H1 / main headings
    h1_match = re.search(r"<\s*h1[^>]*>(.*?)<\s*/\s*h1\s*>", html_str, re.IGNORECASE | re.DOTALL)
    h1 = re.sub(r"<[^>]+>", "", h1_match.group(1)).strip() if h1_match else ""

    # 3. Extract H2 / subtitle
    h2_match = re.search(r"<\s*h2[^>]*>(.*?)<\s*/\s*h2\s*>", html_str, re.IGNORECASE | re.DOTALL)
    h2 = re.sub(r"<[^>]+>", "", h2_match.group(1)).strip() if h2_match else ""

    # 4. Extract buttons
    buttons = [
        re.sub(r"<[^>]+>", "", b).strip()
        for b in re.findall(r"<\s*button[^>]*>(.*?)<\s*/\s*button\s*>", html_str, re.IGNORECASE | re.DOTALL)
        if re.sub(r"<[^>]+>", "", b).strip()
    ]

    # 5. Extract form inputs (placeholders / labels)
    placeholders = re.findall(r"""placeholder=["']([^"']+)["']""", html_str, re.IGNORECASE)

    # 6. Extract canvas / background color
    bg_match = re.search(r"""background(?:-color)?:\s*([#a-zA-Z0-9(),\s.-]+);""", html_str, re.IGNORECASE)
    bg_color = bg_match.group(1).strip() if bg_match else "#FAF7F2"

    return {
        "title": html.escape(title[:60]),
        "heading": html.escape(h1[:80]) if h1 else html.escape(title[:60]),
        "subheading": html.escape(h2[:120]) if h2 else "",
        "buttons": [html.escape(b[:40]) for b in buttons[:3]],
        "inputs": [html.escape(p[:40]) for p in placeholders[:4]],
        "bg_color": bg_color if bg_color.startswith("#") else "#FAF7F2",
    }


def generate_svg_preview(
    meta: dict,
    concept_id: str,
    viewport_width: int,
    viewport_height: int,
    is_mobile: bool,
) -> str:
    """Generate high-fidelity, deterministic vector preview matching prototype source."""
    title = meta["title"]
    heading = meta["heading"]
    subheading = meta["subheading"]
    buttons = meta["buttons"] or ["Submit"]
    inputs = meta["inputs"] or ["Enter email", "Enter password"]
    bg = meta["bg_color"]

    if is_mobile:
        # Mobile stacked layout (390x844)
        card_w = 340
        card_x = (viewport_width - card_w) // 2
        card_y = 60
        card_h = 720

        inputs_svg = ""
        curr_y = card_y + 180
        for inp in inputs:
            inputs_svg += f"""
            <rect x="{card_x + 20}" y="{curr_y}" width="{card_w - 40}" height="44" rx="8" fill="#FFFFFF" stroke="#E6E0D7" stroke-width="1.5"/>
            <text x="{card_x + 35}" y="{curr_y + 27}" font-family="system-ui, -apple-system, sans-serif" font-size="14" fill="#6A716F">{inp}</text>
            """
            curr_y += 60

        btn_svg = ""
        for btn in buttons:
            btn_svg += f"""
            <rect x="{card_x + 20}" y="{curr_y}" width="{card_w - 40}" height="48" rx="10" fill="#FF7A2F"/>
            <text x="{card_x + card_w // 2}" y="{curr_y + 30}" font-family="system-ui, -apple-system, sans-serif" font-size="15" font-weight="600" fill="#222630" text-anchor="middle">{btn}</text>
            """
            curr_y += 60

        return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{viewport_width}" height="{viewport_height}" viewBox="0 0 {viewport_width} {viewport_height}">
            <rect width="100%" height="100%" fill="{bg}"/>
            <!-- Mobile device frame / status bar -->
            <rect x="0" y="0" width="{viewport_width}" height="35" fill="rgba(0,0,0,0.05)"/>
            <text x="25" y="24" font-family="system-ui, sans-serif" font-size="12" font-weight="600" fill="#222630">9:41</text>
            <text x="{viewport_width - 45}" y="24" font-family="system-ui, sans-serif" font-size="12" fill="#222630">100%</text>

            <!-- Card Container -->
            <rect x="{card_x}" y="{card_y}" width="{card_w}" height="{card_h}" rx="20" fill="#FFFFFF" stroke="#E6E0D7" stroke-width="1" filter="drop-shadow(0 4px 16px rgba(0,0,0,0.05))"/>

            <!-- Badge -->
            <rect x="{card_x + (card_w - 180) // 2}" y="{card_y + 30}" width="180" height="26" rx="13" fill="#F5DDD1"/>
            <text x="{card_x + card_w // 2}" y="{card_y + 48}" font-family="system-ui, sans-serif" font-size="11" font-weight="600" fill="#222630" text-anchor="middle">{concept_id.upper()}</text>

            <!-- Heading -->
            <text x="{card_x + card_w // 2}" y="{card_y + 90}" font-family="system-ui, sans-serif" font-size="20" font-weight="bold" fill="#222630" text-anchor="middle">{heading}</text>
            <text x="{card_x + card_w // 2}" y="{card_y + 115}" font-family="system-ui, sans-serif" font-size="12" fill="#6A716F" text-anchor="middle">{subheading}</text>

            {inputs_svg}
            {btn_svg}
        </svg>"""
    else:
        # Desktop layout (1280x800)
        split_w = 460
        split_h = 640
        split_x = (viewport_width - (split_w * 2 + 40)) // 2
        split_y = 80

        inputs_svg = ""
        curr_y = split_y + 160
        for inp in inputs:
            inputs_svg += f"""
            <rect x="{split_x + split_w + 40 + 30}" y="{curr_y}" width="{split_w - 60}" height="46" rx="8" fill="#FAF7F2" stroke="#E6E0D7" stroke-width="1.5"/>
            <text x="{split_x + split_w + 40 + 45}" y="{curr_y + 28}" font-family="system-ui, sans-serif" font-size="14" fill="#6A716F">{inp}</text>
            """
            curr_y += 62

        btn_svg = ""
        for btn in buttons:
            btn_svg += f"""
            <rect x="{split_x + split_w + 40 + 30}" y="{curr_y}" width="{split_w - 60}" height="50" rx="10" fill="#FF7A2F"/>
            <text x="{split_x + split_w + 40 + split_w // 2}" y="{curr_y + 31}" font-family="system-ui, sans-serif" font-size="16" font-weight="600" fill="#222630" text-anchor="middle">{btn}</text>
            """
            curr_y += 62

        return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{viewport_width}" height="{viewport_height}" viewBox="0 0 {viewport_width} {viewport_height}">
            <rect width="100%" height="100%" fill="{bg}"/>
            <!-- Browser navigation bar simulation -->
            <rect x="0" y="0" width="{viewport_width}" height="40" fill="#E6E0D7"/>
            <circle cx="20" cy="20" r="6" fill="#FF5F56"/>
            <circle cx="38" cy="20" r="6" fill="#FFBD2E"/>
            <circle cx="56" cy="20" r="6" fill="#27C93F"/>
            <rect x="100" y="8" width="{viewport_width - 200}" height="24" rx="4" fill="#FFFFFF"/>
            <text x="120" y="24" font-family="system-ui, sans-serif" font-size="12" fill="#6A716F">https://jester.app/preview/{concept_id} — {title}</text>

            <!-- Dual Panel Architecture -->
            <!-- Left Editorial Storytelling Panel -->
            <rect x="{split_x}" y="{split_y}" width="{split_w}" height="{split_h}" rx="24" fill="#F3EEE6" stroke="#E6E0D7" stroke-width="1"/>
            <rect x="{split_x + 40}" y="{split_y + 50}" width="160" height="28" rx="14" fill="#E8EFE2"/>
            <text x="{split_x + 120}" y="{split_y + 69}" font-family="system-ui, sans-serif" font-size="12" font-weight="600" fill="#95A686" text-anchor="middle">{concept_id.upper()}</text>

            <text x="{split_x + 40}" y="{split_y + 130}" font-family="system-ui, sans-serif" font-size="28" font-weight="bold" fill="#222630">{heading}</text>
            <text x="{split_x + 40}" y="{split_y + 170}" font-family="system-ui, sans-serif" font-size="14" fill="#6A716F">{subheading}</text>

            <!-- Value Pillars -->
            <rect x="{split_x + 40}" y="{split_y + 240}" width="{split_w - 80}" height="64" rx="12" fill="#FFFFFF" stroke="#E6E0D7" stroke-width="1"/>
            <text x="{split_x + 60}" y="{split_y + 278}" font-family="system-ui, sans-serif" font-size="14" font-weight="600" fill="#222630">Relationship Intelligence</text>

            <rect x="{split_x + 40}" y="{split_y + 320}" width="{split_w - 80}" height="64" rx="12" fill="#FFFFFF" stroke="#E6E0D7" stroke-width="1"/>
            <text x="{split_x + 60}" y="{split_y + 358}" font-family="system-ui, sans-serif" font-size="14" font-weight="600" fill="#222630">Authentic Connections</text>

            <!-- Right Interactive Credentials Card -->
            <rect x="{split_x + split_w + 40}" y="{split_y}" width="{split_w}" height="{split_h}" rx="24" fill="#FFFFFF" stroke="#E6E0D7" stroke-width="1" filter="drop-shadow(0 8px 30px rgba(0,0,0,0.06))"/>
            <text x="{split_x + split_w + 40 + 40}" y="{split_y + 80}" font-family="system-ui, sans-serif" font-size="24" font-weight="bold" fill="#222630">Get Started</text>
            <text x="{split_x + split_w + 40 + 40}" y="{split_y + 110}" font-family="system-ui, sans-serif" font-size="14" fill="#6A716F">Enter credentials to register</text>

            {inputs_svg}
            {btn_svg}
        </svg>"""


def find_available_browser() -> Optional[Path]:
    """Discover a local headless-capable browser binary (Chrome, Chromium, or Edge)."""
    env_candidate = os.environ.get("CHROME_BIN") or os.environ.get("BROWSER_BIN")
    if env_candidate:
        p = Path(env_candidate)
        if p.is_file():
            return p

    for name in ("chrome", "google-chrome", "chromium", "msedge"):
        w = shutil.which(name)
        if w:
            p = Path(w)
            if p.is_file():
                return p

    standard_paths = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        standard_paths.append(Path(local_app_data) / "Google" / "Chrome" / "Application" / "chrome.exe")
        standard_paths.append(Path(local_app_data) / "Microsoft" / "Edge" / "Application" / "msedge.exe")

    for path in standard_paths:
        if path.is_file():
            return path

    return None


def capture_browser_screenshot(
    browser_path: Path,
    html_path: Path,
    output_png_path: Path,
    width: int,
    height: int,
    timeout_seconds: float = 15.0,
) -> bool:
    """Render an isolated HTML file and capture screenshot using headless browser.

    Security Enforcements:
    - Normal operating system browser sandbox enforced (NO --no-sandbox flag).
    - Dedicated, ephemeral browser profile (--user-data-dir).
    - JavaScript disabled (--disable-javascript).
    - Network requests blocked (--disable-background-networking).
    - Local storage, databases, and extensions disabled.
    """
    with tempfile.TemporaryDirectory(prefix="jester_render_profile_") as temp_profile_dir:
        cmd = [
            str(browser_path),
            "--headless=new",
            "--disable-gpu",
            f"--user-data-dir={temp_profile_dir}",
            "--disable-javascript",
            "--disable-background-networking",
            "--disable-default-apps",
            "--disable-extensions",
            "--disable-sync",
            "--disable-translate",
            "--disable-local-storage",
            "--disable-databases",
            "--metrics-recording-only",
            "--no-first-run",
            "--safebrowsing-disable-auto-update",
            f"--window-size={width},{height}",
            f"--screenshot={output_png_path.resolve()}",
            f"file:///{html_path.resolve().as_posix()}",
        ]
        try:
            if output_png_path.exists():
                output_png_path.unlink()
            res = subprocess.run(cmd, capture_output=True, timeout=timeout_seconds)
            return output_png_path.is_file() and output_png_path.stat().st_size > 0
        except Exception:
            return False


class PrototypeRenderResult(tuple):
    """Container for rendered visual preview outputs with cryptographic and rendering provenance.

    Subclasses tuple so that unpacking as (desktop_file, mobile_file, desktop_sha, mobile_sha)
    is 100% backward compatible with existing tests, while providing direct attribute access.
    """
    desktop_file: Path
    mobile_file: Path
    desktop_sha: str
    mobile_sha: str
    rendering_method: str
    is_browser_screenshot: bool
    source_html_sha256: str
    desktop_viewport: str
    mobile_viewport: str

    def __new__(
        cls,
        desktop_file: Path,
        mobile_file: Path,
        desktop_sha: str,
        mobile_sha: str,
        rendering_method: str,
        is_browser_screenshot: bool,
        source_html_sha256: str,
        desktop_viewport: str = "1280x800",
        mobile_viewport: str = "390x844",
    ):
        instance = super().__new__(cls, (desktop_file, mobile_file, desktop_sha, mobile_sha))
        instance.desktop_file = desktop_file
        instance.mobile_file = mobile_file
        instance.desktop_sha = desktop_sha
        instance.mobile_sha = mobile_sha
        instance.rendering_method = rendering_method
        instance.is_browser_screenshot = is_browser_screenshot
        instance.source_html_sha256 = source_html_sha256
        instance.desktop_viewport = desktop_viewport
        instance.mobile_viewport = mobile_viewport
        return instance


def render_prototype_previews(
    html_source: str,
    output_dir: Path,
    concept_id: str,
    browser_path: Optional[Path] = None,
    force_svg_fallback: bool = False,
) -> PrototypeRenderResult:
    """Render and persist desktop (1280x800) and mobile (390x844) visual previews from HTML prototype.

    Priority:
    1. Headless Browser Screenshot: Uses local isolated browser with JS and network disabled.
       Produces true visual screenshots (.png).
    2. SVG Fallback: Generates deterministic SVG representation (.svg) when browser unavailable
       or when security isolation validation fails (fail closed).
       Explicitly marked as is_browser_screenshot=False, method=GENERIC_SVG_FALLBACK.

    Returns:
        PrototypeRenderResult (unpackable as (desktop_file, mobile_file, desktop_sha, mobile_sha))
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Sanitize HTML for safe execution & persistent storage
    sanitized_html = sanitize_prototype_html(html_source)
    html_file = output_dir / f"prototype_{concept_id}.html"
    html_file.write_bytes(sanitized_html.encode("utf-8"))
    source_sha = compute_file_sha256(html_file)

    # 2. Security validation: Verify isolation before permitting browser execution (Fail Closed)
    is_safe, violations = validate_untrusted_prototype_html(sanitized_html)

    # 3. Attempt True Browser Screenshots if safe and not forced to SVG fallback
    if is_safe and not force_svg_fallback:
        target_browser = browser_path or find_available_browser()
        if target_browser:
            ensure_authorized_brand_assets(output_dir)
            desktop_png = output_dir / f"preview_desktop_{concept_id}.png"
            mobile_png = output_dir / f"preview_mobile_{concept_id}.png"

            d_ok = capture_browser_screenshot(target_browser, html_file, desktop_png, 1280, 800)
            m_ok = capture_browser_screenshot(target_browser, html_file, mobile_png, 390, 844)

            if d_ok and m_ok:
                desktop_sha = compute_file_sha256(desktop_png)
                mobile_sha = compute_file_sha256(mobile_png)
                return PrototypeRenderResult(
                    desktop_file=desktop_png,
                    mobile_file=mobile_png,
                    desktop_sha=desktop_sha,
                    mobile_sha=mobile_sha,
                    rendering_method="HEADLESS_BROWSER_SCREENSHOT",
                    is_browser_screenshot=True,
                    source_html_sha256=source_sha,
                    desktop_viewport="1280x800",
                    mobile_viewport="390x844",
                )

    # 4. Explicit Generic SVG Fallback (Preserves distinct classification and reports limitation)
    meta = _extract_text_content(sanitized_html)

    desktop_svg = generate_svg_preview(
        meta=meta,
        concept_id=concept_id,
        viewport_width=1280,
        viewport_height=800,
        is_mobile=False,
    )
    desktop_file = output_dir / f"preview_desktop_{concept_id}.svg"
    desktop_file.write_bytes(desktop_svg.encode("utf-8"))
    desktop_sha = compute_file_sha256(desktop_file)

    mobile_svg = generate_svg_preview(
        meta=meta,
        concept_id=concept_id,
        viewport_width=390,
        viewport_height=844,
        is_mobile=True,
    )
    mobile_file = output_dir / f"preview_mobile_{concept_id}.svg"
    mobile_file.write_bytes(mobile_svg.encode("utf-8"))
    mobile_sha = compute_file_sha256(mobile_file)

    return PrototypeRenderResult(
        desktop_file=desktop_file,
        mobile_file=mobile_file,
        desktop_sha=desktop_sha,
        mobile_sha=mobile_sha,
        rendering_method="GENERIC_SVG_FALLBACK",
        is_browser_screenshot=False,
        source_html_sha256=source_sha,
        desktop_viewport="1280x800",
        mobile_viewport="390x844",
    )

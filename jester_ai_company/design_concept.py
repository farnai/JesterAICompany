"""Visual Prototyping & Design Concept Domain Models (STEP 24.3).

Provides typed representations for visual UX design concepts, self-contained HTML/CSS
prototypes, untrusted HTML sanitization and safety enforcement, and multi-concept
proposal packages for Founder Review.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple


def _utc_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def compute_sha256_text(text: str) -> str:
    """Compute deterministic SHA-256 hash of UTF-8 encoded text string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# -----------------------------------------------------------------------------
# Untrusted HTML Security Validation & Sanitization (Phase A Security Hardening)
# -----------------------------------------------------------------------------

AUTHORIZED_BRAND_ASSETS: frozenset = frozenset({
    "jester_logo.svg",
    "logo.svg",
    "jester-symbol.svg",
    "carrot_logo.svg",
    "favicon.ico",
    "jester_logo_stacked_outlined.svg",
    "jester_hat_icon.eps",
    "hero.png",
})

SCRIPT_PATTERN = re.compile(r"<\s*script[^>]*>", re.IGNORECASE)
SCRIPT_BLOCK_PATTERN = re.compile(r"<\s*script[^>]*>.*?<\s*/\s*script\s*>", re.IGNORECASE | re.DOTALL)
INLINE_JS_PATTERN = re.compile(r"\bon[a-z]+\s*=", re.IGNORECASE)
JAVASCRIPT_URI_PATTERN = re.compile(r"""(?:href|src|action|formaction)\s*=\s*['"]?\s*javascript:""", re.IGNORECASE)
EMBED_TAG_PATTERN = re.compile(r"<\s*(?:iframe|embed|object|applet)\b", re.IGNORECASE)
CSS_IMPORT_PATTERN = re.compile(r"""@import\s+(?:url\s*\([^)]*\)|['"][^'"]*['"])""", re.IGNORECASE)
META_REFRESH_PATTERN = re.compile(r"""<\s*meta\b[^>]*http-equiv\s*=\s*['"]?refresh['"]?""", re.IGNORECASE)
BASE_TAG_PATTERN = re.compile(r"<\s*base\b", re.IGNORECASE)
EXTERNAL_RESOURCE_ANY_PATTERN = re.compile(r"""(?:href|src|action|poster|data)\s*=\s*['"]?\s*(?:https?:|//)""", re.IGNORECASE)
EXTERNAL_URL_IN_CSS_PATTERN = re.compile(r"""url\s*\(\s*['"]?\s*(?:https?:|//)""", re.IGNORECASE)
PATH_TRAVERSAL_PATTERN = re.compile(r"""(?:(?:src|poster)\s*=\s*['"]?|url\s*\(\s*['"]?|<link\b[^>]*href\s*=\s*['"]?)[^'")]*(?:\.\./|\.\.\\)""", re.IGNORECASE)
FILE_URI_PATTERN = re.compile(r"""(?:(?:href|src|action|poster)\s*=\s*['"]?|url\s*\(\s*['"]?)\s*file:""", re.IGNORECASE)
ABSOLUTE_LOCAL_PATH_PATTERN = re.compile(r"""(?:(?:src|poster)\s*=\s*['"]?|url\s*\(\s*['"]?|<link\b[^>]*href\s*=\s*['"]?)(?:[a-zA-Z]:|[\\/]{1,2}[a-zA-Z0-9_-]+)""", re.IGNORECASE)

RESOURCE_REF_PATTERN = re.compile(
    r"""(?:(?:src|poster)\s*=\s*['"]([^'"]+)['"]|url\s*\(\s*['"]?([^'")]+)['"]?\s*\)|<link\b[^>]*href\s*=\s*['"]([^'"]+)['"])""",
    re.IGNORECASE,
)


def is_authorized_resource_target(target: str) -> Tuple[bool, str]:
    """Check whether a referenced resource target is strictly authorized.

    Permits:
    - Empty or anchor fragments (#)
    - Self-contained data URIs (data:image/svg+xml;..., data:image/png;...)
    - Explicitly whitelisted local brand assets (e.g. jester_logo.svg)

    Forbids:
    - External network URIs (http:, https:, //)
    - Local file scheme URIs (file:)
    - Path traversal (../)
    - Absolute system paths (/etc, C:\\)
    - Arbitrary local files not in AUTHORIZED_BRAND_ASSETS
    """
    cleaned = target.strip()
    if not cleaned or cleaned.startswith("#") or cleaned.startswith("data:image/"):
        return True, "allowed self-contained/data"
    if re.search(r"^(?:https?:|//|file:)", cleaned, re.IGNORECASE):
        return False, "external or file URI"
    if ".." in cleaned or cleaned.startswith("/") or cleaned.startswith("\\") or re.match(r"^[a-zA-Z]:", cleaned):
        return False, "path traversal or absolute path"
    norm_name = cleaned.lower().lstrip("./")
    if norm_name in AUTHORIZED_BRAND_ASSETS:
        return True, "authorized brand asset"
    return False, f"unauthorized local file: {cleaned}"


def validate_untrusted_prototype_html(html_str: str) -> Tuple[bool, List[str]]:
    """Validate untrusted prototype HTML against strict security constraints.

    Enforces Phase A Security Hardening:
    1. Zero arbitrary JavaScript execution: no <script> tags or blocks.
    2. Zero inline event handlers (onload, onclick, onerror, etc.).
    3. Zero javascript: URI schemes.
    4. Zero dangerous embedded tags (<iframe, <embed, <object, <applet).
    5. Zero external network dependencies (no http://, https://, or // resources).
    6. Zero local filesystem access (no file:// URIs, no absolute paths, no ../ traversal).
    7. Zero CSS @import rules (prevents CSS-based exfiltration and remote fetching).
    8. Zero redirects or base URL manipulation (<meta http-equiv="refresh">, <base>).
    9. Allow only explicitly authorized local brand assets or inline data URIs.
    """
    if not html_str or not isinstance(html_str, str):
        return False, ["HTML content is empty or not a string."]

    violations: List[str] = []

    if SCRIPT_PATTERN.search(html_str):
        violations.append("Executable <script> tag detected.")

    if INLINE_JS_PATTERN.search(html_str):
        violations.append("Inline JavaScript event handler detected (e.g. onload, onclick).")

    if JAVASCRIPT_URI_PATTERN.search(html_str):
        violations.append("javascript: URI scheme detected.")

    if EMBED_TAG_PATTERN.search(html_str):
        violations.append("Dangerous embed tag (<iframe, <embed, <object) detected.")

    if CSS_IMPORT_PATTERN.search(html_str):
        violations.append("CSS @import rule detected (external/local stylesheet loading forbidden).")

    if META_REFRESH_PATTERN.search(html_str):
        violations.append("Meta refresh redirect tag detected.")

    if BASE_TAG_PATTERN.search(html_str):
        violations.append("Base URL tag (<base>) detected.")

    if EXTERNAL_RESOURCE_ANY_PATTERN.search(html_str) or EXTERNAL_URL_IN_CSS_PATTERN.search(html_str):
        violations.append("External network resource dependency detected (http/https).")

    if FILE_URI_PATTERN.search(html_str):
        violations.append("Local filesystem 'file://' URI detected.")

    if PATH_TRAVERSAL_PATTERN.search(html_str):
        violations.append("Path traversal ('../' or '..\\') detected.")

    if ABSOLUTE_LOCAL_PATH_PATTERN.search(html_str):
        violations.append("Absolute local file path detected.")

    # Validate all referenced resource targets against the authorized brand asset whitelist
    for match in RESOURCE_REF_PATTERN.finditer(html_str):
        target = match.group(1) or match.group(2) or match.group(3)
        if target:
            is_auth, reason = is_authorized_resource_target(target)
            if not is_auth:
                violations.append(f"Unauthorized resource target reference: {reason}")

    return len(violations) == 0, violations


def sanitize_prototype_html(html_str: str) -> str:
    """Sanitize prototype HTML by stripping active scripting, external resources, and unauthorized local files.

    Produces a self-contained, safe HTML prototype suitable for isolated browser rendering.
    """
    if not html_str or not isinstance(html_str, str):
        return ""

    sanitized = html_str

    # 1. Strip script blocks and tags
    sanitized = SCRIPT_BLOCK_PATTERN.sub("", sanitized)
    sanitized = SCRIPT_PATTERN.sub("", sanitized)
    sanitized = re.sub(r"<\s*/\s*script\s*>", "", sanitized, flags=re.IGNORECASE)

    # 2. Strip inline event handlers
    sanitized = INLINE_JS_PATTERN.sub("data-disabled-event=", sanitized)

    # 3. Strip javascript: URIs
    sanitized = re.sub(
        r"""(href|src|action|formaction)\s*=\s*['"]?\s*javascript:[^'"]*['"]?""",
        r'\1="#"',
        sanitized,
        flags=re.IGNORECASE,
    )

    # 4. Strip iframe/embed/object tags
    sanitized = re.sub(
        r"<\s*(?:iframe|embed|object|applet)\b[^>]*>.*?<\s*/\s*(?:iframe|embed|object|applet)\s*>",
        "",
        sanitized,
        flags=re.IGNORECASE | re.DOTALL,
    )
    sanitized = re.sub(r"<\s*(?:iframe|embed|object|applet)\b[^>]*>", "", sanitized, flags=re.IGNORECASE)

    # 5. Strip meta refresh and base tags
    sanitized = re.sub(r"""<\s*meta\b[^>]*http-equiv\s*=\s*['"]?refresh['"]?[^>]*>""", "", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"<\s*base\b[^>]*>", "", sanitized, flags=re.IGNORECASE)

    # 6. Strip CSS @import rules
    sanitized = re.sub(r"""@import\s+(?:url\s*\([^)]*\)|['"][^'"]*['"]);?""", "", sanitized, flags=re.IGNORECASE)

    # 7. Sanitize <link> tags (allow only non-stylesheet authorized brand assets like favicon.ico)
    def link_repl(match):
        tag = match.group(0)
        m = re.search(r"""href\s*=\s*['"]([^'"]+)['"]""", tag, re.IGNORECASE)
        if m:
            target = m.group(1).strip()
            ok, _ = is_authorized_resource_target(target)
            if ok and "stylesheet" not in tag.lower():
                return tag
        return ""

    sanitized = re.sub(r"<\s*link\b[^>]*>", link_repl, sanitized, flags=re.IGNORECASE)

    # 8. Sanitize src / poster attributes: enforce authorized brand assets or data:image URIs
    def src_repl(match):
        attr = match.group(1)
        val = match.group(2).strip()
        ok, _ = is_authorized_resource_target(val)
        if ok:
            return f'{attr}="{val}"'
        return f'{attr}=""'

    sanitized = re.sub(r"""\b(src|poster)\s*=\s*['"]([^'"]+)['"]""", src_repl, sanitized, flags=re.IGNORECASE)

    # 9. Sanitize CSS url(...) references
    def url_repl(match):
        val = match.group(1).strip()
        ok, _ = is_authorized_resource_target(val)
        if ok:
            return f'url("{val}")'
        return 'url("")'

    sanitized = re.sub(r"""url\s*\(\s*['"]?([^'")]+)['"]?\s*\)""", url_repl, sanitized, flags=re.IGNORECASE)

    return sanitized


# -----------------------------------------------------------------------------
# Design Concept & Proposal Package Domain Models
# -----------------------------------------------------------------------------

class PreviewProvenanceError(Exception):
    """Raised when preview provenance constraints are violated (e.g. SVG labeled as screenshot)."""
    pass


class TamperedPrototypeError(Exception):
    """Raised when prototype content or preview artifacts do not match recorded cryptographic SHA-256."""
    pass


@dataclass
class DesignConcept:
    """Represents a discrete visual design proposal produced by UX."""

    concept_id: str
    name: str
    design_rationale: str
    ux_specification: str
    html_prototype: str
    desktop_preview_path: Optional[str] = None
    mobile_preview_path: Optional[str] = None
    product_references: List[str] = field(default_factory=list)
    known_limitations: List[str] = field(default_factory=list)
    html_sha256: str = ""
    spec_sha256: str = ""
    desktop_preview_sha256: Optional[str] = None
    mobile_preview_sha256: Optional[str] = None
    rendering_method: str = "GENERIC_SVG_FALLBACK"  # "HEADLESS_BROWSER_SCREENSHOT" | "GENERIC_SVG_FALLBACK"
    is_browser_screenshot: bool = False
    source_html_sha256: str = ""
    desktop_viewport: str = "1280x800"
    mobile_viewport: str = "390x844"

    def __post_init__(self):
        if not self.html_sha256 and self.html_prototype:
            self.html_sha256 = compute_sha256_text(self.html_prototype)
        if not self.spec_sha256 and self.ux_specification:
            self.spec_sha256 = compute_sha256_text(self.ux_specification)
        if not self.source_html_sha256:
            self.source_html_sha256 = self.html_sha256

    def compute_hashes(self) -> None:
        """Compute and persist cryptographic SHA-256 hashes of text payloads."""
        self.html_sha256 = compute_sha256_text(self.html_prototype)
        self.spec_sha256 = compute_sha256_text(self.ux_specification)
        self.source_html_sha256 = self.html_sha256

    def to_dict(self) -> Dict[str, Any]:
        """Serialize design concept to dictionary."""
        return {
            "concept_id": self.concept_id,
            "name": self.name,
            "design_rationale": self.design_rationale,
            "ux_specification": self.ux_specification,
            "html_prototype": self.html_prototype,
            "desktop_preview_path": self.desktop_preview_path,
            "mobile_preview_path": self.mobile_preview_path,
            "product_references": list(self.product_references),
            "known_limitations": list(self.known_limitations),
            "html_sha256": self.html_sha256,
            "spec_sha256": self.spec_sha256,
            "desktop_preview_sha256": self.desktop_preview_sha256,
            "mobile_preview_sha256": self.mobile_preview_sha256,
            "rendering_method": self.rendering_method,
            "is_browser_screenshot": self.is_browser_screenshot,
            "source_html_sha256": self.source_html_sha256,
            "desktop_viewport": self.desktop_viewport,
            "mobile_viewport": self.mobile_viewport,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DesignConcept":
        """Deserialize design concept from dictionary."""
        return cls(
            concept_id=str(data["concept_id"]).strip(),
            name=str(data.get("name") or data["concept_id"]).strip(),
            design_rationale=str(data.get("design_rationale", "")).strip(),
            ux_specification=str(data.get("ux_specification", "")).strip(),
            html_prototype=str(data.get("html_prototype", "")),
            desktop_preview_path=data.get("desktop_preview_path"),
            mobile_preview_path=data.get("mobile_preview_path"),
            product_references=list(data.get("product_references", [])),
            known_limitations=list(data.get("known_limitations", [])),
            html_sha256=str(data.get("html_sha256", "")),
            spec_sha256=str(data.get("spec_sha256", "")),
            desktop_preview_sha256=data.get("desktop_preview_sha256"),
            mobile_preview_sha256=data.get("mobile_preview_sha256"),
            rendering_method=str(data.get("rendering_method", "GENERIC_SVG_FALLBACK")),
            is_browser_screenshot=bool(data.get("is_browser_screenshot", False)),
            source_html_sha256=str(data.get("source_html_sha256", data.get("html_sha256", ""))),
            desktop_viewport=str(data.get("desktop_viewport", "1280x800")),
            mobile_viewport=str(data.get("mobile_viewport", "390x844")),
        )


def validate_preview_provenance(concept: DesignConcept, base_dir: Optional[Any] = None) -> None:
    """Validate visual preview provenance and prototype cryptographic integrity.

    Enforces:
    1. A generic SVG template cannot be labeled as a browser screenshot.
    2. Real browser screenshot previews cannot point to SVG template paths.
    3. If base_dir is supplied, prototype HTML and preview files on disk must match recorded SHA-256.
    4. Tampered prototype or preview content immediately invalidates approval or verification.
    """
    from pathlib import Path

    # 1. Enforce fidelity truth: SVG cannot be labeled as a browser screenshot
    if concept.is_browser_screenshot:
        if concept.rendering_method == "GENERIC_SVG_FALLBACK" or not concept.rendering_method:
            raise PreviewProvenanceError("A generic SVG template cannot be labeled as a browser screenshot.")
        if concept.desktop_preview_path and concept.desktop_preview_path.lower().endswith(".svg"):
            raise PreviewProvenanceError("A generic SVG template cannot be labeled as a browser screenshot.")
        if concept.mobile_preview_path and concept.mobile_preview_path.lower().endswith(".svg"):
            raise PreviewProvenanceError("A generic SVG template cannot be labeled as a browser screenshot.")
    else:
        if concept.rendering_method == "HEADLESS_BROWSER_SCREENSHOT":
            raise PreviewProvenanceError("Preview marked as non-browser-screenshot cannot have HEADLESS_BROWSER_SCREENSHOT rendering method.")

    # 2. Check source HTML hash integrity
    if concept.source_html_sha256 and concept.html_sha256 and concept.source_html_sha256 != concept.html_sha256:
        raise TamperedPrototypeError(
            f"Tampered prototype source hash for concept '{concept.concept_id}': "
            f"source_html_sha256 '{concept.source_html_sha256}' != html_sha256 '{concept.html_sha256}'."
        )

    # 3. Check disk files if base_dir provided
    if base_dir:
        base_p = Path(base_dir)
        # Check prototype HTML on disk
        proto_p = base_p / f"prototype_{concept.concept_id}.html"
        if not proto_p.is_file():
            # Try checking relative path if available
            cand = base_p / (concept.concept_id + ".html")
            if cand.is_file():
                proto_p = cand
        if proto_p.is_file() and concept.html_sha256:
            actual_sha = hashlib.sha256(proto_p.read_bytes()).hexdigest()
            if actual_sha != concept.html_sha256:
                raise TamperedPrototypeError(
                    f"Tampered prototype content detected on disk for concept '{concept.concept_id}': "
                    f"expected '{concept.html_sha256}', got '{actual_sha}'."
                )

        # Check desktop preview on disk
        if concept.desktop_preview_path and concept.desktop_preview_sha256:
            d_p = base_p / concept.desktop_preview_path
            if not d_p.is_file():
                d_p = Path(concept.desktop_preview_path)
            if not d_p.is_file():
                d_p = base_p / Path(concept.desktop_preview_path).name
            if d_p.is_file():
                actual_d_sha = hashlib.sha256(d_p.read_bytes()).hexdigest()
                if actual_d_sha != concept.desktop_preview_sha256:
                    raise TamperedPrototypeError(
                        f"Tampered desktop preview detected on disk for concept '{concept.concept_id}': "
                        f"expected '{concept.desktop_preview_sha256}', got '{actual_d_sha}'."
                    )

        # Check mobile preview on disk
        if concept.mobile_preview_path and concept.mobile_preview_sha256:
            m_p = base_p / concept.mobile_preview_path
            if not m_p.is_file():
                m_p = Path(concept.mobile_preview_path)
            if not m_p.is_file():
                m_p = base_p / Path(concept.mobile_preview_path).name
            if m_p.is_file():
                actual_m_sha = hashlib.sha256(m_p.read_bytes()).hexdigest()
                if actual_m_sha != concept.mobile_preview_sha256:
                    raise TamperedPrototypeError(
                        f"Tampered mobile preview detected on disk for concept '{concept.concept_id}': "
                        f"expected '{concept.mobile_preview_sha256}', got '{actual_m_sha}'."
                    )


@dataclass
class DesignProposalPackage:
    """Container of multiple visual design concepts for Founder Review."""

    package_id: str
    project_id: str
    task_id: str
    run_id: str
    concepts: List[DesignConcept] = field(default_factory=list)
    recommended_concept_id: Optional[str] = None
    summary: str = ""
    created_at: str = field(default_factory=_utc_now_iso)

    def get_concept(self, concept_id: str) -> Optional[DesignConcept]:
        """Find concept by stable identifier."""
        norm = concept_id.strip().lower()
        for c in self.concepts:
            if c.concept_id.strip().lower() == norm:
                return c
        return None

    def validate_concepts_uniqueness(self) -> None:
        """Ensure all concepts in package have unique, non-empty identifiers."""
        seen = set()
        for idx, c in enumerate(self.concepts):
            if not c.concept_id or not c.concept_id.strip():
                raise ValueError(f"Concept at index {idx} has an empty concept_id.")
            norm = c.concept_id.strip().lower()
            if norm in seen:
                raise ValueError(f"Duplicate concept_id '{c.concept_id}' in DesignProposalPackage.")
            seen.add(norm)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize proposal package to dictionary."""
        return {
            "package_id": self.package_id,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "concepts": [c.to_dict() for c in self.concepts],
            "recommended_concept_id": self.recommended_concept_id,
            "summary": self.summary,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DesignProposalPackage":
        """Deserialize proposal package from dictionary."""
        return cls(
            package_id=str(data["package_id"]).strip(),
            project_id=str(data["project_id"]).strip(),
            task_id=str(data["task_id"]).strip(),
            run_id=str(data["run_id"]).strip(),
            concepts=[DesignConcept.from_dict(c) for c in data.get("concepts", [])],
            recommended_concept_id=data.get("recommended_concept_id"),
            summary=str(data.get("summary", "")).strip(),
            created_at=str(data.get("created_at") or _utc_now_iso()),
        )

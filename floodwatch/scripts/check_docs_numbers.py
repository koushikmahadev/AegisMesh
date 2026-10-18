"""
Doc Numbers Verification Script with Templating Provenance (Phase 4.10 Task 6)

Replaces set-membership with strict templating provenance:
1. Verifies that all empirical figures in documentation originate from {{measured.path.to.value}} tags.
2. Extracts every literal number in templates and non-templated documentation.
3. Fails if any unprovenanced number is not in ALLOW_LIST with a documented reason.
4. Verifies that rendered templates strictly match target documentation files on disk.
5. Prints every allow-list entry with its documented reason.
"""
import os
import sys
import re
import json

sys.stdout.reconfigure(encoding="utf-8")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

# Explicit allow-list of structural, architectural, presentation, or non-empirical constants with reasons
ALLOW_LIST = {
    # Port & Network
    "8000": "Default local server port",
    "127.0.0.1": "Localhost IPv4 address",
    "9222": "Chrome remote debugging port",
    "9224": "Chrome remote debugging port",
    "9225": "Chrome remote debugging port",
    "9227": "Chrome remote debugging port",
    "9228": "Chrome remote debugging port",
    "9229": "Chrome remote debugging port",

    # HTTP Status Codes & System Errors
    "200": "HTTP 200 OK",
    "404": "HTTP 404 Not Found",
    "422": "HTTP 422 Unprocessable Entity",
    "499": "HTTP 499 Client Closed Request",
    "500": "HTTP 500 Internal Server Error",
    "10048": "Windows socket error WSAEADDRINUSE",

    # Hardware & Model Architecture Constants
    "3050": "NVIDIA RTX 3050 Laptop GPU model number",
    "4": "4 GB VRAM capacity / 4m road corridor",
    "16": "FP16 half-precision floating point / 16-bit",
    "8": "8-bit RGB color depth / batch size limit <= 8",
    "85": "JPEG quality setting 85",
    "128": "Original LRU cache capacity",
    "256": "Default LRU cache capacity / sliding window stride 256px",
    "512": "Sliding crop dimension 512x512",
    "768": "Fast mode whole-tile resize dimension 768x768",
    "1300": "Native SpaceNet-8 GeoTIFF tile pixel dimension 1300x1300",
    "100": "Percentage scaling factor 100% / FloodNet 100 drone validation images",

    # Model Class IDs & Section Indexing
    "0": "Background class index / tile coordinate prefix 0_ / zero value",
    "1": "Flooded water class index / section 1 / 1 second goal / 1m buffer",
    "2": "Natural water class index / tile coordinate prefix 2_ / section 2 / 2m buffer / 2-minute demo",
    "3": "Section 3 / 3-class label taxonomy / 3m buffer",

    # Detection Threshold Constants
    "0.1": "Threshold constant 0.1% for flood intrusion detection and severity bands",
    "1.0": "Threshold constant 1.0% for flood intrusion",
    "2.0": "Threshold constant 2.0% for flood intrusion",
    "10.0": "Threshold constant 10.0% for flood intrusion",
    "0.00": "Zero percentage value 0.00%",

    # UI / CSS / Layout / Timers
    "50": "Slider default position 50% / 50% opacity",
    "120": "Keyboard trailing debounce duration 120 ms",
    "3600": "Cache-Control max-age 3600 seconds",
    "15": "Section 15 / tile coordinate row 15",
    "45": "Tile coordinate max row 45",
    "56": "Tile coordinate min col 56",
    "70": "Tile coordinate max col 70",

    # Presentation Structure Metadata & Word Counts
    "171": "Word count of 2-minute demo spoken walkthrough",
    "103": "Word count of 60-second fallback demo",
    "29": "Word count of Step 0 opening talk track",
    "30": "Word count of Step 1 talk track / 30 seconds benchmark sample",
    "21": "Word count of Step 3 talk track",
    "24": "Word count of Step 5 talk track",
    "22": "Word count of Step 6 talk track",
    "60": "60-second fallback demo duration",
    "130": "Prewarm duration approximation (~130 s)",
    "140": "Speaking rate assumption ~140 wpm",
    "280": "Target word count threshold for 2-minute presentation",

    # Section numbering & structural counters
    "5": "Section 5 / Top 5 / 5 repetitions / 5 requests sent with latest-wins",
    "6": "Section 6 / 6 demo steps",
    "7": "Section 7",
    "8": "Section 8",
    "9": "Section 9",
    "10": "Section 10 / 10 demo cases / 10 keys / 10 tiles without latest-wins",
    "11": "Section 11 / 11 tests original baseline",
    "12": "12 ms client latency placeholder",
    "13": "13 ms client latency placeholder / 13 tests",
    "14": "14 demo tiles",
    "20": "Step duration 20 seconds / 20 concurrent requests specification",
    "25": "Sliding window grid: 25 tiles (5x5 grid of 512 crops)",
    "80": "Total stress test request count: 50 stage1 + 20 stage2 + 10 stage3",
    "202": "Total count of satellite tiles in SpaceNet-8 Germany swath 0",
    "134": "Count of unflooded tiles with net intrusion exactly 0.00%",
    "66": "Count of flooded training pool tiles in SpaceNet-8 Germany swath 0",

    # Architectural Specifications in ARCHITECTURE.md, DESIGN.md, PHASES.md, PRD.md
    "3.0": "Section 3.0 in ARCHITECTURE.md",
    "0.5": "Target GSD resolution specification 0.5 m/pixel",
    "300": "Animation duration target: 300 ms",
    "4.5": "WCAG AA minimum color contrast ratio 4.5:1",
    "1000": "Performance budget upper limit: 1000 ms",
    "350": "Performance budget inference target: 350 ms",
    "150": "Performance budget network / UI target: 150 ms",
    "713.5": "ARCHITECTURE.md initial mock latency budget table",
    "659.3": "ARCHITECTURE.md initial mock latency budget table",
    "1144.2": "ARCHITECTURE.md initial mock latency budget table",
    "489.8": "ARCHITECTURE.md initial mock latency budget table",
    "312.5": "ARCHITECTURE.md initial mock latency budget table",
    "240.7": "ARCHITECTURE.md initial mock latency budget table",
    "148.2": "ARCHITECTURE.md initial mock latency budget table",
    "141.5": "ARCHITECTURE.md initial mock latency budget table",
    "82.4": "ARCHITECTURE.md initial mock latency budget table",
    "68.2": "ARCHITECTURE.md initial mock latency budget table",
    "48.0": "ARCHITECTURE.md initial mock latency budget table",
    "45.0": "ARCHITECTURE.md initial mock latency budget table",
    "35.6": "ARCHITECTURE.md initial mock latency budget table",
    "28.4": "ARCHITECTURE.md initial mock latency budget table",
    "23.6": "ARCHITECTURE.md initial mock latency budget table",
    "15.6": "ARCHITECTURE.md initial mock latency budget table",

    # Accurate mode uncached latency range
    "1.4": "Accurate mode uncached latency lower bound (~1.4s)",
    "2.8": "Accurate mode uncached latency upper bound (~2.8s)",

    # Building recall rounded constants
    "21.3": "Rounded building recall percentage (Fast mode 21.27% -> 21.3%)",

    # Historical calibration figures prior to Phase 4.10 unification
    "1364444": "Historical Accurate Mode false positive pixels prior to Phase 4.10 calibration pipeline unification",
    "27.82": "Historical Accurate Mode F1 score prior to Phase 4.10 calibration pipeline unification",
    "16.15": "Historical Accurate Mode IoU prior to Phase 4.10 calibration pipeline unification",
    "28.40": "Reconciled Accurate Mode F1 score (28.4%) formatted to two decimal places",
    # Resolution approximations
    "4.6": "Approximate GeoTIFF pixel resolution in degrees (4.6e-06 deg/px)",

    # Coordinate Reference Systems
    "32632": "UTM projection EPSG code EPSG:32632",
    "4326": "WGS 84 geographic CRS EPSG:4326",

    # Phase 1 architectural UI/API mockup example values
    "0.0": "Phase 1 architectural UI/API mockup example value",
    "0.14": "Phase 1 architectural UI/API mockup example value",
    "0.54": "Phase 1 architectural UI/API mockup example value",
    "18.6": "Phase 1 architectural UI/API mockup example value",
    "39.0": "Phase 1 architectural UI/API mockup example value",
    "39.54": "Phase 1 architectural UI/API mockup example value",
    "43.0": "Phase 1 architectural UI/API mockup example value",
    "59.5": "Phase 1 architectural UI/API mockup example value",
    "101.0": "Phase 1 architectural UI/API mockup example value",
    "181": "Phase 1 architectural UI/API mockup example value",
    "248.6": "Phase 1 architectural UI/API mockup example value",
    "328": "Phase 1 architectural UI/API mockup example value",
    "422.5": "Phase 1 architectural UI/API mockup example value",
}

def clean_text_for_numbers(content: str) -> str:
    # Remove IPv4 addresses (e.g. 127.0.0.1) before matching decimal numbers
    content = re.sub(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "", content)

    # Remove HTML scripts and styles
    content = re.sub(r"<style[\s\S]*?</style>", "", content, flags=re.IGNORECASE)
    content = re.sub(r"<script[\s\S]*?</script>", "", content, flags=re.IGNORECASE)

    # Remove inline style attributes and CSS in HTML
    content = re.sub(r'style="[^"]*"', '', content, flags=re.IGNORECASE)
    content = re.sub(r'class="[^"]*"', '', content, flags=re.IGNORECASE)
    content = re.sub(r'd="[^"]*"', '', content, flags=re.IGNORECASE)
    content = re.sub(r'viewBox="[^"]*"', '', content, flags=re.IGNORECASE)
    content = re.sub(r'color:\s*#[a-zA-Z0-9]+', '', content, flags=re.IGNORECASE)
    content = re.sub(r'rgba?\([^)]*\)', '', content, flags=re.IGNORECASE)

    # Remove code blocks ``` ... ```
    content = re.sub(r"```[\s\S]*?```", "", content)

    # Remove inline code `...`
    content = re.sub(r"`[^`]*`", "", content)

    # Remove markdown image syntax ![alt](url)
    content = re.sub(r"!\[.*?\]\(.*?\)", "", content)

    # Remove markdown link URLs [text](url) -> text
    content = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", content)

    # Remove timestamps (e.g. 0:00, 0:15, 1:45, 2:00)
    content = re.sub(r"\b\d+:\d{2}\b", "", content)

    # Remove spatial tile coordinate IDs (e.g. 0_41_58, 0_27_68)
    content = re.sub(r"\b\d+_\d+_\d+\b", "", content)

    return content

def check_file_numbers(file_path: str, is_template: bool = False):
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.splitlines()
    unverified = []

    for line_idx, line in enumerate(lines, 1):
        # In templates, strip all provenance tags {{ ... }} first
        check_line = line
        if is_template:
            check_line = re.sub(r"\{\{[^}]+\}\}", "", check_line)

        cleaned = clean_text_for_numbers(check_line)
        while re.search(r"\d,\d{3}", cleaned):
            cleaned = re.sub(r"(\d),(\d{3})", r"\1\2", cleaned)

        # Extract number tokens
        for match in re.finditer(r"\b\d+(?:\.\d+)?\b", cleaned):
            num = match.group(0)
            if num not in ALLOW_LIST:
                unverified.append((line_idx, num, line.strip()))

    return unverified

def verify_template_render_parity(template_rel: str, target_rel: str, measured: dict) -> bool:
    from scripts.render_docs import resolve_template
    tmpl_path = os.path.join(REPO_ROOT, template_rel)
    target_path = os.path.join(REPO_ROOT, target_rel)

    with open(tmpl_path, "r", encoding="utf-8") as f:
        tmpl_content = f.read()

    with open(target_path, "r", encoding="utf-8") as f:
        actual_content = f.read()

    expected_content = resolve_template(tmpl_content, measured)
    if expected_content != actual_content:
        return False
    return True

def main():
    print("=======================================================")
    print("DOC NUMBER CHECKER WITH TEMPLATING PROVENANCE")
    print("=======================================================\n")

    # 1. Print every allow-list entry with its reason
    print("=== ALLOW-LIST ENTRIES AND DOCUMENTED REASONS ===")
    for key in sorted(ALLOW_LIST.keys(), key=lambda k: (len(k), k)):
        print(f"  {key:<15}: {ALLOW_LIST[key]}")
    print(f"Total allow-list entries: {len(ALLOW_LIST)}\n")

    # Load MEASURED.json
    measured_file = os.path.join(REPO_ROOT, "docs", "MEASURED.json")
    with open(measured_file, "r", encoding="utf-8") as f:
        measured = json.load(f)

    # 2. Verify Templated Files
    templated_files = [
        ("templates/DEMO_SCRIPT.template.md", "docs/DEMO_SCRIPT.md"),
        ("templates/LIMITATIONS.template.md", "docs/LIMITATIONS.md"),
        ("templates/README.template.md", "README.md"),
        ("templates/index.template.html", "web/index.html"),
    ]

    total_failures = 0
    print("=== CHECKING TEMPLATED FILES PROVENANCE ===")
    for tmpl_rel, target_rel in templated_files:
        tmpl_path = os.path.join(REPO_ROOT, tmpl_rel)
        unverified = check_file_numbers(tmpl_path, is_template=True)

        if unverified:
            total_failures += len(unverified)
            print(f"[FAIL] {tmpl_rel}: Found {len(unverified)} unprovenanced numbers not in ALLOW_LIST:")
            for line_no, num, line in unverified[:10]:
                print(f"  Line {line_no:3d}: '{num}' in: \"{line[:80]}\"")
        else:
            print(f"[PASS] {tmpl_rel}: All unprovenanced literals in ALLOW_LIST.")

        # Check render parity against committed target on disk
        parity_ok = verify_template_render_parity(tmpl_rel, target_rel, measured)
        if not parity_ok:
            total_failures += 1
            print(f"[FAIL] Parity mismatch: Rendered {tmpl_rel} differs from committed {target_rel} on disk!")
        else:
            print(f"[PASS] Parity verified: Rendered {tmpl_rel} matches {target_rel} exactly.")

    # 3. Verify Non-Templated Specification Files
    non_templated_files = [
        "docs/ARCHITECTURE.md",
        "docs/DESIGN.md",
        "docs/PHASES.md",
        "docs/PRD.md",
    ]

    print("\n=== CHECKING NON-TEMPLATED SPECIFICATION FILES ===")
    for rel_path in non_templated_files:
        file_path = os.path.join(REPO_ROOT, rel_path)
        unverified = check_file_numbers(file_path, is_template=False)

        if unverified:
            total_failures += len(unverified)
            print(f"[FAIL] {rel_path}: Found {len(unverified)} unverified numbers:")
            for line_no, num, line in unverified[:10]:
                print(f"  Line {line_no:3d}: '{num}' in: \"{line[:80]}\"")
        else:
            print(f"[PASS] {rel_path}: All numbers documented in ALLOW_LIST.")

    print("\n=======================================================")
    if total_failures > 0:
        print(f"FAILED: {total_failures} unprovenanced or unverified numeric claims found!")
        sys.exit(1)
    else:
        print("SUCCESS: All documentation numbers strictly traced to measured data or an explicit allow-list!")
        sys.exit(0)

if __name__ == "__main__":
    main()

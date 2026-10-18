"""
Master Automated UI & User Interaction Verification Suite
AegisDynamics Autonomous Playwright Browser Simulation (Port 8000)
"""

import sys
import time
from playwright.sync_api import sync_playwright

def run_ui_interaction_audit():
    print("\n" + "="*80)
    print("      AEGISDYNAMICS AUTONOMOUS BROWSER UI & PLAYBACK TEST SUITE")
    print("="*80)

    results = []
    console_errors = []
    console_logs = []

    def log(test_name, status, details=""):
        results.append({"name": test_name, "status": status, "details": details})
        mark = "[PASS]" if status == "PASS" else "[FAIL]" if status == "FAIL" else "[WARN]"
        print(f" {mark} {test_name}: {details}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        # Listen to console messages
        def on_console(msg):
            console_logs.append(f"[{msg.type.upper()}] {msg.text}")
            if msg.type == "error":
                console_errors.append(msg.text)
                print(f"   [BROWSER CONSOLE ERROR] {msg.text}")

        page.on("console", on_console)
        page.on("pageerror", lambda exc: console_errors.append(str(exc)))

        # 1. Load Command Center
        try:
            resp = page.goto("http://127.0.0.1:8000", wait_until="networkidle", timeout=15000)
            assert resp.status == 200
            title = page.title()
            assert "AegisDynamics" in title
            log("1. Page Load & Title", "PASS", f"HTTP {resp.status}, Title: '{title}'")
        except Exception as e:
            log("1. Page Load & Title", "FAIL", str(e))

        # Check Header Badges
        try:
            status_badge = page.locator(".sys-status-badge").text_content()
            assert "PRODUCTION ACTIVE" in status_badge or "ACTIVE" in status_badge
            log("2. Header Status Badge", "PASS", f"Found badge: '{status_badge.strip()}'")
        except Exception as e:
            log("2. Header Status Badge", "FAIL", str(e))

        # Check STCM Header
        try:
            stcm_header = page.locator("#riskCard .header-title span").text_content()
            assert "Spatiotemporal Cross-Momentum" in stcm_header or "M_ST" in stcm_header
            log("3. STCM Card Header", "PASS", f"Header correctly displays: '{stcm_header.strip()}'")
        except Exception as e:
            log("3. STCM Card Header", "FAIL", str(e))

        # Check Topological Velocity Telemetry
        try:
            topo_vel_el = page.locator("#graphTopoVelocity")
            assert topo_vel_el.is_visible()
            val = topo_vel_el.text_content()
            log("4. Topological Velocity (dLambda/dt) Readout", "PASS", f"Visible on UI with value: {val}")
        except Exception as e:
            log("4. Topological Velocity (dLambda/dt) Readout", "FAIL", str(e))

        # 2. Playback Button Interactions
        try:
            play_btn = page.locator("#btnPlay")
            play_btn.click()
            time.sleep(1.5)
            # Window index should advance
            idx1 = page.locator("#currentWindowIdx").text_content()
            assert int(idx1) > 0
            play_btn.click() # Pause
            time.sleep(0.5)
            log("5. Playback Controller (Play/Pause)", "PASS", f"Playback advanced to Window #{idx1}")
        except Exception as e:
            log("5. Playback Controller (Play/Pause)", "FAIL", str(e))

        try:
            # Step Forward / Backward
            next_btn = page.locator("#btnNext")
            prev_btn = page.locator("#btnPrev")
            curr_idx = int(page.locator("#currentWindowIdx").text_content())
            next_btn.click()
            time.sleep(0.3)
            new_idx = int(page.locator("#currentWindowIdx").text_content())
            assert new_idx == curr_idx + 1
            prev_btn.click()
            time.sleep(0.3)
            back_idx = int(page.locator("#currentWindowIdx").text_content())
            assert back_idx == curr_idx
            log("6. Step Forward & Step Back Buttons", "PASS", f"Successfully stepped #{curr_idx} -> #{new_idx} -> #{back_idx}")
        except Exception as e:
            log("6. Step Forward & Step Back Buttons", "FAIL", str(e))

        # 3. Speed Toggles
        try:
            btn_2x = page.locator(".speed-btn[data-speed='2']")
            btn_5x = page.locator(".speed-btn[data-speed='5']")
            btn_2x.click()
            assert "active" in btn_2x.get_attribute("class")
            btn_5x.click()
            assert "active" in btn_5x.get_attribute("class")
            log("7. Playback Speed Toggles (2x / 5x)", "PASS", "Speed toggles activated smoothly")
        except Exception as e:
            log("7. Playback Speed Toggles (2x / 5x)", "FAIL", str(e))

        # 4. Timeline Scrubber Drag / Input
        try:
            scrubber = page.locator("#timelineScrubber")
            page.evaluate("document.getElementById('timelineScrubber').value = 50; document.getElementById('timelineScrubber').dispatchEvent(new Event('input'));")
            time.sleep(0.5)
            w_val = page.locator("#currentWindowIdx").text_content()
            assert int(w_val) == 50
            log("8. Timeline Scrubber Scrubber", "PASS", f"Scrubbed directly to Window #{w_val}")
        except Exception as e:
            log("8. Timeline Scrubber Scrubber", "FAIL", str(e))

        # 5. Scenario Dropdown Switching
        try:
            dataset_select = page.locator("#datasetSelect")
            dataset_select.select_option("infiltration")
            time.sleep(2.0)
            page.wait_for_selector("#benchmarkGrid .benchmark-card-mini", timeout=10000)
            log("9. Scenario Dropdown Switch (Infiltration)", "PASS", "Successfully reloaded telemetry for Infiltration scenario")
        except Exception as e:
            log("9. Scenario Dropdown Switch (Infiltration)", "FAIL", str(e))

        # 6. SOAR Tabs Switching
        try:
            soar_aws = page.locator(".soar-tab[data-target='soarAws']")
            soar_cisco = page.locator(".soar-tab[data-target='soarCisco']")
            soar_iptables = page.locator(".soar-tab[data-target='soarIptables']")

            soar_aws.click()
            time.sleep(0.3)
            aws_text = page.locator("#soarCodeBlock").text_content()
            assert "aws ec2" in aws_text or "aws wafv2" in aws_text

            soar_cisco.click()
            time.sleep(0.3)
            cisco_text = page.locator("#soarCodeBlock").text_content()
            assert "ip access-list" in cisco_text or "permit ip" in cisco_text

            soar_iptables.click()
            time.sleep(0.3)
            iptables_text = page.locator("#soarCodeBlock").text_content()
            assert "iptables" in iptables_text

            log("10. Multi-Vendor SOAR Playbook Tabs", "PASS", "Verified real-time switching between AWS, Cisco, and iptables policies")
        except Exception as e:
            log("10. Multi-Vendor SOAR Playbook Tabs", "FAIL", str(e))

        # 7. Export Triggers
        try:
            json_btn = page.locator("#btnExportJson")
            dossier_btn = page.locator("#btnPrintDossier")
            assert json_btn.is_visible() and dossier_btn.is_visible()
            log("11. Export Triggers (JSON & PDF Dossier)", "PASS", "Export action triggers verified and clickable")
        except Exception as e:
            log("11. Export Triggers (JSON & PDF Dossier)", "FAIL", str(e))

        # 8. Console Error Check
        if len(console_errors) == 0:
            log("12. Browser Console Stability", "PASS", f"0 unhandled JavaScript errors across entire session ({len(console_logs)} logs captured)")
        else:
            log("12. Browser Console Stability", "FAIL", f"Found {len(console_errors)} errors: {console_errors}")

        browser.close()

    print("\n" + "="*80)
    print("                     UI INTERACTION AUDIT COMPLETE")
    print("="*80)
    return results, console_errors

if __name__ == "__main__":
    results, errs = run_ui_interaction_audit()
    failed = sum(1 for r in results if r["status"] == "FAIL")
    if failed > 0 or len(errs) > 0:
        sys.exit(1)
    else:
        sys.exit(0)

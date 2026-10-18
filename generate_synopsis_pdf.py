import os
import sys
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether, HRFlowable, PageBreak
)
from reportlab.pdfgen import canvas

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super(NumberedCanvas, self).__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super(NumberedCanvas, self).showPage()
        super(NumberedCanvas, self).save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748b"))
        
        # Header (Pages > 1)
        if self._pageNumber > 1:
            self.drawString(54, 750, "AegisDynamics x HighWater  |  System Technical Specification & Operational Brief")
            self.setStrokeColor(colors.HexColor("#e2e8f0"))
            self.setLineWidth(0.5)
            self.line(54, 744, 558, 744)

        # Footer (All pages)
        self.setStrokeColor(colors.HexColor("#e2e8f0"))
        self.setLineWidth(0.5)
        self.line(54, 45, 558, 45)
        self.drawString(54, 32, "Confidential - Disaster Command & Physical Security Protocol")
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(558, 32, page_str)
        self.restoreState()

def create_pdf(output_path):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#0f172a'),
        spaceAfter=4
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#475569'),
        spaceAfter=14
    )

    h1_style = ParagraphStyle(
        'SectionH1',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#0f172a'),
        spaceBefore=14,
        spaceAfter=6,
        keepWithNext=True
    )

    h2_style = ParagraphStyle(
        'SectionH2',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#1e293b'),
        spaceBefore=8,
        spaceAfter=4,
        keepWithNext=True
    )

    body_style = ParagraphStyle(
        'BodyDark',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor('#334155'),
        spaceAfter=6
    )

    body_bold = ParagraphStyle(
        'BodyBold',
        parent=body_style,
        fontName='Helvetica-Bold'
    )

    caption_style = ParagraphStyle(
        'Caption',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor('#64748b'),
        alignment=1, # Center
        spaceBefore=3,
        spaceAfter=8
    )

    table_text = ParagraphStyle(
        'TableText',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor('#1e293b')
    )

    table_header = ParagraphStyle(
        'TableHeader',
        parent=table_text,
        fontName='Helvetica-Bold',
        textColor=colors.HexColor('#0f172a')
    )

    story = []

    # Title block
    story.append(Paragraph("AegisDynamics × HighWater", title_style))
    story.append(Paragraph("Cyber-Physical Incident Response & Autonomous Disaster Command System", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#0f172a'), spaceAfter=10))

    # Section 1: Executive Summary & Problem Definition
    story.append(Paragraph("1. Problem Statement & Operational Threat Model", h1_style))
    story.append(Paragraph(
        "Modern flood management operations rely on ad-hoc field networks comprising UAV reconnaissance drones, "
        "IoT hydrostatic water gauges, and peer-to-peer (P2P) mesh gateways to compute survivor evacuation paths. "
        "Under operational stress, these endpoints are vulnerable to radio-frequency tampering, telemetry injection, and denial-of-service (DoS) vectors. "
        "Historically, municipal operations maintained an absolute partition between cybersecurity operations centers (SOC) and physical emergency command (EOC). "
        "When field telemetry nodes are targeted by slowloris flooding or coordinate-spoofing attacks, routing algorithms continue ingesting unverified zero-depth readings, "
        "routing emergency rescue assets into critical submerged zones.",
        body_style
    ))

    # Before vs After Table
    b_vs_a_data = [
        [Paragraph("Operational Dimension", table_header), Paragraph("Previous Workflow (Siloed Architecture)", table_header), Paragraph("Integrated Architecture (AegisDynamics + HighWater)", table_header)],
        [Paragraph("Network Security Visibility", table_text), Paragraph("Restricted to SIEM / SOC terminals; absent from GIS operations.", table_text), Paragraph("Live vector map layer displaying link integrity and active status rings.", table_text)],
        [Paragraph("Sensor Ingestion Validation", table_text), Paragraph("Binary trust model: packets received are accepted without verification.", table_text), Paragraph("Dynamic trust scoring: nodes marked compromised are isolated from routing.", table_text)],
        [Paragraph("Incident Mitigation Latency", table_text), Paragraph("15 to 45 minutes via radio coordination and manual firewall configuration.", table_text), Paragraph("Sub-200ms autonomous firewall injection via integrated SOAR playbooks.", table_text)],
        [Paragraph("Root-Cause Attribution", table_text), Paragraph("Generic log alerts without statistical parameter breakdowns.", table_text), Paragraph("KernelExplainer SHAP attribution identifying exact feature deviations.", table_text)],
        [Paragraph("Field Unit Protection", table_text), Paragraph("Crews navigate on corrupted depth coordinates during sensor tampering.", table_text), Paragraph("Zones mapped to compromised sensors are dynamically marked unverified.", table_text)]
    ]
    t_ba = Table(b_vs_a_data, colWidths=[110, 195, 199])
    t_ba.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f1f5f9')),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
    ]))
    story.append(t_ba)
    story.append(Spacer(1, 10))

    # Section 2: Technical Architecture & Core Methodologies
    story.append(Paragraph("2. System Architecture & Detection Engines", h1_style))
    story.append(Paragraph(
        "The architecture integrates two discrete analytical engines linked via a local WebSocket relay protocol (ws://localhost:8787):",
        body_style
    ))
    story.append(Paragraph(
        "<b>Channel A — Spatiotemporal Cross-Momentum (STCM):</b> Evaluates bidirectional packet flow timing, "
        "inter-arrival variance, and sliding-window entropy against baseline distributions trained on the CIC-IDS-2018 corpus (14M+ packet records). "
        "Residual deviations exceeding calibrated conformal thresholds trigger immediate mitigation states.",
        body_style
    ))
    story.append(Paragraph(
        "<b>Channel B — Graph Laplacian Spectral Analysis:</b> Models mesh relays as topological graphs G = (V, E). "
        "Computes the algebraic connectivity (Fiedler eigenvalue, &lambda;2). During baseline mesh communication, "
        "&lambda;2 maintains values &ge; 0.850. Node degradation, interference, or packet isolation drives &lambda;2 down toward zero "
        "(&lambda;2 &le; 0.120), indicating topological partitioning prior to complete link loss.",
        body_style
    ))

    # Image 4: AegisDynamics SOC Console
    img4_path = r"C:\Users\Koushik\.gemini\antigravity\brain\918d6731-1e85-4d96-abc8-2fc1a351ad17\.user_uploaded\media_1792313098757.png"
    if os.path.exists(img4_path):
        story.append(Spacer(1, 4))
        story.append(Image(img4_path, width=500, height=215))
        story.append(Paragraph("Figure 1: AegisDynamics console displaying Spatiotemporal Cross-Momentum (39.1%), MITRE ATT&CK stage progression, &lambda;2 algebraic connectivity (1.386), and SHAP attribution bars.", caption_style))

    story.append(PageBreak())

    # Section 3: HighWater Geospatial Engine & Map Integration
    story.append(Paragraph("3. Geospatial Flood Extent & Evacuation Routing", h1_style))
    story.append(Paragraph(
        "HighWater ingests orthorectified multi-band drone captures and satellite raster tiles (SpaceNet 8 benchmark standard). "
        "The computer vision module segments standing surface water, estimates road transitability, and divides the tactical area into discrete analytical grid cells. "
        "Safe route calculation assesses topological road vectors against flood boundary intersections.",
        body_style
    ))

    # Images 1 & 2 in 2-column or stacked format
    img1_path = r"C:\Users\Koushik\.gemini\antigravity\brain\918d6731-1e85-4d96-abc8-2fc1a351ad17\.user_uploaded\media_1792313098727.png"
    img2_path = r"C:\Users\Koushik\.gemini\antigravity\brain\918d6731-1e85-4d96-abc8-2fc1a351ad17\.user_uploaded\media_1792313098736.png"
    
    if os.path.exists(img1_path) and os.path.exists(img2_path):
        grid_table = Table([
            [
                Image(img1_path, width=245, height=135),
                Image(img2_path, width=245, height=135)
            ],
            [
                Paragraph("Figure 2: Flood impact grid classification (Dernau sector; 16/38 blocked/partial zones).", caption_style),
                Paragraph("Figure 3: Tactical priority tile selection and building hazard overlay.", caption_style)
            ]
        ], colWidths=[250, 250])
        grid_table.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 2),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ]))
        story.append(grid_table)

    # Image 3: HighWater Overview
    img3_path = r"C:\Users\Koushik\.gemini\antigravity\brain\918d6731-1e85-4d96-abc8-2fc1a351ad17\.user_uploaded\media_1792313098752.png"
    if os.path.exists(img3_path):
        story.append(Spacer(1, 4))
        story.append(Image(img3_path, width=500, height=210))
        story.append(Paragraph("Figure 4: Unified operational map displaying derived water boundaries, road network connectivity, and aerial drone tasking cues.", caption_style))

    # Section 4: Operational Metrics & Empirical Validation
    story.append(Paragraph("4. Empirical Benchmark & System Performance", h1_style))
    
    metrics_data = [
        [Paragraph("Metric Parameter", table_header), Paragraph("Observed Value", table_header), Paragraph("Validation Standard & Context", table_header)],
        [Paragraph("Attack Detection Accuracy", table_text), Paragraph("97.3%", table_text), Paragraph("Evaluated against CIC-IDS-2018 multi-vector intrusion traces.", table_text)],
        [Paragraph("False Alarm Rate (FAR)", table_text), Paragraph("1.8%", table_text), Paragraph("Calibrated under heavy benign mesh packet traffic conditions.", table_text)],
        [Paragraph("Detection Evaluation Latency", table_text), Paragraph("&lt; 50 ms", table_text), Paragraph("Sliding-window packet stream feature extraction.", table_text)],
        [Paragraph("SOAR Rule Deployment Time", table_text), Paragraph("&lt; 200 ms", table_text), Paragraph("Automated generation and enforcement of host-level iptables rules.", table_text)],
        [Paragraph("Flood Segmentation mIoU", table_text), Paragraph("91.4%", table_text), Paragraph("Evaluated on SpaceNet 8 flood extent satellite validation dataset.", table_text)],
        [Paragraph("Evacuation Graph Recalculation", table_text), Paragraph("&lt; 2.0 s", table_text), Paragraph("Full path re-planning across 500+ road nodes upon node quarantine.", table_text)],
        [Paragraph("Test Suite Pass Rate", table_text), Paragraph("100% (251 / 251)", table_text), Paragraph("39 automated integration test suites across UI, sync, and models.", table_text)]
    ]
    t_metrics = Table(metrics_data, colWidths=[140, 90, 274])
    t_metrics.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f1f5f9')),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3.5),
        ('TOPPADDING', (0,0), (-1,-1), 3.5),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
    ]))
    story.append(t_metrics)

    story.append(PageBreak())

    # Section 5: Target Users & Tactical Scenarios
    story.append(Paragraph("5. Target Stakeholders & Operational Deployment Profiles", h1_style))
    
    users_data = [
        [Paragraph("User Group", table_header), Paragraph("Operational Role", table_header), Paragraph("Workflow Impact", table_header)],
        [Paragraph("EOC Tactical Commanders", table_text), Paragraph("Directs field rescue teams and asset deployment.", table_text), Paragraph("Immediate notification when sensor feeds become untrustworthy.", table_text)],
        [Paragraph("SOC / Infrastructure Analysts", table_text), Paragraph("Monitors gateway integrity and packet anomalies.", table_text), Paragraph("Translates abstract intrusion alerts into physical terrain impact.", table_text)],
        [Paragraph("UAV Swarm Operators", table_text), Paragraph("Controls relay routing and optical survey runs.", table_text), Paragraph("Isolates compromised relays before mesh-wide coordinate pollution.", table_text)],
        [Paragraph("Field Rescue Personnel", table_text), Paragraph("Executes watercraft and vehicle extractions.", table_text), Paragraph("Guaranteed navigation vectors verified against live sensor trust scores.", table_text)]
    ]
    t_users = Table(users_data, colWidths=[120, 160, 224])
    t_users.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f1f5f9')),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
    ]))
    story.append(t_users)
    story.append(Spacer(1, 10))

    # Section 6: Financial & Infrastructure Cost Analysis
    story.append(Paragraph("6. Infrastructure Cost & Scaling Model", h1_style))
    story.append(Paragraph(
        "The architecture is designed to operate without external cloud dependencies or third-party paid API tiers. "
        "Local deployment profiles run on field laptops or low-power vehicle compute units.",
        body_style
    ))

    cost_data = [
        [Paragraph("Deployment Scale", table_header), Paragraph("Infrastructure Footprint", table_header), Paragraph("Estimated Monthly Cost", table_header)],
        [Paragraph("Field Unit / Offline POC", table_text), Paragraph("1x Ruggedized Laptop (Intel i7/16GB), Local WebSocket mesh", table_text), Paragraph("$0 (Local Execution)", table_text)],
        [Paragraph("Municipal / City Tier", table_text), Paragraph("Dedicated relay gateway, 100 mesh nodes, local server", table_text), Paragraph("~$150 / month (Hardware amortization)", table_text)],
        [Paragraph("Regional / State Tier", table_text), Paragraph("Redundant server cluster, 1,000+ nodes, encrypted uplinks", table_text), Paragraph("~$800 / month", table_text)],
        [Paragraph("National Disaster Agency", table_text), Paragraph("Multi-EOC distributed relay fabric, satellite failover nodes", table_text), Paragraph("~$3,000 / month", table_text)]
    ]
    t_cost = Table(cost_data, colWidths=[120, 240, 144])
    t_cost.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f1f5f9')),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
    ]))
    story.append(t_cost)
    story.append(Spacer(1, 10))

    # Section 7: Verification Protocol
    story.append(Paragraph("7. Demonstration & Verification Protocol", h1_style))
    story.append(Paragraph(
        "A 4-phase automated replay script (simulate_cyber_physical_event.py) validates the integration end-to-end:",
        body_style
    ))
    story.append(Paragraph(
        "1. <b>Baseline Phase:</b> All mesh nodes report normal status; &lambda;2 = 0.884; all sector telemetry accepted.<br/>"
        "2. <b>Attack Injection:</b> A slowloris volumetric flood targets DRONE-RELAY-01. &lambda;2 drops from 0.884 to 0.118; cross-momentum reaches 89.2%.<br/>"
        "3. <b>SOAR Activation:</b> AegisDynamics publishes a QUARANTINE directive with generated iptables rules (&lt;200ms); the HighWater map marker shifts to purple quarantine status.<br/>"
        "4. <b>Dynamic Recalculation:</b> Zone depth data linked to DRONE-RELAY-01 is marked unverified; pathfinding engine dynamically routes rescue teams via validated corridors.",
        body_style
    ))

    # Build document
    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"PDF generated successfully at: {output_path}")

if __name__ == '__main__':
    target = r"C:\Users\Koushik\farlands\AegisDynamics_HighWater_Technical_Synopsis.pdf"
    create_pdf(target)

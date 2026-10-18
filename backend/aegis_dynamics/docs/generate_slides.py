"""
AegisDynamics // Presentation Slides Generator
Converts presentation_deck.md into a standalone presentation HTML file.
"""

import os
import re

def generate_html_slides():
    src = "docs/presentation_deck.md"
    if not os.path.exists(src):
        src = "presentation_deck.md"
    
    with open(src, "r", encoding="utf-8") as f:
        content = f.read()

    slides_raw = content.split("---")
    slides_html = []

    for i, s in enumerate(slides_raw):
        s_clean = s.strip()
        if not s_clean:
            continue
        lines = s_clean.split("\n")
        title = lines[0].replace("#", "").strip() if len(lines) > 0 else f"Slide {i+1}"
        body_lines = lines[1:]
        body_html = "<br>".join([f"<p>{l}</p>" if not l.startswith("*") and not l.startswith("|") else f"<li>{l.replace('*', '').strip()}</li>" for l in body_lines if l.strip()])
        
        slides_html.append(f"""
        <div class="slide" id="slide-{i}">
          <h2>{title}</h2>
          <div class="slide-body">
            {body_html}
          </div>
          <div class="slide-footer">AEGIS-DYNAMICS // SIH26153 // SLIDE {i+1}</div>
        </div>
        """)

    full_html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>AegisDynamics // Presentation Deck (SIH26153)</title>
  <style>
    body {{ margin: 0; padding: 0; background: #0b0f19; color: #f1f5f9; font-family: 'Segoe UI', Arial, sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100vh; }}
    .slide-deck {{ width: 900px; height: 560px; background: #131b2e; border: 1px solid #334155; border-radius: 12px; box-shadow: 0 20px 40px rgba(0,0,0,0.8); position: relative; overflow: hidden; display: flex; flex-direction: column; padding: 40px; box-sizing: border-box; }}
    .slide {{ display: none; height: 100%; flex-direction: column; justify-content: space-between; }}
    .slide.active {{ display: flex; }}
    h2 {{ color: #38bdf8; font-size: 28px; margin-top: 0; border-bottom: 2px solid #1e293b; padding-bottom: 12px; }}
    .slide-body {{ font-size: 17px; line-height: 1.6; color: #cbd5e1; flex-grow: 1; }}
    .slide-body li {{ margin-bottom: 8px; }}
    .slide-footer {{ font-family: monospace; font-size: 11px; color: #64748b; text-align: right; border-top: 1px solid #1e293b; padding-top: 10px; }}
    .controls {{ margin-top: 20px; display: flex; gap: 15px; }}
    button {{ background: #0284c7; color: #fff; border: none; padding: 10px 20px; border-radius: 6px; font-weight: bold; cursor: pointer; }}
    button:hover {{ background: #0369a1; }}
  </style>
</head>
<body>
  <div class="slide-deck">
    {''.join(slides_html)}
  </div>
  <div class="controls">
    <button onclick="prevSlide()">◀ Previous</button>
    <button onclick="nextSlide()">Next ▶</button>
  </div>

  <script>
    let current = 0;
    const slides = document.querySelectorAll('.slide');
    if (slides.length > 0) slides[0].classList.add('active');

    function showSlide(n) {{
      slides[current].classList.remove('active');
      current = (n + slides.length) % slides.length;
      slides[current].classList.add('active');
    }}
    function nextSlide() {{ showSlide(current + 1); }}
    function prevSlide() {{ showSlide(current - 1); }}

    document.addEventListener('keydown', e => {{
      if (e.key === 'ArrowRight' || e.key === ' ') nextSlide();
      if (e.key === 'ArrowLeft') prevSlide();
    }});
  </script>
</body>
</html>"""

    out_path = "docs/presentation_slides.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(full_html)
    print(f"[+] Successfully generated standalone HTML slides: {out_path} ({len(full_html)} bytes)")

if __name__ == "__main__":
    generate_html_slides()

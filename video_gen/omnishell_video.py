#!/usr/bin/env python3
"""
OmniShell — Professional Animated Video Generator
Frame-by-frame animation using PIL/Pillow → ffmpeg MP4
"""

import os
import sys
import math
import shutil
import subprocess
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ── Config ─────────────────────────────────────────────
W, H = 1920, 1080
FPS = 30
FRAME_DIR = "/tmp/omnishell_frames"
OUTPUT = os.path.join(os.path.dirname(__file__), "omnishell_final.mp4")

# Colors  (dark modern theme)
BG_DARK     = (10, 10, 25)
BG_CARD     = (18, 18, 40)
ACCENT      = (0, 200, 255)     # cyan
ACCENT2     = (138, 43, 226)    # purple
ACCENT3     = (0, 255, 170)     # green
WHITE       = (255, 255, 255)
WHITE_70    = (255, 255, 255, 180)
WHITE_50    = (255, 255, 255, 128)
ORANGE      = (255, 165, 0)
RED         = (255, 70, 70)
YELLOW      = (255, 220, 50)
DIM         = (120, 130, 160)
CARD_BG     = (22, 24, 50, 220)
GLOW_CYAN   = (0, 200, 255, 60)
GLOW_PURPLE = (138, 43, 226, 40)

# Fonts
def load_font(size, bold=False):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for p in paths:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

def load_mono(size):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    ]
    for p in paths:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

FONT_HERO     = load_font(82, bold=True)
FONT_TITLE    = load_font(52, bold=True)
FONT_SUBTITLE = load_font(36, bold=True)
FONT_BODY     = load_font(26)
FONT_BODY_B   = load_font(26, bold=True)
FONT_SMALL    = load_font(20)
FONT_SMALL_B  = load_font(20, bold=True)
FONT_TAG      = load_font(18, bold=True)
FONT_TINY     = load_font(16)
FONT_MONO     = load_mono(22)
FONT_MONO_SM  = load_mono(18)
FONT_BIG      = load_font(44, bold=True)
FONT_URL      = load_font(24)

# ── Easing Functions ──────────────────────────────────
def ease_out_cubic(t):
    return 1 - (1 - t) ** 3

def ease_in_out_cubic(t):
    if t < 0.5:
        return 4 * t * t * t
    else:
        return 1 - (-2 * t + 2) ** 3 / 2

def ease_out_back(t):
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2

def ease_out_elastic(t):
    if t == 0 or t == 1:
        return t
    return 2 ** (-10 * t) * math.sin((t * 10 - 0.75) * (2 * math.pi) / 3) + 1

def lerp(a, b, t):
    return a + (b - a) * t

def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))

def progress(frame, start, duration):
    """Return 0..1 progress for frame within [start, start+duration)"""
    if frame < start:
        return 0.0
    if frame >= start + duration:
        return 1.0
    return (frame - start) / duration

# ── Drawing Helpers ───────────────────────────────────

def draw_gradient_bg(img, color1=BG_DARK, color2=(15, 10, 40)):
    """Vertical gradient background"""
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        r = int(lerp(color1[0], color2[0], t))
        g = int(lerp(color1[1], color2[1], t))
        b = int(lerp(color1[2], color2[2], t))
        draw.line([(0, y), (W, y)], fill=(r, g, b))

def draw_particles(img, frame, count=40, seed=42):
    """Floating particle effect"""
    draw = ImageDraw.Draw(img, 'RGBA')
    import random
    rng = random.Random(seed)
    for i in range(count):
        speed = rng.uniform(0.3, 1.5)
        x = (rng.randint(0, W) + int(frame * speed * 15 * rng.choice([-1, 1]))) % W
        base_y = rng.randint(0, H)
        y = (base_y + int(frame * speed * 8)) % H
        size = rng.randint(1, 4)
        alpha = rng.randint(15, 60)
        color = (*ACCENT[:3], alpha) if i % 3 == 0 else (*ACCENT2[:3], alpha) if i % 3 == 1 else (*ACCENT3[:3], alpha)
        draw.ellipse([x-size, y-size, x+size, y+size], fill=color)

def draw_grid_lines(img, frame, alpha=15):
    """Subtle animated grid"""
    draw = ImageDraw.Draw(img, 'RGBA')
    offset = int(frame * 0.5) % 60
    for x in range(0, W + 60, 60):
        draw.line([(x - offset, 0), (x - offset, H)], fill=(100, 120, 180, alpha), width=1)
    for y in range(0, H + 60, 60):
        draw.line([(0, y - offset), (W, y - offset)], fill=(100, 120, 180, alpha), width=1)

def draw_rounded_rect(draw, xy, radius, fill, outline=None, width=0):
    """Draw a rounded rectangle"""
    x1, y1, x2, y2 = xy
    if fill:
        draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)
    elif outline:
        draw.rounded_rectangle(xy, radius=radius, outline=outline, width=width)

def draw_glow_circle(img, cx, cy, radius, color, intensity=3):
    """Draw a glowing circle"""
    overlay = Image.new('RGBA', (W, H), (0,0,0,0))
    d = ImageDraw.Draw(overlay)
    for i in range(intensity, 0, -1):
        r = radius + i * 8
        alpha = max(5, int(40 / i))
        d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(*color[:3], alpha))
    d.ellipse([cx-radius, cy-radius, cx+radius, cy+radius], fill=(*color[:3], 180))
    img.paste(Image.alpha_composite(Image.new('RGBA', (W,H), (0,0,0,0)), overlay), (0,0), overlay)

def draw_glow_line(img, p1, p2, color, width=2, glow=4):
    """Draw a glowing line"""
    overlay = Image.new('RGBA', (W, H), (0,0,0,0))
    d = ImageDraw.Draw(overlay)
    for i in range(glow, 0, -1):
        alpha = max(8, int(50 / i))
        d.line([p1, p2], fill=(*color[:3], alpha), width=width + i * 3)
    d.line([p1, p2], fill=(*color[:3], 220), width=width)
    img.paste(Image.alpha_composite(Image.new('RGBA', (W,H), (0,0,0,0)), overlay), (0,0), overlay)

def draw_arrow(img, p1, p2, color, width=2, head_size=12):
    """Draw arrow with head"""
    draw_glow_line(img, p1, p2, color, width)
    # Arrow head
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    length = math.sqrt(dx*dx + dy*dy)
    if length == 0:
        return
    dx /= length
    dy /= length
    # perpendicular
    px, py = -dy, dx
    tip = p2
    left = (tip[0] - dx*head_size + px*head_size*0.5, tip[1] - dy*head_size + py*head_size*0.5)
    right = (tip[0] - dx*head_size - px*head_size*0.5, tip[1] - dy*head_size - py*head_size*0.5)
    overlay = Image.new('RGBA', (W, H), (0,0,0,0))
    d = ImageDraw.Draw(overlay)
    d.polygon([tip, left, right], fill=(*color[:3], 220))
    img.paste(Image.alpha_composite(Image.new('RGBA', (W,H), (0,0,0,0)), overlay), (0,0), overlay)

def text_width(text, font):
    bbox = font.getbbox(text)
    return bbox[2] - bbox[0]

def text_height(text, font):
    bbox = font.getbbox(text)
    return bbox[3] - bbox[1]

def draw_text_centered(draw, y, text, font, fill=WHITE):
    tw = text_width(text, font)
    draw.text(((W - tw) // 2, y), text, font=font, fill=fill)

def draw_text_with_glow(img, pos, text, font, fill=WHITE, glow_color=ACCENT, glow_radius=3):
    """Text with glow effect"""
    overlay = Image.new('RGBA', (W, H), (0,0,0,0))
    d = ImageDraw.Draw(overlay)
    # Glow passes
    for dx in range(-glow_radius, glow_radius+1):
        for dy in range(-glow_radius, glow_radius+1):
            if dx*dx + dy*dy <= glow_radius*glow_radius:
                alpha = max(10, int(40 / max(1, abs(dx) + abs(dy))))
                d.text((pos[0]+dx, pos[1]+dy), text, font=font, fill=(*glow_color[:3], alpha))
    d.text(pos, text, font=font, fill=fill)
    img.paste(Image.alpha_composite(Image.new('RGBA', (W,H), (0,0,0,0)), overlay), (0,0), overlay)

def typewriter(text, t):
    """Return substring of text based on progress t (0..1)"""
    n = int(len(text) * clamp(t))
    return text[:n]

# ── Scene Definitions ─────────────────────────────────
# Timeline (seconds): total ~78s
# Scene 1: Hero Intro          0-8s    (0-240 frames)
# Scene 2: What is OmniShell   8-16s   (240-480)
# Scene 3: Architecture        16-32s  (480-960)
# Scene 4: Agent Swarm         32-44s  (960-1320)
# Scene 5: Example 1           44-52s  (1320-1560)
# Scene 6: Example 2           52-60s  (1560-1800)
# Scene 7: Example 3           60-68s  (1800-2040)
# Scene 8: Tech Stack          68-74s  (2040-2220)
# Scene 9: Outro/CTA           74-80s  (2220-2400)

SCENES = [
    (0,   240,  "hero"),
    (240,  240,  "what_is"),
    (480,  480,  "architecture"),
    (960,  360,  "agent_swarm"),
    (1320, 240,  "example1"),
    (1560, 240,  "example2"),
    (1800, 240,  "example3"),
    (2040, 180,  "techstack"),
    (2220, 180,  "outro"),
]
TOTAL_FRAMES = 2400  # 80 seconds

# ── Transition helper ─────────────────────────────────
def apply_transition(img, frame, scene_start, scene_dur, fade_in=15, fade_out=15):
    """Apply fade in/out at scene boundaries"""
    f = frame - scene_start
    alpha = 1.0
    if f < fade_in:
        alpha = ease_out_cubic(f / fade_in)
    elif f > scene_dur - fade_out:
        alpha = ease_out_cubic((scene_dur - f) / fade_out)
    if alpha < 1.0:
        dark = Image.new('RGBA', (W, H), (*BG_DARK, int((1 - alpha) * 255)))
        img.paste(Image.alpha_composite(img.convert('RGBA'), dark), (0, 0))

# ── Scene Renderers ───────────────────────────────────

def render_hero(img, f, dur):
    """Hero intro with logo reveal and title animation"""
    draw = ImageDraw.Draw(img, 'RGBA')
    draw_particles(img, f, count=50)
    draw_grid_lines(img, f, alpha=10)

    # Pulsing glow circle in center
    pulse = 0.5 + 0.5 * math.sin(f * 0.05)
    glow_r = int(120 + pulse * 40)
    draw_glow_circle(img, W//2, H//2 - 60, glow_r, ACCENT, intensity=5)

    # Terminal icon (animated reveal)
    t_reveal = ease_out_cubic(clamp(progress(f, 0, 45)))
    if t_reveal > 0:
        # Draw terminal bracket >_
        icon_alpha = int(255 * t_reveal)
        icon_scale = 0.5 + 0.5 * t_reveal
        icon_y = int(H//2 - 100 + (1 - t_reveal) * 50)
        icon_text = ">_"
        tw = text_width(icon_text, FONT_HERO)
        draw.text(((W - tw)//2, icon_y - 70), icon_text, font=FONT_HERO,
                  fill=(*ACCENT[:3], icon_alpha))

    # Title: "OmniShell" — slides up with bounce
    t_title = ease_out_back(clamp(progress(f, 20, 40)))
    if t_title > 0:
        title = "OmniShell"
        title_y = int(H//2 - 20 + (1 - t_title) * 100)
        title_alpha = int(255 * min(1, t_title * 1.5))
        tw = text_width(title, FONT_HERO)
        draw_text_with_glow(img, ((W-tw)//2, title_y), title, FONT_HERO,
                           fill=(*WHITE[:3], title_alpha), glow_color=ACCENT)

    # Subtitle — fades in after title
    t_sub = ease_out_cubic(clamp(progress(f, 55, 35)))
    if t_sub > 0:
        sub = "Universal Autonomous Syndicate"
        sub_alpha = int(255 * t_sub)
        tw = text_width(sub, FONT_SUBTITLE)
        draw.text(((W - tw)//2, H//2 + 80), sub, font=FONT_SUBTITLE,
                  fill=(*ACCENT3[:3], sub_alpha))

    # Tagline — typewriter effect
    t_tag = progress(f, 90, 80)
    if t_tag > 0:
        tagline = "Multi-Agent OS & Knowledge Copilot"
        shown = typewriter(tagline, t_tag)
        tw = text_width(shown, FONT_BODY)
        cursor = "█" if int(f * 0.15) % 2 == 0 else ""
        draw.text(((W - text_width(tagline, FONT_BODY))//2, H//2 + 140),
                  shown + cursor, font=FONT_BODY, fill=DIM)

    # Bottom line
    t_bot = ease_out_cubic(clamp(progress(f, 150, 30)))
    if t_bot > 0:
        bot = "github.com/vishwajitvm/OmniShell"
        tw = text_width(bot, FONT_SMALL)
        draw.text(((W-tw)//2, H - 80), bot, font=FONT_SMALL,
                  fill=(*DIM[:3], int(200 * t_bot)))

    # Decorative corner lines
    t_corners = ease_out_cubic(clamp(progress(f, 30, 40)))
    if t_corners > 0:
        line_len = int(80 * t_corners)
        ca = int(120 * t_corners)
        # Top-left
        draw.line([(60, 60), (60 + line_len, 60)], fill=(*ACCENT[:3], ca), width=2)
        draw.line([(60, 60), (60, 60 + line_len)], fill=(*ACCENT[:3], ca), width=2)
        # Top-right
        draw.line([(W-60, 60), (W-60 - line_len, 60)], fill=(*ACCENT[:3], ca), width=2)
        draw.line([(W-60, 60), (W-60, 60 + line_len)], fill=(*ACCENT[:3], ca), width=2)
        # Bottom-left
        draw.line([(60, H-60), (60 + line_len, H-60)], fill=(*ACCENT[:3], ca), width=2)
        draw.line([(60, H-60), (60, H-60 - line_len)], fill=(*ACCENT[:3], ca), width=2)
        # Bottom-right
        draw.line([(W-60, H-60), (W-60 - line_len, H-60)], fill=(*ACCENT[:3], ca), width=2)
        draw.line([(W-60, H-60), (W-60, H-60 - line_len)], fill=(*ACCENT[:3], ca), width=2)


def render_what_is(img, f, dur):
    """What is OmniShell — feature showcase"""
    draw = ImageDraw.Draw(img, 'RGBA')
    draw_particles(img, f, count=25, seed=99)

    # Section title
    t1 = ease_out_cubic(clamp(progress(f, 0, 25)))
    if t1 > 0:
        title = "What is OmniShell?"
        tw = text_width(title, FONT_TITLE)
        x = int((W - tw) // 2 + (1 - t1) * -200)
        draw.text((x, 80), title, font=FONT_TITLE, fill=(*WHITE[:3], int(255*t1)))
        # Underline
        line_w = int(tw * t1)
        draw.line([(x, 145), (x + line_w, 145)], fill=ACCENT, width=3)

    # Description
    t2 = progress(f, 30, 60)
    if t2 > 0:
        desc = "Your intelligent command center that understands intent,"
        desc2 = "plans execution, and runs verified workflows autonomously."
        shown1 = typewriter(desc, clamp(t2 * 2))
        shown2 = typewriter(desc2, clamp(t2 * 2 - 1)) if t2 > 0.5 else ""
        draw.text((160, 190), shown1, font=FONT_BODY, fill=DIM)
        if shown2:
            draw.text((160, 225), shown2, font=FONT_BODY, fill=DIM)

    # Feature cards — 9 capabilities
    features = [
        ("💬", "Q&A", "Instant answers"),
        ("🔍", "System Inspection", "Live diagnostics"),
        ("🌐", "Browser", "Web automation"),
        ("📋", "Multi-step Plan", "Verified workflows"),
        ("⏰", "Reminder", "Smart scheduling"),
        ("🔁", "Recurring", "Automated routines"),
        ("📝", "Plan Only", "Preview first"),
        ("🛡️", "Recovery", "Self-healing"),
        ("🔬", "Research", "Deep analysis"),
    ]

    start_f = 50
    for i, (emoji, name, desc) in enumerate(features):
        delay = i * 12
        t = ease_out_back(clamp(progress(f, start_f + delay, 25)))
        if t <= 0:
            continue

        col = i % 3
        row = i // 3
        card_w, card_h = 480, 120
        gap = 30
        total_w = 3 * card_w + 2 * gap
        base_x = (W - total_w) // 2
        cx = base_x + col * (card_w + gap)
        cy = 290 + row * (card_h + gap)

        # Card slides up
        slide_y = int((1 - t) * 40)
        cy += slide_y
        alpha = int(220 * t)

        draw_rounded_rect(draw, (cx, cy, cx + card_w, cy + card_h),
                         radius=12, fill=(*BG_CARD[:3], alpha), outline=(*ACCENT[:3], int(80*t)), width=1)

        # Emoji
        draw.text((cx + 15, cy + 15), emoji, font=FONT_SUBTITLE, fill=WHITE)
        # Name
        draw.text((cx + 70, cy + 18), name, font=FONT_BODY_B, fill=(*WHITE[:3], alpha))
        # Desc
        draw.text((cx + 70, cy + 52), desc, font=FONT_SMALL, fill=(*DIM[:3], alpha))

        # Progress bar at bottom of card
        bar_t = clamp(progress(f, start_f + delay + 15, 20))
        if bar_t > 0:
            bar_w = int((card_w - 30) * ease_out_cubic(bar_t))
            draw.rounded_rectangle((cx + 15, cy + card_h - 18, cx + 15 + bar_w, cy + card_h - 12),
                                  radius=3, fill=(*ACCENT[:3], int(100*t)))


def render_architecture(img, f, dur):
    """Architecture diagram — animated build-up"""
    draw = ImageDraw.Draw(img, 'RGBA')
    draw_grid_lines(img, f, alpha=6)

    # Title
    t_title = ease_out_cubic(clamp(progress(f, 0, 20)))
    draw.text((80, 40), "System Architecture", font=FONT_TITLE,
              fill=(*WHITE[:3], int(255*t_title)))
    draw.line([(80, 100), (80 + int(400*t_title), 100)], fill=ACCENT, width=3)

    # Architecture layers (left side - vertical flow)
    layers = [
        ("👤 User", "Browser / CLI", ACCENT),
        ("🖥️ Frontend", "Next.js + HBS :3000", (100, 200, 255)),
        ("⚡ API Gateway", "FastAPI :8000", ACCENT3),
        ("🧠 Intent Engine", "Classify → Plan → Route", YELLOW),
        ("🤖 Agent Swarm", "8 Specialized Agents", ACCENT2),
        ("🛡️ Safety Gate", "Policy + Validation", RED),
        ("⚙️ Executor", "Host / Docker :8003", ORANGE),
        ("📊 Result", "Verify + Telemetry", ACCENT3),
    ]

    box_w, box_h = 380, 60
    start_x = 120
    start_y = 140
    gap_y = 12

    for i, (name, desc, color) in enumerate(layers):
        delay = i * 18
        t = ease_out_cubic(clamp(progress(f, 15 + delay, 25)))
        if t <= 0:
            continue

        y = start_y + i * (box_h + gap_y)
        alpha = int(230 * t)
        slide_x = int((1 - t) * -150)

        # Box
        bx = start_x + slide_x
        draw_rounded_rect(draw, (bx, y, bx + box_w, y + box_h),
                         radius=10, fill=(*BG_CARD[:3], alpha),
                         outline=(*color[:3], int(150*t)), width=2)

        # Text
        draw.text((bx + 15, y + 8), name, font=FONT_BODY_B, fill=(*WHITE[:3], alpha))
        draw.text((bx + 15, y + 35), desc, font=FONT_TINY, fill=(*DIM[:3], alpha))

        # Arrow to next
        if i < len(layers) - 1:
            arrow_t = ease_out_cubic(clamp(progress(f, 25 + delay + 10, 15)))
            if arrow_t > 0:
                ax = bx + box_w // 2
                ay1 = y + box_h
                ay2 = int(ay1 + (gap_y) * arrow_t)
                draw_glow_line(img, (ax, ay1), (ax, ay2), color, width=2, glow=2)
                # Arrow head
                if arrow_t > 0.7:
                    overlay = Image.new('RGBA', (W,H), (0,0,0,0))
                    d2 = ImageDraw.Draw(overlay)
                    d2.polygon([(ax, ay2+2), (ax-5, ay2-5), (ax+5, ay2-5)],
                              fill=(*color[:3], int(200*arrow_t)))
                    img.paste(Image.alpha_composite(img.convert('RGBA'), overlay), (0,0), overlay)

    # Right side — Request Control Plane flow
    rcp_t = ease_out_cubic(clamp(progress(f, 120, 30)))
    if rcp_t > 0:
        rx = 600
        ry = 140
        draw.text((rx, ry), "Request Control Plane", font=FONT_SUBTITLE,
                  fill=(*ACCENT[:3], int(255*rcp_t)))

        stages = ["Intent", "Policy", "Plan", "Execute", "Verify"]
        stage_colors = [ACCENT3, ACCENT, YELLOW, ORANGE, ACCENT3]
        stage_x = rx + 20
        for i, (stage, sc) in enumerate(zip(stages, stage_colors)):
            st = ease_out_cubic(clamp(progress(f, 130 + i*15, 20)))
            if st <= 0:
                continue
            sy = ry + 50 + i * 55
            sa = int(255 * st)

            # Stage pill
            pw = 250
            draw_rounded_rect(draw, (stage_x, sy, stage_x + pw, sy + 40),
                             radius=20, fill=(*sc[:3], int(40*st)),
                             outline=(*sc[:3], int(180*st)), width=2)
            draw.text((stage_x + 45, sy + 8), stage, font=FONT_BODY_B,
                      fill=(*WHITE[:3], sa))

            # Status icon
            check_t = clamp(progress(f, 145 + i*15, 10))
            if check_t > 0:
                icon = "✓" if i < 3 else "●" if i == 3 else "○"
                draw.text((stage_x + 12, sy + 8), icon, font=FONT_BODY,
                          fill=(*sc[:3], int(255*check_t)))

            # Connector
            if i < len(stages) - 1:
                ct = ease_out_cubic(clamp(progress(f, 140 + i*15 + 8, 10)))
                if ct > 0:
                    draw_glow_line(img, (stage_x + pw//2, sy + 40),
                                  (stage_x + pw//2, sy + 55), sc, width=1, glow=2)

    # Right side — Data flow
    df_t = ease_out_cubic(clamp(progress(f, 220, 30)))
    if df_t > 0:
        dx = 920
        dy = 140
        draw.text((dx, dy), "Data Layer", font=FONT_SUBTITLE,
                  fill=(*ACCENT2[:3], int(255*df_t)))

        data_items = [
            ("🐘 PostgreSQL", "Scheduled Tasks + Runs"),
            ("🔴 Redis", "Cache + PubSub"),
            ("📁 Host FS", "File Operations"),
            ("🌐 External", "APIs + Services"),
        ]
        for i, (name, desc) in enumerate(data_items):
            dt = ease_out_cubic(clamp(progress(f, 230 + i*15, 20)))
            if dt <= 0:
                continue
            iy = dy + 50 + i * 80
            ia = int(255 * dt)

            draw_rounded_rect(draw, (dx, iy, dx + 380, iy + 65),
                             radius=10, fill=(*BG_CARD[:3], int(200*dt)),
                             outline=(*ACCENT2[:3], int(80*dt)), width=1)
            draw.text((dx + 15, iy + 8), name, font=FONT_BODY_B, fill=(*WHITE[:3], ia))
            draw.text((dx + 15, iy + 36), desc, font=FONT_TINY, fill=(*DIM[:3], ia))

    # Connecting lines between sections
    conn_t = ease_out_cubic(clamp(progress(f, 280, 40)))
    if conn_t > 0:
        # API → RCP
        draw_arrow(img, (500, 300), (620, 200), ACCENT3, width=1, head_size=8)
        # RCP → Agent Swarm layer
        draw_arrow(img, (620, 480), (500, 500), YELLOW, width=1, head_size=8)
        # Agent → Data Layer
        draw_arrow(img, (870, 350), (920, 280), ACCENT2, width=1, head_size=8)

    # "Developed by" watermark
    wm_t = ease_out_cubic(clamp(progress(f, 350, 25)))
    if wm_t > 0:
        draw.text((W - 350, H - 45), "Developed by Vishwajit VM", font=FONT_SMALL,
                  fill=(*DIM[:3], int(150*wm_t)))


def render_agent_swarm(img, f, dur):
    """Agent Swarm — 8 agents in circular layout"""
    draw = ImageDraw.Draw(img, 'RGBA')
    draw_particles(img, f, count=30, seed=77)

    # Title
    t1 = ease_out_cubic(clamp(progress(f, 0, 20)))
    draw.text((W//2 - 220, 40), "8-Agent Swarm", font=FONT_TITLE,
              fill=(*WHITE[:3], int(255*t1)))
    draw.text((W//2 - 260, 100), "Collaborative Intelligence Network", font=FONT_BODY,
              fill=(*DIM[:3], int(255*t1)))

    agents = [
        ("Intent &\nPlanning", "Classify user intent\n& build execution plan", ACCENT),
        ("System\nRecon", "Gather host facts\n& environment info", (100, 200, 255)),
        ("Content\nGeneration", "Synthesize answers\n& documentation", ACCENT3),
        ("Security\nGuard", "Validate safety\n& policy compliance", RED),
        ("Command\nResearch", "Find optimal commands\n& fallback options", YELLOW),
        ("Command\nValidator", "Verify command safety\n& correctness", ORANGE),
        ("Execution\nPlanner", "Sequence & orchestrate\nstep execution", ACCENT2),
        ("Telemetry\nVerifier", "Monitor results\n& verify outcomes", (180, 100, 255)),
    ]

    cx, cy = W // 2, H // 2 + 40
    radius = 320

    # Central hub
    hub_t = ease_out_elastic(clamp(progress(f, 15, 35)))
    if hub_t > 0:
        hub_r = int(60 * hub_t)
        draw_glow_circle(img, cx, cy, hub_r, ACCENT, intensity=4)
        if hub_t > 0.5:
            ha = int(255 * min(1, (hub_t - 0.5) * 3))
            text = "SYNDICATE"
            tw2 = text_width(text, FONT_SMALL_B)
            draw.text((cx - tw2//2, cy - 10), text, font=FONT_SMALL_B,
                      fill=(*WHITE[:3], ha))

    # Agents in circle
    for i, (name, desc, color) in enumerate(agents):
        angle = (2 * math.pi * i / len(agents)) - math.pi / 2
        delay = 30 + i * 15
        t = ease_out_back(clamp(progress(f, delay, 30)))
        if t <= 0:
            continue

        # Orbit rotation (slow)
        orbit_offset = f * 0.003
        angle += orbit_offset

        ax = int(cx + radius * math.cos(angle))
        ay = int(cy + radius * math.sin(angle))

        alpha = int(255 * t)
        scale = t

        # Connection line to center (animated pulse)
        line_t = ease_out_cubic(clamp(progress(f, delay + 15, 15)))
        if line_t > 0:
            # Pulsing dot along the line
            pulse_pos = (f * 0.02 + i * 0.3) % 1.0
            px = int(lerp(cx, ax, pulse_pos))
            py = int(lerp(cy, ay, pulse_pos))
            draw_glow_line(img, (cx, cy), (ax, ay), color, width=1, glow=2)
            draw_glow_circle(img, px, py, 4, color, intensity=2)

        # Agent card
        card_w, card_h = 160, 110
        draw_rounded_rect(draw, (ax - card_w//2, ay - card_h//2,
                                 ax + card_w//2, ay + card_h//2),
                         radius=12, fill=(*BG_CARD[:3], int(220*t)),
                         outline=(*color[:3], int(180*t)), width=2)

        # Agent number
        num_text = str(i + 1)
        draw.text((ax - card_w//2 + 8, ay - card_h//2 + 5), num_text,
                  font=FONT_TAG, fill=(*color[:3], alpha))

        # Agent name (multiline)
        lines = name.split('\n')
        for li, line in enumerate(lines):
            lw = text_width(line, FONT_SMALL_B)
            draw.text((ax - lw//2, ay - 28 + li * 22), line,
                      font=FONT_SMALL_B, fill=(*WHITE[:3], alpha))

        # Description (multiline, smaller)
        desc_lines = desc.split('\n')
        for li, line in enumerate(desc_lines):
            lw = text_width(line, FONT_TINY)
            draw.text((ax - lw//2, ay + 18 + li * 18), line,
                      font=FONT_TINY, fill=(*DIM[:3], int(180*t)))


def render_example(img, f, dur, example_num):
    """Render an example workflow"""
    draw = ImageDraw.Draw(img, 'RGBA')
    draw_particles(img, f, count=15, seed=example_num * 33)

    examples = {
        1: {
            "title": "Example 1: System Inspection",
            "prompt": "Check my system memory and CPU usage",
            "intent": "system_inspection",
            "confidence": "99%",
            "risk": "SAFE",
            "steps": [
                ("free -h | grep Mem:", "RAM usage: 7.5G / 16G"),
                ("top -bn1 -o %CPU | head -5", "CPU: 12% avg, top: chrome 8%"),
                ("vmstat 1 3", "Memory: 47% used, I/O: normal"),
            ],
            "color": ACCENT,
        },
        2: {
            "title": "Example 2: Recurring Workflow",
            "prompt": "Monitor disk usage every 30 minutes",
            "intent": "recurring_workflow",
            "confidence": "97%",
            "risk": "SAFE",
            "steps": [
                ("Schedule: */30 * * * *", "Cron registered in PostgreSQL"),
                ("df -h / | tail -1", "Disk: 45G / 100G (45% used)"),
                ("Auto-alert if > 85%", "Threshold monitoring active"),
            ],
            "color": ACCENT3,
        },
        3: {
            "title": "Example 3: Multi-Step Plan",
            "prompt": "Deploy latest build to staging server",
            "intent": "multi_step_plan",
            "confidence": "95%",
            "risk": "MODERATE",
            "steps": [
                ("git pull origin main", "Fetched latest: 3 commits"),
                ("npm run build --production", "Build successful (2.1s)"),
                ("rsync -avz dist/ staging:/app", "Deployed 47 files"),
            ],
            "color": YELLOW,
        },
    }

    ex = examples[example_num]

    # Title
    t1 = ease_out_cubic(clamp(progress(f, 0, 20)))
    draw.text((100, 50), ex["title"], font=FONT_TITLE, fill=(*ex["color"][:3], int(255*t1)))
    draw.line([(100, 115), (100 + int(500*t1), 115)], fill=ex["color"], width=3)

    # Prompt card (simulating user input)
    t2 = ease_out_cubic(clamp(progress(f, 15, 25)))
    if t2 > 0:
        # User prompt bubble
        prompt_y = 150
        prompt_w = 700
        draw_rounded_rect(draw, (100, prompt_y, 100 + prompt_w, prompt_y + 70),
                         radius=15, fill=(*BG_CARD[:3], int(220*t2)),
                         outline=(*ex["color"][:3], int(100*t2)), width=1)
        # Prompt text with typewriter
        pt = progress(f, 20, 40)
        prompt_shown = typewriter(ex["prompt"], pt)
        cursor = "█" if int(f * 0.15) % 2 == 0 and pt < 1 else ""
        draw.text((130, prompt_y + 10), "$ " + prompt_shown + cursor,
                  font=FONT_MONO, fill=(*ACCENT3[:3], int(255*t2)))
        draw.text((130, prompt_y + 40), "User Input",
                  font=FONT_TINY, fill=(*DIM[:3], int(180*t2)))

    # Intent classification result
    t3 = ease_out_cubic(clamp(progress(f, 55, 20)))
    if t3 > 0:
        iy = 240
        draw_rounded_rect(draw, (100, iy, 500, iy + 90),
                         radius=10, fill=(*BG_CARD[:3], int(200*t3)),
                         outline=(*ACCENT[:3], int(80*t3)), width=1)
        draw.text((120, iy + 10), f"Intent: {ex['intent']}", font=FONT_BODY_B,
                  fill=(*WHITE[:3], int(255*t3)))
        draw.text((120, iy + 40), f"Confidence: {ex['confidence']}", font=FONT_SMALL,
                  fill=(*ACCENT3[:3], int(255*t3)))
        risk_color = ACCENT3[:3] if ex['risk'] == 'SAFE' else YELLOW[:3]
        draw.text((120, iy + 62), f"Risk: {ex['risk']}", font=FONT_SMALL,
                  fill=(*risk_color, int(255*t3)))

        # Safety gate badge
        draw_rounded_rect(draw, (520, iy + 10, 750, iy + 50),
                         radius=20, fill=(*ACCENT3[:3], int(40*t3)),
                         outline=(*ACCENT3[:3], int(150*t3)), width=2)
        draw.text((540, iy + 18), "🛡️ Safety Gate ✓", font=FONT_BODY_B,
                  fill=(*ACCENT3[:3], int(255*t3)))

    # Execution steps
    for i, (cmd, result) in enumerate(ex["steps"]):
        delay = 80 + i * 40
        t = ease_out_cubic(clamp(progress(f, delay, 25)))
        if t <= 0:
            continue

        sy = 360 + i * 130
        slide_x = int((1 - t) * 100)

        # Step card
        draw_rounded_rect(draw, (100 + slide_x, sy, W - 100, sy + 110),
                         radius=10, fill=(*BG_CARD[:3], int(200*t)),
                         outline=(*ex["color"][:3], int(60*t)), width=1)

        # Step number
        draw_rounded_rect(draw, (115 + slide_x, sy + 10, 155 + slide_x, sy + 40),
                         radius=15, fill=(*ex["color"][:3], int(80*t)))
        draw.text((125 + slide_x, sy + 12), str(i+1), font=FONT_BODY_B,
                  fill=(*WHITE[:3], int(255*t)))

        # Command
        cmd_t = progress(f, delay + 5, 25)
        cmd_shown = typewriter(cmd, cmd_t)
        draw.text((170 + slide_x, sy + 12), "$ " + cmd_shown,
                  font=FONT_MONO_SM, fill=(*ACCENT[:3], int(255*t)))

        # Result
        res_t = clamp(progress(f, delay + 20, 15))
        if res_t > 0:
            draw.text((170 + slide_x, sy + 45), "→ " + result,
                      font=FONT_SMALL, fill=(*ACCENT3[:3], int(255*res_t)))

            # Progress bar
            bar_w = int(400 * ease_out_cubic(res_t))
            draw.rounded_rectangle((170 + slide_x, sy + 78, 170 + slide_x + bar_w, sy + 85),
                                  radius=3, fill=(*ex["color"][:3], int(80*t)))

        # Check mark when done
        done_t = clamp(progress(f, delay + 30, 8))
        if done_t > 0:
            draw.text((W - 160, sy + 15), "✓ Done", font=FONT_BODY_B,
                      fill=(*ACCENT3[:3], int(255*done_t)))

    # Right side: Agent discussion preview
    disc_t = ease_out_cubic(clamp(progress(f, 60, 25)))
    if disc_t > 0 and f < dur - 20:
        dx = W - 480
        dy = 150
        draw_rounded_rect(draw, (dx, dy, dx + 380, dy + 180),
                         radius=12, fill=(*BG_CARD[:3], int(180*disc_t)),
                         outline=(*ACCENT2[:3], int(80*disc_t)), width=1)
        draw.text((dx + 15, dy + 10), "🤖 Syndicate Discussion", font=FONT_SMALL_B,
                  fill=(*ACCENT2[:3], int(255*disc_t)))

        agents_talking = [
            "Intent Agent: Classified ✓",
            "Security: Policy check ✓",
            "Cmd Research: Optimal cmds found",
            "Validator: All safe ✓",
            "Planner: Sequenced steps",
        ]
        for i, line in enumerate(agents_talking):
            at = ease_out_cubic(clamp(progress(f, 70 + i * 8, 12)))
            if at > 0:
                draw.text((dx + 15, dy + 40 + i * 25), line, font=FONT_TINY,
                          fill=(*DIM[:3], int(200*at)))


def render_techstack(img, f, dur):
    """Tech Stack visualization"""
    draw = ImageDraw.Draw(img, 'RGBA')
    draw_particles(img, f, count=20, seed=55)

    t1 = ease_out_cubic(clamp(progress(f, 0, 20)))
    tw = text_width("Tech Stack", FONT_TITLE)
    draw.text(((W - tw)//2, 50), "Tech Stack", font=FONT_TITLE,
              fill=(*WHITE[:3], int(255*t1)))

    stacks = [
        ("Backend", [
            ("FastAPI", "Python async API framework", ACCENT3),
            ("PostgreSQL 15", "JSONB task persistence", (100, 150, 255)),
            ("Redis 7", "Cache + real-time PubSub", RED),
        ]),
        ("Frontend", [
            ("NestJS", "Server framework", ACCENT),
            ("Handlebars", "Template rendering", YELLOW),
            ("Tailwind CSS", "Utility-first styling", ACCENT),
        ]),
        ("Infrastructure", [
            ("Docker Compose", "Container orchestration", (100, 200, 255)),
            ("Host Executor", "Native OS bridge", ORANGE),
            ("Cron Engine", "Scheduled workflows", ACCENT2),
        ]),
    ]

    for si, (section, items) in enumerate(stacks):
        col_x = 100 + si * 600
        sec_t = ease_out_cubic(clamp(progress(f, 15 + si * 20, 20)))
        if sec_t > 0:
            draw.text((col_x, 130), section, font=FONT_SUBTITLE,
                      fill=(*ACCENT[:3], int(255*sec_t)))
            draw.line([(col_x, 175), (col_x + int(200*sec_t), 175)], fill=ACCENT, width=2)

        for ii, (name, desc, color) in enumerate(items):
            delay = 25 + si * 20 + ii * 12
            t = ease_out_back(clamp(progress(f, delay, 20)))
            if t <= 0:
                continue

            iy = 200 + ii * 100
            alpha = int(255 * t)
            slide = int((1 - t) * 60)

            draw_rounded_rect(draw, (col_x, iy + slide, col_x + 500, iy + 80 + slide),
                             radius=10, fill=(*BG_CARD[:3], int(200*t)),
                             outline=(*color[:3], int(120*t)), width=2)

            # Colored dot
            draw.ellipse((col_x + 15, iy + 22 + slide, col_x + 27, iy + 34 + slide),
                         fill=(*color[:3], alpha))

            draw.text((col_x + 40, iy + 12 + slide), name, font=FONT_BODY_B,
                      fill=(*WHITE[:3], alpha))
            draw.text((col_x + 40, iy + 45 + slide), desc, font=FONT_SMALL,
                      fill=(*DIM[:3], int(180*t)))

    # Docker compose visual at bottom
    dc_t = ease_out_cubic(clamp(progress(f, 100, 30)))
    if dc_t > 0:
        dy = 560
        draw.text(((W - text_width("Docker Compose Services", FONT_BODY_B))//2, dy),
                  "Docker Compose Services", font=FONT_BODY_B,
                  fill=(*ACCENT[:3], int(255*dc_t)))

        services = [
            ("backend", ":8000", ACCENT3),
            ("frontend", ":3000", ACCENT),
            ("postgres", ":5432", (100, 150, 255)),
            ("redis", ":6379", RED),
            ("executor", ":8003", ORANGE),
        ]
        total_sw = len(services) * 200 + (len(services) - 1) * 40
        base_sx = (W - total_sw) // 2

        for i, (sname, port, color) in enumerate(services):
            st = ease_out_back(clamp(progress(f, 110 + i * 10, 20)))
            if st <= 0:
                continue
            sx = base_sx + i * 240
            sy = dy + 50 + int((1-st) * 30)
            sa = int(255 * st)

            draw_rounded_rect(draw, (sx, sy, sx + 190, sy + 80),
                             radius=12, fill=(*BG_CARD[:3], int(200*st)),
                             outline=(*color[:3], int(150*st)), width=2)
            draw.text((sx + 15, sy + 10), sname, font=FONT_BODY_B,
                      fill=(*WHITE[:3], sa))
            draw.text((sx + 15, sy + 42), port, font=FONT_MONO_SM,
                      fill=(*color[:3], sa))

            # Connection lines between services
            if i < len(services) - 1:
                ct = clamp(progress(f, 115 + i * 10, 15))
                if ct > 0:
                    draw_glow_line(img, (sx + 190, sy + 40), (sx + 240, sy + 40),
                                  DIM, width=1, glow=1)


def render_outro(img, f, dur):
    """Outro with CTA and developer attribution"""
    draw = ImageDraw.Draw(img, 'RGBA')
    draw_particles(img, f, count=50, seed=42)
    draw_grid_lines(img, f, alpha=8)

    # Large glow
    pulse = 0.5 + 0.5 * math.sin(f * 0.04)
    draw_glow_circle(img, W//2, H//2 - 40, int(180 + pulse * 30), ACCENT, intensity=5)
    draw_glow_circle(img, W//2, H//2 - 40, int(100 + pulse * 20), ACCENT2, intensity=3)

    # Logo text
    t1 = ease_out_elastic(clamp(progress(f, 0, 40)))
    if t1 > 0:
        title = "OmniShell"
        tw = text_width(title, FONT_HERO)
        title_y = int(H//2 - 120 + (1-t1) * 80)
        draw_text_with_glow(img, ((W-tw)//2, title_y), title, FONT_HERO,
                           fill=(*WHITE[:3], int(255*t1)), glow_color=ACCENT)

    # Tagline
    t2 = ease_out_cubic(clamp(progress(f, 25, 25)))
    if t2 > 0:
        sub = "Your Autonomous Command Center"
        tw = text_width(sub, FONT_SUBTITLE)
        draw.text(((W-tw)//2, H//2), sub, font=FONT_SUBTITLE,
                  fill=(*ACCENT3[:3], int(255*t2)))

    # GitHub link
    t3 = ease_out_cubic(clamp(progress(f, 45, 20)))
    if t3 > 0:
        url = "github.com/vishwajitvm/OmniShell"
        tw = text_width(url, FONT_URL)
        uy = H//2 + 60

        # URL background pill
        draw_rounded_rect(draw, ((W-tw)//2 - 20, uy - 5, (W+tw)//2 + 20, uy + 35),
                         radius=20, fill=(*BG_CARD[:3], int(200*t3)),
                         outline=(*ACCENT[:3], int(150*t3)), width=2)
        draw.text(((W-tw)//2, uy), url, font=FONT_URL,
                  fill=(*ACCENT[:3], int(255*t3)))

    # Developer credit
    t4 = ease_out_cubic(clamp(progress(f, 60, 20)))
    if t4 > 0:
        dev = "Developed by Vishwajit VM"
        tw = text_width(dev, FONT_SUBTITLE)
        draw.text(((W-tw)//2, H//2 + 130), dev, font=FONT_SUBTITLE,
                  fill=(*WHITE[:3], int(255*t4)))

    # Star CTA
    t5 = ease_out_cubic(clamp(progress(f, 80, 20)))
    if t5 > 0:
        cta = "⭐ Star on GitHub • 🚀 Try it Today"
        tw = text_width(cta, FONT_BODY)
        draw.text(((W-tw)//2, H//2 + 200), cta, font=FONT_BODY,
                  fill=(*YELLOW[:3], int(255*t5)))

    # Corner decorations
    t6 = ease_out_cubic(clamp(progress(f, 10, 30)))
    if t6 > 0:
        ll = int(100 * t6)
        ca = int(150 * t6)
        draw.line([(40, 40), (40 + ll, 40)], fill=(*ACCENT[:3], ca), width=2)
        draw.line([(40, 40), (40, 40 + ll)], fill=(*ACCENT[:3], ca), width=2)
        draw.line([(W-40, 40), (W-40 - ll, 40)], fill=(*ACCENT2[:3], ca), width=2)
        draw.line([(W-40, 40), (W-40, 40 + ll)], fill=(*ACCENT2[:3], ca), width=2)
        draw.line([(40, H-40), (40 + ll, H-40)], fill=(*ACCENT3[:3], ca), width=2)
        draw.line([(40, H-40), (40, H-40 - ll)], fill=(*ACCENT3[:3], ca), width=2)
        draw.line([(W-40, H-40), (W-40 - ll, H-40)], fill=(*ACCENT[:3], ca), width=2)
        draw.line([(W-40, H-40), (W-40, H-40 - ll)], fill=(*ACCENT[:3], ca), width=2)


# ── Main Frame Renderer ──────────────────────────────

def render_frame(frame_num):
    """Render a single frame"""
    img = Image.new('RGBA', (W, H), BG_DARK + (255,))
    draw_gradient_bg(img)

    for scene_start, scene_dur, scene_name in SCENES:
        if frame_num < scene_start or frame_num >= scene_start + scene_dur:
            continue

        f = frame_num - scene_start  # local frame

        if scene_name == "hero":
            render_hero(img, f, scene_dur)
        elif scene_name == "what_is":
            render_what_is(img, f, scene_dur)
        elif scene_name == "architecture":
            render_architecture(img, f, scene_dur)
        elif scene_name == "agent_swarm":
            render_agent_swarm(img, f, scene_dur)
        elif scene_name == "example1":
            render_example(img, f, scene_dur, 1)
        elif scene_name == "example2":
            render_example(img, f, scene_dur, 2)
        elif scene_name == "example3":
            render_example(img, f, scene_dur, 3)
        elif scene_name == "techstack":
            render_techstack(img, f, scene_dur)
        elif scene_name == "outro":
            render_outro(img, f, scene_dur)

        # Apply scene transitions
        apply_transition(img, frame_num, scene_start, scene_dur)
        break

    # Bottom progress bar (always visible)
    draw = ImageDraw.Draw(img, 'RGBA')
    prog_w = int((W - 80) * (frame_num / TOTAL_FRAMES))
    draw.rounded_rectangle((40, H - 8, 40 + prog_w, H - 2), radius=3,
                          fill=(*ACCENT[:3], 100))

    return img.convert('RGB')


# ── Main ──────────────────────────────────────────────

def main():
    print(f"🎬 OmniShell Video Generator")
    print(f"   Resolution: {W}x{H} @ {FPS}fps")
    print(f"   Total frames: {TOTAL_FRAMES} ({TOTAL_FRAMES/FPS:.1f}s)")
    print(f"   Output: {OUTPUT}")
    print()

    # Clean frame dir
    if os.path.exists(FRAME_DIR):
        shutil.rmtree(FRAME_DIR)
    os.makedirs(FRAME_DIR, exist_ok=True)

    # Generate frames
    for i in range(TOTAL_FRAMES):
        img = render_frame(i)
        img.save(os.path.join(FRAME_DIR, f"frame_{i:05d}.png"), "PNG")

        if i % FPS == 0:
            sec = i // FPS
            scene = "?"
            for ss, sd, sn in SCENES:
                if ss <= i < ss + sd:
                    scene = sn
                    break
            print(f"   [{sec:3d}s / {TOTAL_FRAMES//FPS}s] Rendering: {scene}  ({i}/{TOTAL_FRAMES})")

    print(f"\n✅ All {TOTAL_FRAMES} frames generated")
    print(f"🎞️  Encoding MP4 with ffmpeg...")

    # Encode with ffmpeg
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(FPS),
        "-i", os.path.join(FRAME_DIR, "frame_%05d.png"),
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-vf", "scale=1920:1080",
        OUTPUT
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ ffmpeg error: {result.stderr}")
        sys.exit(1)

    print(f"✅ Video saved: {OUTPUT}")

    # File size
    size_mb = os.path.getsize(OUTPUT) / (1024 * 1024)
    print(f"📦 File size: {size_mb:.1f} MB")

    # Clean frames
    shutil.rmtree(FRAME_DIR)
    print("🧹 Cleaned temp frames")


if __name__ == "__main__":
    main()

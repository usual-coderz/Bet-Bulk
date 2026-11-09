import asyncio
import base64
import logging
import math
import random
from dataclasses import dataclass

import cv2
import numpy as np

import dom

log = logging.getLogger("captcha")

MIN_W, MAX_W = 22, 110
MIN_H, MAX_H = 22, 110


@dataclass
class SlideResult:
    ok: bool
    gap_cx: int = -1
    distance: int = -1


def detect_gap(img_bgr: np.ndarray) -> int:
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.dilate(cv2.Canny(gray, 60, 160), np.ones((3, 3), np.uint8), iterations=2)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h, w = gray.shape
    best, best_score = None, 0.0

    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        if not (MIN_W <= cw <= MAX_W and MIN_H <= ch <= MAX_H):
            continue
        if not (0.5 <= cw / ch <= 2.0):
            continue
        area = cv2.contourArea(c)
        if area < 400:
            continue
        if x < w * 0.10:
            continue
        score = (area / (cw * ch)) * (x / w)
        if score > best_score:
            best, best_score = (x, y, cw, ch), score

    if not best:
        raise LookupError("gap not found")

    x, y, cw, ch = best
    log.debug("gap box x=%d y=%d w=%d h=%d", x, y, cw, ch)
    return x + cw // 2


def _trajectory(distance: int, steps: int = 42):
    out = []
    for i in range(steps + 1):
        t = i / steps
        ease = t * t * (3 - 2 * t)
        out.append((distance * ease,
                    math.sin(t * math.pi * 2) * random.uniform(0.4, 2.2) * (1 - t)))
    return out


async def _shot(img_loc) -> np.ndarray | None:
    try:
        raw = await img_loc.screenshot(scale="css")   # 1 px == 1 CSS px
    except TypeError:
        raw = await img_loc.screenshot()
    except Exception as e:
        log.warning("captcha screenshot fail: %s", e)
        return None
    return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)


async def slide(page, sel: dict, pad_right: int = 0,
                x_hint: int | None = None) -> SlideResult:
    w = await dom.find_captcha(page)
    if not w:
        log.warning("captcha widget nahi mila")
        return SlideResult(False)
    img_l, handle_l = w

    img = await _shot(img_l)
    if img is None:
        return SlideResult(False)

    try:
        gap_cx = detect_gap(img)
    except LookupError:
        if x_hint is None:
            log.warning("gap detect nahi hua, hint bhi nahi")
            return SlideResult(False)
        gap_cx = x_hint
        log.info("CV fail, solver hint use: %d", gap_cx)

    ib = await img_l.bounding_box()
    hb = await handle_l.bounding_box()
    if not ib or not hb:
        log.warning("bounding box nahi mila")
        return SlideResult(False)

    sx = hb["x"] + hb["width"] / 2
    sy = hb["y"] + hb["height"] / 2
    distance = int((ib["x"] + gap_cx) - sx) - pad_right
    log.info("gap_cx=%d distance=%d pad=%d", gap_cx, distance, pad_right)

    if abs(distance) <= 6:
        log.info("piece pehle se sahi jagah par hai")
        return SlideResult(True, gap_cx, 0)
    if distance <= 8:
        log.warning("distance chhota: %d", distance)
        return SlideResult(False, gap_cx, distance)

    await page.mouse.move(sx, sy)
    await asyncio.sleep(random.uniform(0.15, 0.4))
    await page.mouse.down()
    await asyncio.sleep(random.uniform(0.08, 0.2))

    for dx, dy in _trajectory(distance):
        await page.mouse.move(sx + dx, sy + dy, steps=1)
        await asyncio.sleep(random.uniform(0.006, 0.022))

    over = random.randint(3, 8)
    await page.mouse.move(sx + distance + over, sy, steps=3)
    await asyncio.sleep(random.uniform(0.08, 0.18))
    await page.mouse.move(sx + distance - random.randint(0, 2), sy, steps=2)
    await asyncio.sleep(random.uniform(0.1, 0.25))
    await page.mouse.up()

    log.info("drag complete distance=%d", distance)
    return SlideResult(True, gap_cx, distance)


async def screenshot_b64(page, sel: dict) -> str | None:
    w = await dom.find_captcha(page)
    if not w:
        return None
    try:
        raw = await w[0].screenshot(scale="css")
    except TypeError:
        raw = await w[0].screenshot()
    except Exception:
        return None
    return base64.b64encode(raw).decode()
"""Repeated mid-band DCT origin marker, independent of file metadata.

Designed for full-size images; resizing/cropping are not guaranteed to survive.
The public fixed marker is a source hint, not a cryptographic signature.
"""
import hashlib
import numpy as np
from PIL import Image
from scipy.fft import dctn, idctn

_BITS = np.unpackbits(np.frombuffer(hashlib.sha256(b'ZZZTMA POWERBYZZZHE. DCT v1').digest()[:16], dtype=np.uint8))
_COUNT = 384
_STRENGTH = 24.


def _locations(width, height):
    rows, cols = height // 8, width // 8
    if rows * cols < _COUNT:
        return None
    # Uniform positions; deterministic, no filesystem or random global state.
    positions = np.linspace(0, rows * cols - 1, _COUNT, dtype=int)
    return (positions // cols) * 8, (positions % cols) * 8


def _blocks(rgb, locations):
    yy, xx = locations
    return rgb[yy[:, None, None] + np.arange(8)[None, :, None],
               xx[:, None, None] + np.arange(8)[None, None, :], :]


def _embed_legacy(image):
    locations = _locations(*image.size)
    if locations is None:
        return image.copy()
    alpha = image.getchannel('A') if 'A' in image.getbands() else None
    rgb = np.asarray(image.convert('RGB'), dtype=np.float32).copy()
    blocks = _blocks(rgb, locations)
    luminance = blocks @ np.array([.299, .587, .114], dtype=np.float32)
    coefficients = dctn(luminance, axes=(-2, -1), norm='ortho')
    a, b = coefficients[:, 2, 3].copy(), coefficients[:, 3, 2].copy()
    signs = np.tile(_BITS, 3).astype(np.float32) * 2 - 1
    adjustment = np.maximum(0, _STRENGTH - signs * (a - b)) * signs / 2
    coefficients[:, 2, 3] += adjustment
    coefficients[:, 3, 2] -= adjustment
    delta = idctn(coefficients, axes=(-2, -1), norm='ortho') - luminance
    updated = np.clip(np.rint(blocks + delta[..., None]), 0, 255)
    yy, xx = locations
    rgb[yy[:, None, None] + np.arange(8)[None, :, None],
        xx[:, None, None] + np.arange(8)[None, None, :], :] = updated
    result = Image.fromarray(rgb.astype(np.uint8), 'RGB')
    if alpha is not None: result.putalpha(alpha)
    return result


def _detect_legacy(image):
    locations = _locations(*image.size)
    if locations is None: return dict(detected=False, score=0.)
    rgb = np.asarray(image.convert('RGB'), dtype=np.float32)
    luminance = _blocks(rgb, locations) @ np.array([.299, .587, .114], dtype=np.float32)
    coefficients = dctn(luminance, axes=(-2, -1), norm='ortho')
    votes = (coefficients[:, 2, 3] > coefficients[:, 3, 2]).reshape(3, 128)
    bits = votes.sum(axis=0) >= 2
    score = float(np.mean(bits == _BITS))
    return dict(detected=score >= .94, score=score)


def embed(image, machine_code=None):
    from .robust_watermark import embed as robust_embed
    return robust_embed(_embed_legacy(image), machine_code)


def detect(image, *, extract_machine=False):
    legacy = _detect_legacy(image)
    if legacy['detected'] and not extract_machine: return {**legacy, 'scheme': 'legacy_dct_v1'}
    from .robust_watermark import detect as robust_detect
    robust = robust_detect(image)
    if legacy['detected'] and not robust['detected']: return {**legacy,'scheme':'legacy_dct_v1'}
    return robust if robust['detected'] or robust['score'] > legacy['score'] else {**legacy,'scheme':'legacy_dct_v1'}

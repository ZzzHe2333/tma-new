"""Read-only robustness audit of an existing exported image (not a watermark upgrade)."""
from pathlib import Path
import hashlib
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PIL import Image
import numpy as np
from scipy.fft import dctn
from tma_app import frequency_watermark as wm, image_provenance as origin


def main(source, destination):
    destination.mkdir(parents=True, exist_ok=False)
    original_bytes = source.read_bytes()
    source_hash = hashlib.sha256(original_bytes).hexdigest()
    with Image.open(source) as image:
        image.load()
        rgb = image.convert('RGB')
    rows = []

    def check(name, path, method):
        with Image.open(path) as candidate:
            candidate.load()
            frequency = wm.detect(candidate)
            locations = wm._locations(*candidate.size)
            luminance = wm._blocks(np.asarray(candidate.convert('RGB'), dtype=np.float32), locations) @ np.array([.299,.587,.114], dtype=np.float32)
            coefficients = dctn(luminance, axes=(-2,-1), norm='ortho')
            bits = (coefficients[:,2,3] > coefficients[:,3,2]).reshape(3,128).sum(axis=0) >= 2
            errors = (round((1-frequency['score'])*128) if frequency.get('scheme') == 'normalized_dct_v2'
                      else int(np.count_nonzero(bits != wm._BITS)))
            size = candidate.size
        row = dict(test=name, method=method, file=str(path), size=size,
                   sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                   frequency=frequency, bit_errors=errors, total_bits=128,
                   fully_recovered=errors == 0, identification=origin.verify_image(path))
        rows.append(row)
        print(name, frequency, 'bit_errors', errors, flush=True)

    original = destination/'original.png'; original.write_bytes(original_bytes)
    check('原始 PNG', original, '原始EXE导出文件逐字节复制；直接检测DCT与元数据')
    old_key = origin._KEY
    try:
        origin._KEY = b'wrong-test-key-not-the-real-key'
        wrong = origin.verify_image(original)
    finally:
        origin._KEY = old_key
    rows.append(dict(test='错误密钥', method='仅对元数据HMAC使用错误密钥；DCT没有独立密钥接口',
                     identification=wrong, rejected=wrong['status'] == 'modified', dct_key_test='not_applicable'))
    jpeg = destination/'jpeg-q85.jpg'
    rgb.save(jpeg, format='JPEG', quality=85, subsampling=2)
    check('JPEG Q85', jpeg, 'Pillow JPEG quality=85, 4:2:0，去除元数据')

    from PySide6.QtWidgets import QApplication, QLabel
    from PySide6.QtGui import QPixmap
    from PySide6.QtCore import Qt
    app = QApplication.instance() or QApplication([])
    for name, size, filename in [('截图 1:1', rgb.size, 'screenshot-1to1.png'),
                                 ('截图 1280×720', (1280,720), 'screenshot-fit.png')]:
        label = QLabel()
        label.setStyleSheet('background:white;')
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setFixedSize(*size)
        pixmap = QPixmap(str(source)).scaled(*size, Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation)
        label.setPixmap(pixmap)
        label.show(); app.processEvents()
        target = destination/filename
        assert label.grab().save(str(target))
        label.close()
        check(name, target, '离屏Qt窗口渲染后grab截图，非系统桌面截图；无元数据')

    width, height = rgb.size
    resized = destination/'half-then-restore.png'
    rgb.resize((width//2,height//2), Image.Resampling.LANCZOS).resize(rgb.size, Image.Resampling.LANCZOS).save(resized)
    check('缩至50%再恢复', resized, 'Lanczos缩小至一半，再用Lanczos恢复原尺寸')
    cropped = destination/'crop-10-percent.png'
    rgb.crop((round(width*.05), round(height*.05), round(width*.95), round(height*.95))).save(cropped)
    check('裁剪10%', cropped, '横纵方向各去掉10%（四边各5%），不恢复尺寸；剩余面积约81%')
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    report = dict(source=str(source), source_sha256=source_hash, size=rgb.size,
                  detection_threshold=.94, watermark='固定128位来源标记，不含可还原文字，无独立DCT密钥',
                  source_unchanged=True, tests=rows)
    (destination/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


if __name__ == '__main__':
    main(Path(sys.argv[1]), Path(sys.argv[2]))

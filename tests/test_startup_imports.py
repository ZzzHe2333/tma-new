"""Keep unused computation dependencies off the main window's startup path."""
import os
from pathlib import Path
import subprocess
import sys


def test_empty_window_then_first_calculation(tmp_path):
    # A fresh interpreter matters: other numerical tests have imported SciPy.
    code = r'''
import sys
import numpy as np
from tma_app.app import QApplication
from tma_app.classic import ClassicMainWindow
app = QApplication([])
window = ClassicMainWindow()
window.show()
app.processEvents()
assert window.isVisible() and window.classic_actions['Open1'].isEnabled()
assert not any(name == 'scipy' or name.startswith('scipy.') for name in sys.modules)
from tma_app.numerics import analyze, process_signal
x = np.arange(11, dtype=float)
y = 3*x*x + 2*x + 7
original = y.copy()
result = analyze(x, y, 'integral', 0., 10.)
assert 'scipy.integrate' in sys.modules
assert 'scipy.signal' not in sys.modules
from scipy.integrate import trapezoid
baseline = y[0] + (y[-1]-y[0])*x/10
assert result['integral'] == trapezoid(y-baseline, x)
smoothed = process_signal(x, y, 'smooth', 5)
from scipy.signal import savgol_filter
np.testing.assert_array_equal(smoothed, savgol_filter(y, 5, polyorder=3))
np.testing.assert_array_equal(y, original)
window.close()
'''
    env = dict(os.environ, LOCALAPPDATA=str(tmp_path), QT_QPA_PLATFORM='offscreen',
               ZZZHE_TMA_ACCOUNT_REGISTRY='0', TMA_MASS_XLSX='')
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code],
                            cwd=Path(__file__).resolve().parents[1], env=env,
                            capture_output=True, text=True, encoding='utf-8', timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr

# 請在這裡貼上 main.py 的程式碼
import sys
import gc
# pyrefly: ignore [missing-import]
from PyQt6.QtWidgets import QApplication
# pyrefly: ignore [missing-import]
from PyQt6.QtCore import Qt

from model import CastellaModel
from view import CastellaView
from presenter import CastellaPresenter

if __name__ == '__main__':
    # 開啟高解析度螢幕支援
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    
    # 使用現代感的主題
    app.setStyle("Fusion") 
    
    # ===============================================
    # Optimization: Adjust GC Threshold
    # Increase Generation 0 threshold to 50,000 to prevent frequent GC pauses
    # during high-frequency packet generation.
    # ===============================================
    _, gen1, gen2 = gc.get_threshold()
    gc.set_threshold(50000, gen1, gen2)

    # 建立 MVP 三本柱
    model = CastellaModel()
    view = CastellaView()
    presenter = CastellaPresenter(model, view)
    
    # 啟動介面
    view.show()
    
    # ===============================================
    # Optimization: GC Freeze
    # Freeze static PyQt UI nodes and variables after initialization
    # to reduce background GC scanning overhead and frame drops.
    # ===============================================
    gc.collect(2)
    gc.freeze()
    print("System optimization complete: GC configured and objects frozen.")
    
    # 進入應用程式事件迴圈
    sys.exit(app.exec())
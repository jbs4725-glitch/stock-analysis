# -*- coding: utf-8 -*-
"""클라우드 배포 엔트리 (ASCII 모듈명) — Render/Hugging Face/gunicorn 호환.
   실제 앱 로직은 stock_app.py(=웹앱.py 사본)에 있다."""
import os
import stock_app
app = stock_app.app   # gunicorn app:app / docker 모두 이 변수를 사용

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "7860"))   # HF=7860, Render=$PORT
    app.run(host="0.0.0.0", port=port, threaded=True)

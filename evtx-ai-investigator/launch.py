"""PyInstaller .exe 진입점.

src/app.py 를 직접 진입점으로 쓰면 상대 import(from .paths …)가 부모 패키지 없이
실행돼 ImportError 가 난다. 이 런처는 src 를 패키지로 import 해 그 문제를 피한다.
"""
from src.app import main

if __name__ == "__main__":
    main()

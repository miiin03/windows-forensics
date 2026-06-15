# vendor/ — 번들 런타임 (커밋 제외)

첫 실행 셋업(`src/setup.py`)이 Ollama 를 설치할 때 쓰는 **무인 인스톨러**를 여기 둔다.

## OllamaSetup.exe (권장)
- 다운로드: https://ollama.com/download/OllamaSetup.exe
- 이 파일을 `vendor/OllamaSetup.exe` 로 저장하면:
  - 첫 실행 시 **다운로드 없이** Ollama 무인 설치(`/VERYSILENT /SUPPRESSMSGBOXES`) → 오프라인 안정성↑.
- 없으면 `setup.py` 가 위 공식 URL 에서 자동 다운로드(인터넷 필요).

## 용량
- 인스톨러 수십 MB. 모델(qwen2.5:7b, 4.7GB)은 항상 첫 실행 시 `ollama pull` 로 받는다(여기 두지 않음).

## .exe 패키징
```bash
pyinstaller --onefile --windowed \
  --add-data "ui;ui" \
  --add-data "vendor;vendor" \
  src/app.py
```
> 모델까지 완전 오프라인(B안)으로 묶으려면 별도 인스톨러(Inno Setup 등)로 `~/.ollama/models` 동봉 검토.

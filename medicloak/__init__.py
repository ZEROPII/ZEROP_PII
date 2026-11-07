# MediCloak 운영 모드 패키지: python -m medicloak (cli.py)
#
# 서버 코드는 webdemo/backend/를 함께 쓴다 (같은 화면 · 같은 API). 다른 점은 켜는 방법뿐이다.
#   python -m webdemo     데모: 로그인 없음 · 결정적 응답기 · 메모리 기록
#   python -m medicloak   운영: 로그인 · 역할 분리 · DB(가상 EMR · 대화 · 감사 기록) · .env의 실제 LLM

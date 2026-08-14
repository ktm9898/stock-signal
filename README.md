# Stock Signal Tracker & Screener (stock-signal)

KOSPI 200 종목 대상 ADX 과매도 반전 매수 신호 및 민감 매도 신호 감시 웹 대시보드 및 자동화 스크리너입니다.

## 주요 기능
1. **KOSPI 200 매수 신호 스크리닝**:
   - `ADX >= 25` 이상 상태에서 `-DI`가 `ADX` 하향 돌파 시 반전 매수 후보 포착
   - `RSI <= 40` 중첩 여부 및 거래량 반응(1.2배)에 따른 우선순위(1단계: 매수 추천 / 2단계: 적극 매수 / 3단계: 강력 매수) 산정
2. **보유 종목 민감 매도 신호 감시**:
   - 사용자 보유 등록 종목 대상 3단계 매도 신호 (1단계: 매도 추천 [RSI >= 60], 2단계: 적극 매도 [+DI >= 20.0 꺾임], 3단계: 강력 매도 [-DI 확대])
3. **자동화 스케줄링 및 수집 연동**:
   - Google Apps Script(GAS) 시간 기반 트리거 및 웹 앱 연동을 통한 수집 & 구글 시트 DB 업데이트

## 기술 스택
- **Engine/Backend**: Python, PyKRX, pandas, ta (Technical Analysis Library)
- **Database/Bridge**: Google Sheets API / Google Apps Script
- **Scheduler**: Google Apps Script Time-driven Triggers / GitHub Actions (workflow_dispatch)
- **Frontend**: Single Page HTML Web App (Vanilla JS, Modern CSS, Dark Mode Trading UI)

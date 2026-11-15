기술스택

backend python, fastapi  
frontend tyepscript vite  
db postgresql  
in-memory redis  


- 주식 모의 거래서 서비스 기획
- 증권거래소 API를 연결하여 정해진 시간마다 특정 기업 리스트의 가격을 쌓습니다.
- 오더북은 없습니다
- 기존 predict-market의 유저 정보를 사용합니다.
- 실제 거래에 맞춰 거래가 이뤄집니다. 하지만 교환하는 방식이 아니기 때문에 매수, 매도는 실행하면 항상 시행됩니다.
- predict-market 처럼 리더보드를 갖춥니다. 연간 / 월간 / 실시간 / 이벤트
- 
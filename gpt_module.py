"""Reusable server-side GPT module for BSSBU and future projects."""
import json, os, urllib.error, urllib.request
def _load_env(path=None):
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if not os.path.exists(path): return
    with open(path,encoding='utf-8') as f:
        for raw in f:
            line=raw.strip()
            if not line or line.startswith('#') or '=' not in line: continue
            key,val=line.split('=',1); os.environ.setdefault(key.strip(),val.strip().strip('"').strip("'"))
class GPTModule:
    def __init__(self):
        _load_env(); self.api_key=os.getenv('OPENAI_API_KEY','').strip(); self.model=os.getenv('OPENAI_MODEL','gpt-4o-mini').strip(); self.base_url=os.getenv('OPENAI_BASE_URL','https://api.openai.com/v1/chat/completions').strip()
    @property
    def available(self): return bool(self.api_key)
    async def sql_from_text(self, instruction, schema):
        if not self.available: raise RuntimeError('OPENAI_API_KEY가 서버 .env에 설정되지 않았습니다.')
        system='''너는 SQLite 관리자용 SQL 생성기다. 사용자의 자연어 요청을 SQLite SQL 한 문장으로 변환하라. 제공된 스키마에 존재하는 테이블과 컬럼만 사용하라. 결과는 마크다운, 설명, 코드펜스 없이 SQL 한 문장만 출력하라. 사용자가 조회를 원하면 SELECT를, 데이터 추가/수정 요청이면 INSERT/UPDATE를 사용하라. DROP, ALTER, ATTACH, DETACH, VACUUM, REINDEX는 만들지 마라. 요청이 모호하면 가장 안전한 SELECT를 만들고, 존재하지 않는 테이블을 임의로 만들지 마라.'''
        prompt=f'현재 SQLite 스키마:\n{json.dumps(schema,ensure_ascii=False)}\n\n자연어 요청:\n{instruction}'
        body=json.dumps({'model':self.model,'messages':[{'role':'system','content':system},{'role':'user','content':prompt}],'temperature':0,'max_tokens':400}).encode()
        req=urllib.request.Request(self.base_url,data=body,headers={'Authorization':f'Bearer {self.api_key}','Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=45) as response: data=json.loads(response.read().decode())
            return data['choices'][0]['message']['content'].strip().replace('```sql','').replace('```','').strip()
        except (urllib.error.HTTPError,urllib.error.URLError,KeyError,json.JSONDecodeError) as exc: raise RuntimeError(f'GPT SQL 생성 실패: {exc}') from exc
    async def reply(self,message,detections,events,messages,kind='chat'):
        if not self.available: raise RuntimeError('OPENAI_API_KEY가 서버 .env에 설정되지 않았습니다.')
        if kind == 'summary':
            system='너는 BSSBU AI Studio의 장면 해석 AI다. 제공된 COCO-SSD 탐지 결과와 이벤트를 단순 나열하지 말고, 운영자 관점에서 현재 장면의 의미, 주의할 점, 다음 행동을 한국어로 3~5문장으로 요약하라. 관측되지 않은 사실은 추측하지 말라.'
        elif kind == 'vision_insight':
            system='너는 BSSBU AI Studio의 이미지 분석 인사이트 AI다. 이미지는 제공되지 않았고, 브라우저가 계산한 OpenCV 계열 통계(밝기 평균, 명암 표준편차, 채도, 16구간 밝기 히스토그램, 엣지 밀도)와 전이학습 분류 결과만 제공된다. 이 수치를 해석해 노출·대비·색감·디테일·분류 신뢰도를 설명하고, 사진 정리나 보정에 도움이 되는 다음 행동을 한국어 3~5문장으로 제안하라. 이미지 내용을 추측하거나 객체를 단정하지 말라.'
        else:
            system='너는 BSSBU AI Studio의 일반 GPT 대화 모듈이다. 사용자의 질문에 일반적인 지식과 자연스러운 대화로 답하라. 카메라 탐지 컨텍스트는 관련 질문일 때만 참고하고, 관련 없으면 무시하라. 확실하지 않은 사실은 추측하지 말고 한국어로 자연스럽게 답하라.'
        context={'detections':detections[-30:],'events':events[-12:],'recent_messages':messages[-10:]}
        prompt=f'현재 관측 컨텍스트:\n{json.dumps(context,ensure_ascii=False)}\n\n운영자 요청:\n{message}'
        body=json.dumps({'model':self.model,'messages':[{'role':'system','content':system},{'role':'user','content':prompt}],'temperature':.2,'max_tokens':500}).encode()
        req=urllib.request.Request(self.base_url,data=body,headers={'Authorization':f'Bearer {self.api_key}','Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=45) as response: data=json.loads(response.read().decode())
            return data['choices'][0]['message']['content'].strip()
        except (urllib.error.HTTPError,urllib.error.URLError,KeyError,json.JSONDecodeError) as exc: raise RuntimeError(f'GPT 요청 실패: {exc}') from exc

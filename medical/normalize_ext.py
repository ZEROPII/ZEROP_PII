"""
정규화 확장 v0.11.3 [본 연구 설정, 2026-11-03] — 전달 묶음 normalize_bridge(v0.11.1)는 그대로 두고 상속으로 더한다.

r3_rule · holdout_1 실행 기록의 정규화 실패를 보고 넣은 규칙이다. 원칙은 묶음과 같다:
기록보다 구체적으로 세지 않는다(모르면 넓은 노드로, 그래도 모르면 반영하지 않음).

1. 날짜 기간 (v0.11.2, 팀 보류검증 패키지의 normalize_bridge_v0.11.2.patch와 같은 규칙)
   '2018-03-09~24', '2016-02-01~현재', '2012-10-02 시작' → 시작 역할이면 '~' 왼쪽, 종료 역할이면 오른쪽(빠진 연·월은 왼쪽에서 채움).
   근거: TimeML/TIMEX3는 기간을 시작점 · 끝점이 있는 구간으로 다룬다.
2. '/'로 이은 이름 (v0.11.2) 'Gingivitis/Gingival disease' → 진단 · 시술 · 관리 계획은 나눠서 각각 찾는다 (NCBI disease corpus의 composite mention).
3. 나이 범위 '93-96세'처럼 5 · 10세 구간이 아닌 범위 → 감싸는 가장 좁은 5 · 10세 구간 (팀 채점 단계 3과 같은 규칙).
4. 성별 한 글자 '남' · '여' · '남자' · '여자'.
5. 이름 일부로 찾기: 'ibuprofen', 'metformin hydrochloride 500 MG', 'Removal of supragingival plaque'처럼
   별칭표에 그대로 없는 이름은, 그 낱말을 모두 담은 별칭들의 **가장 가까운 공통 상위 노드**로 반영한다.
   예: 'ibuprofen' → 모든 ibuprofen 제품의 공통 상위(ATC M01AE01 ibuprofen). 공통 상위가 뿌리(ANY)면 반영하지 않는다.
   이름 일부만 말했으니 그 이름이 가리킬 수 있는 것보다 좁게 세지 않는다.

v0.11.4 [실험, 2026-11-16, 브랜치 exp/turn0-normalize] — 실제 LLM 실행(455b09e~172c384) 10개에서 턴 0 · 다시 확인이
'귀속된 미매핑'(REFUSAL_UNMAPPED · UNMAPPED_ATTRIBUTED)으로 막힌 값 367개를 보고 넣은 규칙이다. 원칙은 같다:
기록보다 구체적으로 세지 않는다. 시간 · 나이 값이 아닌 말은 미매핑으로 막지 않고 보류(PENDING)로 둔다(k에 들어갈 정보가 없다).
'(비공개)'가 들어간 값은 건드리지 않는다(edec6bb 규칙 그대로).
6. 기간 표기: '1992-12-13 시작, 지속', '1985-06-04 이후 지속', '2011년부터 지속' → 날짜만.
   '2016-2022', '2022년 11월-2023년 2월', '1966년 4월~8월' → 1번 규칙과 같이 시작 역할은 왼쪽, 종료 역할은 오른쪽(빠진 연도는 왼쪽에서).
   그 역할 · 날짜의 일(DAY) 노드가 없으면 같은 역할의 월 → 연 노드로 넓힌다(없으면 미매핑 그대로).
7. 기간 칸에 시간 값이 없는 말: '약 8일'(복용 길이) · '1월'(연도 없는 달) · '지속 중' · '여러 시점에서 진단'처럼
   숫자 날짜도 이름도 없는 말 → 보류. 길이 · 연도 없는 달은 노드가 없어 k에 넣을 수 없다.
   ('Unspecified convulsions 시작일'처럼 사건 이름이 들어간 값은 보류하지 않는다.)
   '51세 당시', '29세 시 진단', '37세' → 그 사건 당시 나이(AGE)로 본다(문서의 '위 진단 당시 나이'와 같은 뜻).
8. 나이 표기: '70세대' → 70대, '0세~3세' → 0~3세, '약 3세' · '15세경' → 감싸는 10세 구간(어림이라 5세 구간보다 넓게).
   '20세 이상'처럼 한쪽이 열린 범위 · '중년 초기'처럼 숫자가 없는 말 → 보류.
9. 한국어 · 묶음 이름: '고혈압·대사증후군', 'Gingivitis & Gingival disease', '… 및 …' → 2번 규칙처럼 나눠 찾는다.
   한국어 일반 이름(고혈압, 당뇨, 빈혈, 골절, 항생제, 치과 시술 등)은 아래 표의 넓은 노드(ICD 구역 · 장, ATC 2단계, ICD-PCS 부위)로.
   '빈혈'처럼 여러 종류를 함께 가리키는 말은 그 종류를 모두 감싸는 노드로 둔다(구체적인 하나로 좁히지 않는다).
10. 속성 교차: 시술(PROC)로 뽑힌 'Respiratory therapy'처럼 시술 별칭에는 없고 관리 계획(PLAN) 별칭에 정확히 있으면 PLAN으로(반대도 같음).
    진단(DX)으로 뽑힌 'Routine antenatal care'처럼 진단 별칭에 없고 관리 계획 · 시술 별칭에 정확히 하나로 있으면 그쪽으로.
    'Respiratory therapy care plan' → 'care plan'을 뗀 이름으로 찾는다.
11. 지역 칸의 '기록됨' · '비공개' · '확인됨'처럼 장소가 아닌 말 → 보류.

v0.11.5-exp [실험, 2026-11-16] — 한국어 의료 이름 사전(9-1번, 진단 · 약 · 시술 · 관리 계획 약 200개)을 더했다.
  한국어 이름은 영어 이름으로 바꾼 뒤 영어로 말했을 때와 같은 규칙으로 찾는다. 사전에 없는 말은 그대로 미매핑이다
  (연구 하네스는 이런 값을 답 전체 거절 대신 그 값만 가린다: medical/session.py).
  성별 '여아' · '남아', 나이 칸의 연도 범위('1985-2025' → 보류), '48세 (진단 당시 37-42세)' → 앞의 나이.
"""
from __future__ import annotations

import re

from medical.bundle.normalize_bridge import Normalizer

VERSION = "medical/normalize_ext v0.11.5-exp"
_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
_SEX = {"남": "남성", "남자": "남성", "여": "여성", "여자": "여성", "남아": "남성", "여아": "여성", "소년": "남성", "소녀": "여성",
        "남자아이": "남성", "여자아이": "여성", "남성 환자": "남성", "여성 환자": "여성"}
PARTIAL_ATTRS = ("DX", "PROC", "MED", "PLAN")

# 9. 한국어 일반 이름 → 넓은 노드 (노드표에 있는 것만 쓴다. 없으면 이 규칙은 그냥 지나간다)
KO_GENERAL = {
    "DX": {
        "고혈압": "DX_ICD_SECTION_I10-I1A", "당뇨": "DX_ICD_SECTION_E08-E13", "당뇨병": "DX_ICD_SECTION_E08-E13",
        "골절": "DX_ICD_CHAPTER_19", "신부전": "DX_ICD_SECTION_N17-N19",
        "만성 신장병": "DX_ICD_SECTION_N17-N19", "심장질환": "DX_ICD_CHAPTER_9", "심장 질환": "DX_ICD_CHAPTER_9",
        "급성 기관지염": "DX_ICD_CODE_J20", "인후염": "DX_ICD_CODE_J02", "급성 인후염": "DX_ICD_CODE_J02",
        "연쇄구균성 인후염": "DX_ICD_CODE_J020", "대사증후군": "DX_ICD_CODE_E8881",
        "치주질환": "DX_ICD_CODE_K05", "치주 질환": "DX_ICD_CODE_K05",
        "암": "DX_ICD_CHAPTER_2", "종양": "DX_ICD_CHAPTER_2", "심혈관 질환": "DX_ICD_CHAPTER_9",
        "다중 심혈관 질환": "DX_ICD_CHAPTER_9", "조기 심장질환": "DX_ICD_CHAPTER_9",
    },
    "MED": {
        "항생제": "MED_ATC_J01", "해열·진통 약물": "MED_ATC_N02", "해열진통제": "MED_ATC_N02", "진통제": "MED_ATC_N02",
        "당뇨 관리 약물": "MED_ATC_A10", "당뇨약": "MED_ATC_A10", "당뇨병 약물": "MED_ATC_A10",
        "항경련제": "MED_ATC_N03", "antiepileptic drugs": "MED_ATC_N03",
    },
    "PROC": {
        "치과 시술": "PROC_GROUP_0_C", "치아 시술": "PROC_GROUP_0_C", "치과 치료": "PROC_GROUP_0_C",
        "치아 충전": "PROC_GROUP_0_C", "치아 플라크 제거": "PROC_GROUP_0_C", "치석 제거": "PROC_GROUP_0_C",
        "치아 플라크": "PROC_GROUP_0_C", "치석": "PROC_GROUP_0_C", "스케일링": "PROC_GROUP_0_C",
    },
}
# 9-1. 한국어 의료 이름 → 영어 이름(별칭표 그대로 찾기) 또는 노드. 기록된 실행 · Synthea 자주 나오는 진단 · 약 · 시술 · 관리 계획.
#      영어 이름은 영어로 말했을 때와 똑같은 규칙으로 찾는다(정확히 있으면 그 노드, 없으면 4 · 5번 규칙). 못 찾으면 그냥 지나간다.
KO_EN = {
    "DX": {
        "빈혈": "Anemia", "치은염": "Gingivitis", "잇몸 질환": "Gingival disease", "잇몸질환": "Gingival disease", "잇몸병": "Gingival disease",
        "기관지염": "Acute bronchitis", "충치": "Primary dental caries", "치아우식": "Primary dental caries",
        "치아 우식": "Primary dental caries", "치아우식증": "Primary dental caries", "만성 부비동염": "Chronic sinusitis",
        "만성부비동염": "Chronic sinusitis", "부비동염": "sinusitis", "축농증": "sinusitis", "급성 세균성 부비동염": "Acute bacterial sinusitis",
        "치아 감염": "Infection of tooth", "허혈성 심장질환": "Ischemic heart disease", "허혈성 심질환": "Ischemic heart disease",
        "허혈성 심장 질환": "Ischemic heart disease", "치아 상실": "Loss of teeth", "열상": "Laceration - injury",
        "발 열상": "Laceration of foot", "손 열상": "Laceration of hand", "얼굴 열상": "Facial laceration", "안면 열상": "Facial laceration",
        "전완 열상": "Laceration of forearm", "중이염": "Otitis media", "고지혈증": "Hyperlipidemia", "이상지질혈증": "Hyperlipidemia",
        "당뇨병성 신장질환": "Disorder of kidney due to diabetes mellitus", "당뇨병성 신증": "Disorder of kidney due to diabetes mellitus",
        "당뇨 신장병": "Disorder of kidney due to diabetes mellitus", "뇌진탕": "Concussion injury of brain",
        "제2형 당뇨병": "Diabetes mellitus type 2", "2형 당뇨병": "Diabetes mellitus type 2", "2형 당뇨": "Diabetes mellitus type 2",
        "제2형 당뇨": "Diabetes mellitus type 2", "고중성지방혈증": "Hypertriglyceridemia", "만성 신장병": "DX_ICD_CODE_N18",
        "만성 신장질환": "DX_ICD_CODE_N18", "만성신질환": "DX_ICD_CODE_N18", "만성 신질환": "DX_ICD_CODE_N18", "만성 콩팥병": "DX_ICD_CODE_N18",
        "만성신장병": "DX_ICD_CODE_N18", "만성 신장병 3기": "Chronic kidney disease stage 3", "만성 신장병 4기": "Chronic kidney disease stage 4",
        "대장 용종": "Polyp of colon", "대장 폴립": "Polyp of colon", "손목 염좌": "Sprain of wrist", "발목 염좌": "Sprain of ankle",
        "매복 사랑니": "Impacted molars", "매복치": "Impacted molars", "골다공증": "Osteoporosis", "약물 과다복용": "Overdose", "과다복용": "Overdose",
        "목 손상": "Injury of neck", "편타 손상": "Whiplash injury to neck", "채찍질 손상": "Whiplash injury to neck", "편두통": "migraine",
        "무릎 골관절염": "Osteoarthritis of knee", "고관절 골관절염": "Osteoarthritis of hip", "골관절염": "osteoarthritis",
        "퇴행성 관절염": "osteoarthritis", "수면장애": "Sleep disorder", "수면 장애": "Sleep disorder", "천식": "Asthma",
        "소아 천식": "Childhood asthma", "쇄골 골절": "Fracture of clavicle", "전완 골절": "Fracture of forearm",
        "팔 골절": "Fracture of forearm", "발목 골절": "Fracture of ankle", "늑골 골절": "Fracture of rib", "갈비뼈 골절": "Fracture of rib",
        "고관절 골절": "Closed fracture of hip", "뼈 골절": "Fracture of bone", "자간증": "eclampsia", "고혈당": "Hyperglycemia", "화상": "burn",
        "치조염": "Alveolitis of jaw", "건성 치조염": "Alveolitis of jaw", "말기 신부전": "End-stage renal disease",
        "말기 신장병": "End-stage renal disease", "말기 신장질환": "End-stage renal disease", "폐렴": "Pneumonia", "섬유근육통": "Fibromyalgia",
        "전립선 종양": "Neoplasm of prostate", "전립선암": "Neoplasm of prostate", "뇌전증": "Epilepsy", "간질": "Epilepsy",
        "알레르기 비염": "allergic rhinitis", "알레르기성 비염": "allergic rhinitis", "심근경색": "DX_ICD_CODE_I21",
        "심근 경색": "DX_ICD_CODE_I21", "급성 심근경색": "DX_ICD_CODE_I21", "충수염": "Appendicitis", "맹장염": "Appendicitis",
        "주의력결핍": "Child attention deficit disorder", "주의력 결핍 장애": "Child attention deficit disorder",
        "ADHD": "Child attention deficit disorder", "심방세동": "Atrial fibrillation", "폐암": "DX_ICD_SECTION_C30-C39",
        "대장암": "Malignant neoplasm of colon", "결장암": "Malignant neoplasm of colon", "뇌졸중": "Cerebrovascular accident",
        "중풍": "Cerebrovascular accident", "심부정맥 혈전증": "venous thrombosis", "심부 정맥 혈전증": "venous thrombosis",
        "우울증": "DX_ICD_CODE_F32", "주요우울장애": "DX_ICD_CODE_F32", "갑상선기능저하증": "hypothyroidism",
        "갑상선 기능 저하증": "hypothyroidism", "패혈성 쇼크": "Septic shock", "급성 담낭염": "Acute cholecystitis", "담낭염": "cholecystitis",
        "대동맥판 협착증": "Aortic valve stenosis", "대동맥판막 협착증": "Aortic valve stenosis", "승모판 역류": "Mitral valve regurgitation",
        "승모판 역류증": "Mitral valve regurgitation", "백혈병": "Leukemia, disease", "급성 호흡부전": "Acute respiratory failure",
        "본태성 고혈압": "Essential hypertension", "전당뇨": "Prediabetes", "당뇨 전단계": "Prediabetes", "당뇨병 전단계": "Prediabetes",
        "공복혈당장애": "Prediabetes", "급성 인두염": "Acute pharyngitis", "코로나19": "covid-19", "코로나": "covid-19",
        "요로감염": "urinary tract infection", "요로 감염": "urinary tract infection", "심부전": "heart failure", "협심증": "angina",
        "골절상": "Fracture of bone", "자궁외임신": "Tubal pregnancy", "유산": "miscarriage", "계류유산": "Blighted ovum",
    },
    "MED": {
        "아세트아미노펜": "acetaminophen", "타이레놀": "acetaminophen", "이부프로펜": "ibuprofen", "나프록센": "naproxen", "아목시실린": "amoxicillin",
        "페니실린": "penicillin", "세티리진": "cetirizine", "로라타딘": "loratadine", "메트포르민": "metformin", "인슐린": "MED_ATC_A10A",
        "리시노프릴": "lisinopril", "암로디핀": "amlodipine", "히드로클로로티아지드": "hydrochlorothiazide", "하이드로클로로티아지드": "hydrochlorothiazide",
        "심바스타틴": "simvastatin", "아토르바스타틴": "atorvastatin", "니트로글리세린": "nitroglycerin", "클로피도그렐": "clopidogrel", "와파린": "warfarin",
        "황산철": "ferrous sulfate", "철분제": "MED_ATC_B03A", "플루티카손": "fluticasone", "알부테롤": "albuterol", "살부타몰": "albuterol",
        "레보티록신": "levothyroxine", "프레드니손": "prednisone", "메토프롤롤": "metoprolol", "디펜히드라민": "diphenhydramine",
        "덱스트로메토르판": "dextromethorphan", "독시라민": "doxylamine", "불소": "sodium fluoride", "불화나트륨": "sodium fluoride",
        "카바마제핀": "carbamazepine", "클로나제팜": "clonazepam", "디아제팜": "diazepam", "알렌드로네이트": "alendronate", "날록손": "naloxone",
        "펜타닐": "fentanyl", "옥시코돈": "oxycodone", "하이드로코돈": "hydrocodone", "트라마돌": "tramadol", "세팔렉신": "cephalexin",
        "독시사이클린": "doxycycline", "니트로푸란토인": "nitrofurantoin", "아지트로마이신": "azithromycin", "해열제": "MED_ATC_N02B",
        "소염진통제": "MED_ATC_M01A", "비스테로이드성 소염제": "MED_ATC_M01A", "항히스타민제": "MED_ATC_R06", "스타틴": "MED_ATC_C10AA",
        "고지혈증약": "MED_ATC_C10", "혈압약": "MED_ATC_C", "고혈압약": "MED_ATC_C", "항고혈압제": "MED_ATC_C", "항응고제": "MED_ATC_B01A",
        "이뇨제": "MED_ATC_C03", "베타차단제": "MED_ATC_C07", "흡입기": "MED_ATC_R03", "천식약": "MED_ATC_R03", "항우울제": "MED_ATC_N06A",
        "항불안제": "MED_ATC_N05B", "수면제": "MED_ATC_N05C", "피임약": "MED_ATC_G03A", "경구 피임약": "MED_ATC_G03A",
        "구강 건강 관리 약물": "MED_ATC_A01", "구강 관리 약물": "MED_ATC_A01", "마약성 진통제": "MED_ATC_N02A", "오피오이드": "MED_ATC_N02A",
    },
    "PROC": {
        "관상동맥중재술": "coronary", "관상동맥 중재술": "coronary", "경피적 관상동맥 중재술": "coronary", "관상동맥 스텐트": "coronary", "발치": "extraction",
        "치아 발치": "extraction", "대장내시경": "colonoscopy", "대장 내시경": "colonoscopy", "혈액투석": "hemodialysis",
    },
    "PLAN": {
        "물리치료": "Physiotherapy", "호흡 치료": "Respiratory therapy", "호흡치료": "Respiratory therapy",
        "당뇨 자가관리": "Diabetes self management plan", "자가 관리": "Self-care interventions", "상처 관리": "wound care",
        "골절 관리": "fracture care", "화상 관리": "burn care",
    },
}
_COMPOSITE = re.compile(r"\s*(?:·|&|\s및\s|/)\s*")
_DURATION = re.compile(r"^(약|대략|총)?\s*\d{1,3}(\s*[-~]\s*\d{1,3})?\s*(일|주|주일|개월|달|시간)(간|째)?(\s*(동안|정도))?$")
_MONTH_ONLY = re.compile(r"^\d{1,2}\s*월(\s*경)?$")
_AGE_AT = re.compile(r"^(\d{1,3})\s*세(\s*(당시|때|시|무렵|경))?(\s*(진단|시행|시작|처방|발병))?$")
_AGE_SPAN = re.compile(r"^(\d{1,3})\s*세?\s*(?:[~\-]|부터)\s*(\d{1,3})\s*세\s*(사이|까지)?(\s*(당시|때|에))?$")
_NOT_PLACE = {"기록됨", "비공개", "확인됨", "기록 있음", "정보 없음", "미상"}
_NOT_SPECIFIC = {"기타", "기타 질환", "기타 진단", "여러 질환", "다수", "없음", "미상"}
_SUPPRESSED = "(비공개)"


class NormalizerV2(Normalizer):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._tok_index = None

    # 1. 날짜 기간 -----------------------------------------------------------------------
    def _period(self, raw, role):
        s = str(raw).strip()
        if _SUPPRESSED not in s:
            s = re.sub(r"[\s,]*(지속\s*중|지속|계속|현재까지)$", "", s)                  # 6. '… 시작, 지속'
            s = re.sub(r"^(\d{4})(년)?\s*-\s*(\d{4})(년)?$", r"\1~\3", s)               # 6. '2016-2022'
            s = re.sub(r"^(\d{4}년\s*\d{1,2}월)\s*-\s*(\d{4}년\s*\d{1,2}월)$", r"\1~\2", s)
        s = re.sub(r"\s*(시작|부터|이후|경부터)$", "", s)
        if "~" in s and role and _SUPPRESSED not in s:
            left, right = [x.strip() for x in s.split("~", 1)]
            ml = re.match(r"^(\d{4})년", left)
            if ml and re.fullmatch(r"\d{1,2}\s*월(\s*\d{1,2}\s*일)?", right):         # 6. '1966년 4월~8월'
                s = left + "~" + ml.group(1) + "년 " + right
        s = self._ko_date(s)
        if "~" in s and role:
            left, right = [x.strip() for x in s.split("~", 1)]
            if role.endswith("_END") and right and not re.search(r"현재|지속", right):
                m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", left)
                if m and re.fullmatch(r"\d{1,2}", right):
                    s = f"{m.group(1)}-{m.group(2)}-{int(right):02d}"
                elif m and re.fullmatch(r"\d{1,2}-\d{1,2}", right):
                    s = f"{m.group(1)}-" + "-".join(f"{int(x):02d}" for x in right.split("-"))
                else:
                    s = right
            else:
                s = left
        s = self._ko_date(s)
        nid, st = super()._period(s, role)
        if st == "UNMAPPED" and role and _SUPPRESSED not in s:                           # 6. 일 노드가 없으면 월 → 연
            m = re.fullmatch(r"(\d{4})-(\d{1,2})(?:-(\d{1,2}))?",
                             s.replace("년", "-").replace("월", "").replace("일", "").replace(" ", "").rstrip("-"))
            if m:
                basis = "DATE" if role.startswith(("CONDITION", "CAREPLAN")) else "UTC"
                y, mo, d = m.groups()
                for cand in ([f"PERIOD_{role}_{basis}_MONTH_{y}-{int(mo):02d}"] if d else []) + [f"PERIOD_{role}_{basis}_YEAR_{y}"]:
                    if cand in self.node:
                        self._period_note = "DATE_NODE_MISSING_TO_COARSER"
                        return cand, "MAPPED"
        return nid, st

    @staticmethod
    def _ko_date(s):
        """6. '2017년 5월 24일' · '2017년 5월'을 '2017-05-24' · '2017-05'로 (묶음 규칙은 '년 월 일' 사이 공백이 있으면 읽지 못한다)."""
        def one(x):
            m = re.fullmatch(r"\s*(\d{4})\s*년\s*(\d{1,2})\s*월(?:\s*(\d{1,2})\s*일)?\s*", x)
            if not m:
                return x
            y, mo, d = m.groups()
            return f"{y}-{int(mo):02d}" + (f"-{int(d):02d}" if d else "")
        return "~".join(one(x) for x in s.split("~")) if "~" in s else one(s)

    # 2 · 4. 표현 다듬기 ---------------------------------------------------------------------
    def _variants(self, att, raw):
        yield from super()._variants(att, raw)
        s = str(raw).strip()
        if "/" in s and att in ("DX", "PROC", "PLAN"):
            for part in s.split("/"):
                if part.strip():
                    yield part.strip(), "SLASH_SPLIT"
        if att in ("DX", "PROC", "PLAN", "MED") and _SUPPRESSED not in s and re.search(r"·|&|\s및\s", s):   # 9.
            for part in _COMPOSITE.split(s):
                if part.strip():
                    yield part.strip(), "COMPOSITE_SPLIT"
        if att == "PLAN" and re.search(r"\s+care plan$", s, re.I):                     # 10.
            yield re.sub(r"\s+care plan$", "", s, flags=re.I), "CARE_PLAN_SUFFIX"
        if att == "SEX" and s in _SEX:
            yield _SEX[s], "SEX_SHORT"

    # 3. 나이 범위 ---------------------------------------------------------------------------
    def _age(self, raw):
        r0 = str(raw).strip()
        if _SUPPRESSED not in r0:                                                       # 8.
            r0 = re.sub(r"(\d)0세대$", r"\g<1>0대", r0)
            r0 = re.sub(r"(\d)\s*(세|살)\s*([~\-])", r"\1\3", r0)
            r0 = re.sub(r"^(\d{1,3})\s*(세|살)?\s*부터\s*(\d{1,3})\s*(세|살)?\s*(사이|까지)?$", r"\1-\3세", r0)
            m = re.fullmatch(r"(약|대략)\s*(\d{1,3})\s*(세|살)|(\d{1,3})\s*(세|살)\s*(경|쯤|무렵|전후)", r0)
            if m:
                a = int(m.group(2) or m.group(4))
                return f"AGE10_{a // 10 * 10}"
        raw = r0
        nid = super()._age(raw)
        if nid:
            return nid
        m = re.fullmatch(r"(\d{1,3})[~\-](\d{1,3})(세|살)?", str(raw).replace(" ", ""))
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a <= b and a // 5 == b // 5:
                return f"AGE5_{a // 5 * 5}"
            if a <= b and a // 10 == b // 10:
                return f"AGE10_{a // 10 * 10}"
            if a < b and _SUPPRESSED not in str(raw):
                # 8-1. 5 · 10세 구간을 넘는 범위('36-44세')는 대상 AI가 사건 당시 나이들을 처음~끝으로 묶어 말한 것이다.
                #      기록된 실행 12건에서 시작 · 끝 나이 모두 그 환자의 실제 사건 당시 나이였다(12/12).
                #      1번 규칙(기간의 시작 역할 → 왼쪽)과 같이 시작 나이를 그 사건 당시 나이로 센다. 끝 나이는 세지 않는다(덜 세는 쪽).
                self._age_note = "AGE_RANGE_START"
                return f"AGE_Y{a}"
        return None

    # 5. 이름 일부 → 공통 상위 노드 -------------------------------------------------------------
    def _lookup(self, att, raw):
        hits, how = super()._lookup(att, raw)
        if hits or att not in PARTIAL_ATTRS:
            return hits, how
        s = str(raw).strip()
        if _SUPPRESSED in s:
            return set(), ""
        parts = [s] + ([p.strip() for p in _COMPOSITE.split(s) if p.strip()] if _COMPOSITE.search(s) else [])
        for part in parts:                                                              # 9. 한국어 일반 이름
            key = part.lower()
            nid = KO_GENERAL.get(att, {}).get(key) or KO_GENERAL.get(att, {}).get(re.sub(r"\s*(시술|치료|처치)$", "", key))
            if nid and nid in self.node:
                return {nid}, "KO_GENERAL" if part == s else "KO_GENERAL_PART"
        for part in parts:                                                              # 9-1. 한국어 의료 이름 → 영어 이름
            hit = self._ko_en(att, part)
            if hit:
                return {hit}, "KO_TERM" if part == s else "KO_TERM_PART"
        for part in parts:
            lca = self._partial(att, part)
            if lca:
                return {lca}, "TOKEN_SUBSET_LCA" if part == s else "TOKEN_SUBSET_LCA_PART"
        return set(), ""

    def _ko_en(self, att, part):
        tab = KO_EN.get(att) or {}
        key = part.strip()
        cands = [key, key.replace(" ", ""), re.sub(r"\s*(진단|병력|증상|소견|치료제|약물|약)$", "", key)]
        en = next((tab[c] for c in cands if c in tab), None)
        if en is None:
            en = next((v for k, v in tab.items() if k.replace(" ", "") in cands[1:2]), None)
        if not en:
            return None
        if en in self.node:
            return en
        hits, _ = Normalizer._lookup(self, att, en)
        if len(hits) == 1:
            return next(iter(hits))
        if len(hits) > 1:
            return self._chain_top(hits)
        return self._partial(att, en)

    # 7 · 10 · 11. 시간 값 아닌 말 · 나이로 말한 기간 · 속성 교차 · 장소 아닌 말 -------------------------------------
    def normalize(self, ob, response_text, query_text=""):
        att, raw = ob.get("attribute"), str(ob.get("raw_value", "")).strip()
        self._age_note = None
        if _SUPPRESSED not in raw:
            if att == "PERIOD":
                m_at, m_span = _AGE_AT.match(raw), _AGE_SPAN.match(raw)
                if m_at or m_span:
                    age_raw = m_at.group(1) + "세" if m_at else f"{m_span.group(1)}-{m_span.group(2)}세"
                    out = super().normalize(dict(ob, attribute="AGE", raw_value=age_raw), response_text, query_text)
                    out["raw_value"], out["attribute"] = ob.get("raw_value"), "AGE"
                    out["reasons"].append("AGE_IN_PERIOD")
                    if self._age_note and out.get("mapping_status") == "MAPPED":
                        out["reasons"].append(self._age_note)
                    return out
                why = ("DURATION_NOT_DATE" if _DURATION.match(raw) else "MONTH_WITHOUT_YEAR" if _MONTH_ONLY.match(raw)
                       else "NO_DATE_VALUE" if not re.search(r"\d", raw) and not re.search(r"[A-Za-z]", raw) else None)
                # 이름(영문)이 들어간 'Unspecified convulsions 시작일' 같은 값은 추출기가 사건 이름을 기간 칸에 넣은 것이라
                # 보류하지 않고 그대로 둔다(미매핑 → 막힘). 진단 · 시술 이름이 세지 않은 채 나가지 않게 한다.
                if why:
                    return self._hold(ob, response_text, query_text, why)
            elif att == "AGE":
                if re.search(r"이상|이하|초과|미만", raw) or not re.search(r"\d", raw):
                    return self._hold(ob, response_text, query_text, "AGE_OPEN_OR_VAGUE")
                if re.search(r"\d{4}", raw) and not re.search(r"세|살", raw):                  # '1985-2025': 나이가 아니라 연도
                    return self._hold(ob, response_text, query_text, "NOT_AN_AGE")
                m_par = re.fullmatch(r"\s*(\d{1,3}\s*(?:세|살))\s*[（(].*[)）]\s*", raw)           # '48세 (진단 당시 37-42세)' → 앞의 나이
                if m_par:
                    out = super().normalize(dict(ob, raw_value=m_par.group(1)), response_text, query_text)
                    out["raw_value"] = ob.get("raw_value"); out["reasons"].append("AGE_PAREN_MAIN")
                    return out
            elif att == "REGION" and raw in _NOT_PLACE:
                return self._hold(ob, response_text, query_text, "NOT_A_PLACE")
            elif att in PARTIAL_ATTRS and raw in _NOT_SPECIFIC:
                return self._hold(ob, response_text, query_text, "NOT_A_SPECIFIC_VALUE")
        out = super().normalize(ob, response_text, query_text)
        if att == "AGE" and self._age_note and out.get("mapping_status") == "MAPPED":
            out["reasons"].append(self._age_note)
        if out.get("mapping_status") == "UNMAPPED" and att in ("PROC", "PLAN", "DX") and _SUPPRESSED not in raw:
            for other in {"PROC": ("PLAN",), "PLAN": ("PROC",), "DX": ("PLAN", "PROC")}[att]:
                hits, how = Normalizer._lookup(self, other, raw)
                if len(hits) != 1:
                    continue
                out2 = super().normalize(dict(ob, attribute=other), response_text, query_text)
                if out2.get("mapping_status") == "MAPPED":
                    out2["reasons"].append(f"ATTR_{att}_TO_{other}")
                    return out2
        return out

    def _hold(self, ob, response_text, query_text, why):
        """시간 · 나이 · 장소 값이 없는 말은 보류(PENDING): 근거 · 대상 확인은 원래 순서대로 먼저 한다."""
        out = dict(ob); out["node_id"] = None; out["commit"] = False; out["reasons"] = []
        spans = ob.get("evidence_spans") or []
        if not spans or not all(sp in response_text for sp in spans):
            out["mapping_status"] = "PENDING"; out["reasons"].append("EVIDENCE_NOT_IN_RESPONSE (3.8, 3.11)"); return out
        out["mapping_status"] = "PENDING"; out["reasons"] += [why, "PENDING (C04: 후보 제약 제외)"]
        return out

    def _index(self):
        if self._tok_index is None:
            self._tok_index = {}
            for (att, sf), nids in self.alias.items():
                if att in PARTIAL_ATTRS:
                    self._tok_index.setdefault(att, []).append((frozenset(_TOKEN.findall(sf)), nids))
        return self._tok_index

    def _partial(self, att, raw):
        q = set(_TOKEN.findall(raw.lower()))
        if not any(len(t) >= 4 and not t[0].isdigit() for t in q):      # 'of', 'mg', '500'만으로는 찾지 않음
            return None
        nodes = set()
        for toks, nids in self._index().get(att, []):
            if q <= toks:
                nodes |= nids
        nodes = {n for n in nodes if n in self.node}
        if not nodes:
            return None
        common = None
        for n in nodes:
            common = self._anc(n) if common is None else common & self._anc(n)
        if not common:
            return None
        lca = max(common, key=lambda n: len(self._anc(n)))              # 가장 깊은(가까운) 공통 상위
        if lca.startswith("ANY") or lca.endswith("_ANY") or not self.node[lca].get("parent_id"):
            return None
        return lca


def make_normalizer(paths, version: str = "v2", min_confidence=None) -> Normalizer:
    cls = NormalizerV2 if version == "v2" else Normalizer
    return cls(paths.nodes, paths.alias, min_confidence=min_confidence)

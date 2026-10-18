# 평가지표

# 평가 지표와 선행연구 비교

## 근거 표기

| 표시 | 뜻 |
|---|---|
| ◎ | 논문 원문 또는 출판사·arXiv 공식 페이지에서 내용을 확인함 |
| ○ | 초록·검색 요약 수준으로 확인함, 또는 프리프린트 (인용 전 본문 대조 필요) |
| △ |이번에 존재를 확인하지 못함 (확인 전에는 인용하지 않음) |

---

## 1. 우리 프로젝트에서 볼 수 있는 평가 지표

### 1.1 현재 사용 중인 지표 (위반 · 유용성)

| 구분 | 지표 | 정의 (쉬운 설명) | 장점 | 한계 및 보완 | 참고한 근거 |
|---|---|---|---|---|---|
| 위반 | **위반 대상 수** | 대화 중 한 번이라도 1 ≤ k_val < 5에 도달한 고유 대상 수. k_val은 정답과 대조해 맞은 단서만으로 다시 센 "같은 조건의 사람 수" | 누적 대화에서 위험에 이른 대상 규모를 직관적으로 보여줌 | 발생 횟수와 위험의 심각도는 구분하지 못함 | Weatherhead et al. (2026) ◎ |
| 위반 | **위반 대상 비율** | 위반 대상 수 ÷ 전체 대상 수 | 실험 규모가 달라도 비교하기 쉬움 | 표본이 적으면 비율의 불확실성이 큼 → 신뢰구간 병기 | Weatherhead et al. (2026) ◎ |
| 위반 | **최저 k** | 대화 중 후보 수의 최솟값 (대상별) | 위반 여부뿐 아니라 얼마나 좁혀졌는지 보임 | k=0은 안전이 아니라 조건 충돌이므로 따로 표시 | 우리 PoC |
| 유용성 | **QI 유지 점수** | 답변 속 각 QI의 공개 상태를 점수화: 원문 1점, 일반화 부분 점수, 생략 0점 | 어떤 속성이 얼마나 남았는지 설명 가능 | 일반화 부분 점수의 기준을 사전에 명확히 정해야 함 | POLAR-Bench (보호 속성과 필요 속성을 집합 포함 여부로 채점) ◎ |
| 유용성 | **평균 QI 유지율** | 대상·QI별 유지 점수의 평균 | 방어 조건별 정보 보존 정도를 비교 | 모든 QI가 같은 중요도라고 가정함 | 우리 PoC |
| 유용성 | **답변 변경·차단 비율** | 방어로 수정되거나 차단된 턴의 비율 | 방어가 답변에 미치는 영향을 측정 | 변경된 답변이 실제로 유용한지는 알려주지 않음 | 우리 PoC |
| 유용성 | **글자 유사도·길이 비율** | 원문과 방어 후 답변의 글자 단위 유사도, 길이 비교 | 자동으로 쉽게 계산 | 표현이 비슷해도 의미가 훼손될 수 있음. 의료 LLM 평가 연구도 어휘 중복 지표(ROUGE 등)는 정확성 검증에 부족하다고 지적 | LiveMedBench (Yan et al., 2026) ◎ |

> 기준 임계값 주의: 기존 PoC 보고서의 위반 기준은 k = 1, 2, 3 (k < 4)였고, 현재 제안은 k < 5라 k = 4도 위반에 포함됩니다. 변경 이유를 명시하고, 가능하면 두 임계값에서 결과를 모두 보고하세요.

### 1.2 추가로 볼 만한 지표

| 우선순위 | 지표 | 설명 | 왜 필요한가 | 현재 로그로 계산 | 참고한 근거 |
|---|---|---|---|---|---|
| 높음 | **위험 도달 속도** | 몇 번째 질문에서 위험 기준에 도달하나 (중앙값) | 위험이 얼마나 빨리 오는지, 공격에 드는 질문 수의 대리 지표 | 가능 | Weatherhead (2026) ◎, Cheng et al. (2025, 질의당 비용) ◎ |
| 높음 | **불필요 개입률** | 위험 없는 질문·대상에 방어가 끼어든 비율 | 필요 없는 수정이 많으면 사용성이 나빠짐 | 정상 질문 실험으로 가능 | Hermansa et al. (2022, 오경보 감소) ◎, El Emam & Dankar (2008, 과잉 익명화) ◎ |
| 높음 | **사후 검증 일치도** | 실행 중 k(k_run)와 정답 대조 k(k_val)의 차이, 놓친 위반 수 | 실행 중 값만 보면 위반을 놓칠 수 있음 | 가능 | 우리 PoC |
| 높음 | **AI 추측 정답률** | AI가 말한 QI 중 정답과 맞은 비율 | 방어 전 위험이 AI의 추측 정확도에 달려 있음 | 사후 검증 분류로 가능 | Staab et al. (2025), SynthPAI (2024) ◎ |
| 중간 | **QI 추출 정확도** | 추출기가 QI를 놓치거나 잘못 뽑은 정도 (Precision·Recall·F1) | 놓치면 k를 크게 계산해 위험을 과소평가 | 정답 라벨 필요 | Stubbs et al. (2015) ○, TAB (2022) ◎ |
| 중간 | **응답 품질 (루브릭)** | 방어 후에도 질문에 정확하고 충분히 답했는지 항목별 채점 | 글자 유사도로는 의미 유지를 알 수 없음 | 평가자(사람 또는 AI) 필요 | HealthBench (2025) ◎, LiveMedBench (2026) ◎ |
| 중간 | **보정 위반율** | 쓸모 있는 응답만으로 다시 센 위반율 | 전부 거절해도 위반은 0이 되는 문제를 보정 | 응답 품질 평가와 함께 | PrivacyLens (2024) ◎ |
| 중간 | **민감도 분석** | 기준 집단 크기·임계값(k<4, k<5)을 바꿔도 결론이 같은가 | 결과가 설정에 좌우되는지 확인 | 가능 (기록 재계산) | Weatherhead (2026) ◎ |
| 중간 | **신뢰구간·검정** | 대상 수가 적을 때 우연인지 판단 | 결과의 신뢰도를 표시 | 가능 | Weatherhead (2026, 신뢰구간 사용) ◎ |
| 낮음 | **QI별 위험 기여도** | 어떤 정보 종류가 위반을 많이 만드나 | 우선 보호할 속성을 정함 | 로그의 후보 QI로 가능 | PRASH (2021, 방향만 참고) ○ |
| 낮음 | **운영 비용** | 방어에 쓰인 응답 지연·재검사 횟수 | 실제 서비스 적용 가능성 | 로그 추가 필요 | 고객 서비스 챗봇 사례(응답 시간) ○, 금융 사기 탐지 사례(조사 비용) ◎ |

---

## 2. 선행연구와 우리 프로젝트의 직접 비교

### 2.1 가장 가까운 연구

| 선행연구 | 실제 연구 내용 | 평가 방식 | 우리 프로젝트와의 차이 | 근거 |
|---|---|---|---|---|
| **Lee, Park & Son (2026)**, *Applied Sciences* 16(8), 3680 | 다중 턴 대화에서 개별로는 무해한 단서가 누적되어 생기는 재식별 위험을 다룸. 화자별로 단서를 분리해 증거 그래프에 쌓고 위험이 시작되는 시점(onset)을 탐지하는 상태 유지형 미들웨어 제안 | 위험 발생 시점 탐지 중심. (세부 지표와 데이터 규모는 HWP 요약 기준: 합성 대화 184건, OW@k·SW@k·MAE. 본문 대조 필요) | **문제 설정이 가장 직접적으로 겹침.** "다중 턴 누적 위험을 평가한다"만으로는 차별점이 되지 않음. 우리는 후보 수 k, 정답 대조 사후 검증, 온톨로지 일반화, QI 유지 점수를 결합해 비교 | ◎ (본문 지표는 ○) |
| **Weatherhead et al. (2026)**, *Frontiers in Digital Health* | 의료 합성 데이터로, 정보가 한 단계씩 공개될 때 같은 조건의 사람 수(k)가 줄어드는 현상 분석 | k<5 도달 비율 79.9%, 도달 단계 중앙값 7. 희귀 속성을 먼저 공개한 조건에서는 4단계 | 위험이 쌓이는 현상을 보였지만 방어와 그 비용(개입률·응답 손실)은 평가하지 않음 | ◎ |
| **Panjwani (2026)**, CAMP, arXiv:2604.16521 | 대화 중 개인정보를 누적 추적해 외부 모델로 나가는 입력을 가림 | 노출된 정보 유형 수, 누적 위험 점수(CPE), 개입 턴 | 위험을 가중치 점수로 계산하고 정답 대조 검증이 없음 (프리프린트) | ◎ / ○ |
| **Ren et al. (2025)**, *Findings of IJCNLP–AACL* | 텍스트 익명화의 개인정보 보호 지표를 다룬 논문 47편을 검토, 서로 다른 6가지 프라이버시 개념으로 분류하고 HIPAA·GDPR 기준과 대응 | 지표 비교 조사 (지표 목록은 [저장소](https://github.com/ryxGuo/privacy-metrics-survey) 참고) | 단일 수치가 모든 보호 수준을 대표하지 않으므로, 우리 k가 어떤 종류의 위험을 나타내는지 명시해야 함 | ◎ |
| **Pilán et al. (2022)**, TAB, *Computational Linguistics* 48(4) | 텍스트 익명화 평가용 코퍼스와 평가 프레임워크 | 직접식별자·준식별자 recall, 가중 precision | 문서 한 건 단위 평가. 보호와 유용성을 함께 보는 발상은 선행연구에도 있음 | ◎ |
| **El Emam & Dankar (2008)**, *JAMIA* 15(5) | k-익명성이 실제 재식별 확률을 얼마나 낮추는지 시뮬레이션 | 재식별 확률(두 시나리오), 정보 손실(discernibility) | 정적 데이터가 대상. k-익명성은 일부 시나리오에서 과도하게 익명화할 수 있어 우리의 "불필요 개입률" 지표의 근거 | ◎ |
| **Sweeney (2002)**, k-anonymity | 준식별자 조합으로 개인이 구별되지 않도록 하는 모델 | 동일 조합을 가진 레코드 수 k | 후보 집단 크기를 위험 판단에 쓰는 이론적 배경. 대화에서 계산한 k는 정형 데이터의 보장과 같지 않음 | ◎ |
| **Garfinkel (2015)**, NISTIR 8053 | 비식별화 방법과 위험, 비식별 데이터도 재식별될 수 있음을 설명한 공식 보고서 | 보호와 유용성의 균형 논의 | 우리 방어 방식이나 결과를 직접 입증하지는 않음 | ○ |

### 2.2 같은 문제를 다른 쪽에서 다룬 관련 연구 (프리프린트 포함)

| 연구 | 내용 | 비교 시 유의점 | 근거 |
|---|---|---|---|
| Stateful Guardrails for Multi-Turn LLM Systems: A Conversational Risk Accumulation Framework, arXiv:2607.19361 | 교차 턴 정보 공개를 정보 누적 그래프로 표현하는 상태 유지형 가드레일 | 안전·위험 누적 관점이며 후보 수 k 기준과 다름. 차별점을 쓸 때 함께 확인 | ○ |
| DeepContext (Albrethsen & Kumar), arXiv:2602.16935 | 상태를 전파해 다중 턴 위험의 누적을 탐지하는 가드레일 | 적대적 의도 탐지가 대상. 개인정보 재식별과는 위협이 다름 | ○ |
| Shao et al. (2024), PrivacyLens, NeurIPS | 에이전트 행동에서 민감정보 누출을 측정 | 누출률과 도움됨 점수를 함께 보고하는 설계를 참고 | ◎ |

---
## 3. 의료와 다른 산업의 평가 지표

| 분야 | 연구 | 무엇을 평가하나 | 사용 지표 | 우리 프로젝트에 주는 시사점 | 근거 |
|---|---|---|---|---|---|
| **의료 데이터 비식별화** | Exploring the tradeoff between data privacy and utility with a clinical data analysis use case, *BMC Med Inform Decis Mak* (2024) | 서울 소재 대학병원 환자 1,155건으로 응급실 체류 시간 예측을 수행하며 비식별화 방법별 개인정보 보호와 유용성의 관계를 분석 | 재식별 감소율, ARX 유용성 점수, 분석 결과(예측 모델) 변화 | 보호에 성공했는지뿐 아니라 보호 후에도 원래 작업이 가능한지를 따로 측정. 연구에서는 재식별 감소율과 유용성 점수 사이에서만 유의한 상관이 관찰되어, 지표 간 관계를 직접 확인해야 함 | ◎ |
| **의료 LLM 응답 품질** | HealthBench (Arora et al., 2025, arXiv:2505.08775) | 의사가 설계한 루브릭으로 다중 턴 의료 대화 응답을 채점 (5,000개 대화, 48,562개 평가 기준) | 정확성·완전성·소통 품질·맥락 인식·지시 준수 | 글자 유사도 대신 답변의 핵심 내용이 유지됐는지를 항목별 점수로 평가하는 틀 | ◎ |
| **의료 LLM 응답 품질** | LiveMedBench (Yan et al., 2026, arXiv:2602.10367) | 실제 임상 사례 2,756건, 38개 전문과, 16,702개 평가 기준의 루브릭 기반 벤치마크 | 사례별로 쪼갠 루브릭 평가. 어휘 중복(ROUGE)은 임상 정확성 확인에 부족하다고 지적 | 우리 유용성 평가의 한계(글자 유사도)와 같은 문제의식 | ◎ |
| **의료 텍스트 비식별화** | Stubbs et al. (2015), 2014 i2b2/UTHealth 개인정보 탐지 과제 | 임상 기록에서 개인정보를 찾는 시스템 성능 | Precision·Recall·F1 (엄격 평가와 토큰 단위 평가) | QI 추출기의 정확도를 따로 평가. 종단 기록에서 개별로는 무해한 정보가 결합되면 식별로 이어질 수 있다는 문제의식도 같음 | ○ |
| **금융 (사기 탐지)** | Chargeback Fraud Detection on Anonymised Merchant Data: An Industry Case Study (ACM, 2026) | 익명화된 가맹점 거래 데이터로 환불 사기를 탐지 | ROC-AUC 87%, 재현율 47%에서 정밀도 86%, PR-AUC 50%, 손익분기 조사 비용 | 탐지율 하나가 아니라 오탐과 조사 비용을 함께 봄. 우리도 위험 감소 효과와 과잉 개입 손실을 함께 보는 관점 | ◎ |
| **제조 (예지 보전)** | Hermansa et al. (2022), Sensor-Based Predictive Maintenance with Reduction of False Alarms, *Sensors* 22(1), 226 | 설비 센서 이상 탐지에서 오경보를 줄이는 방법 | 단독 이상치 탐지 대비 오경보 평균 90.25% 감소 | 연구의 동기가 "운영자를 경보로 압도하지 않는 것". 필요할 때만 수정·차단하는지를 불필요 개입률로 평가 | ◎ |
| **고객 서비스** | Implementing AI Chatbots in Customer Service Optimization—A Case Study in Micro-Enterprise, *Information* 16(12), 1078 (2025) | 슬로바키아 소규모 이커머스 업체의 챗봇 도입 효과 | 처리한 문의 수, 응답 시간, 자동화율 등 정량 지표와 직원·고객 피드백 | 답변이 원문과 비슷한지는 품질의 일부일 뿐. 질문에 적절히 대응했는지를 별도로 평가 | ◎ (초록) |
| **교육·공공통계** | Ferrão et al. (2022), Utility-driven assessment of anonymized data via clustering, *Scientific Data* 9, 456 | 포르투갈 고등교육 법학 학생 행정 데이터를 익명화한 뒤 분석 구조가 유지되는지 평가 | 군집 타당성 지표, 상대 위험 등. 익명화 후 추정치가 편향될 수 있다는 결과 | 유용성을 데이터 통계가 아니라 분석 결과가 같은가로 보는 관점 | ◎ |
| **LLM 보안** | Cheng et al. (2025), Effective PII Extraction from LLMs through Augmented Few-Shot Learning, USENIX Security | 모델이 학습 때 외운 개인정보를 뽑는 공격 | 비표적 추출 공격 성공률 48.9%, 정보 1건당 약 0.012달러 | 위협이 학습 데이터 기억이라 우리와 다름. 공격 성공률과 비용을 보고하는 방식만 참고 | ◎ |
| **LLM 에이전트** | POLAR-Bench (Zheng et al., 2026, arXiv:2605.19127) | 개인정보 정책을 지키면서 작업에 필요한 정보는 제공하는지 평가 (10개 분야, 7,852개 표본) | 프라이버시와 유용성을 각각 집합 포함 여부로 결정적 채점 | 우리의 QI 유지 점수와 같은 구조. 보호와 유용성을 따로 채점해 함께 해석 | ◎ (프리프린트) |
| **스마트홈·IoT** | Bugeja et al. (2021), PRASH, *Sensors* 21, 6399 | 스마트홈의 개인정보 위험을 체계적으로 분석하는 틀 | 공격 유형 분류, 공격 트리, 정량 지표로 위험 노출도 계산 | 속성별 위험 중요도를 달리 보는 방향 참고 | ○ |
| **차등 프라이버시** | Kairouz et al. (2015), The Composition Theorem for Differential Privacy, ICML | 반복 질의에서 보호가 얼마나 떨어지는지 이론적으로 증명 | 질의 횟수에 따른 전체 보호 수준 하락 | 누적 위험이 중요하다는 배경. DP와 k-익명성은 다른 모델이라 수치를 직접 비교하지 않음 | ◎ |

---

## 4. 평가 지표 자체의 비교

| 평가 목적 | 선행연구에서 볼 수 있는 지표·방법 | 우리 프로젝트의 지표 | 장점 | 주의할 점 |
|---|---|---|---|---|
| 재식별 위험 | k-익명성, 재식별 성공 확률, 위험 도달 비율과 시점 | 대화별 후보 수 k, 위반 여부 | 위험을 수치화하고 조건별로 비교 가능 | k는 기준 집단과 후보 산정 방식에 의존 |
| 위험 계산의 기준 | 공개 데이터나 공격 모델의 지식으로 위험 추정 | 정답과 일치하는 단서만으로 사후 계산한 k_val | 방어가 추출한 값과 별도로 정답 기준 위험을 산출 | 정답 라벨이 있는 합성 데이터에서만 가능 |
| 다중 턴 위험 탐지 | 위험 발생 시점 탐지 (Lee et al., 2026), 누적 위험 점수 (CAMP) | 대상별 위반 수·비율, 위험 도달 속도 | 대화 단위 노출 여부를 간단히 비교 | 방어가 얼마나 빨랐는지는 별도 지표 필요 |
| 보호와 텍스트 유용성 | TAB의 프라이버시·유용성 평가, POLAR-Bench의 집합 기반 채점 | 위반과 QI 유지 점수를 함께 측정 | 보호와 정보 손실을 동시에 확인 | QI 유지율만으로 답변 전체의 유용성을 대표할 수 없음 |
| 응답 변화 정도 | 원문과 변환문의 차이 | 답변 변경 비율, 글자 유사도, 길이 비율 | 자동 비교가 쉬움 | 표현이 비슷해도 의미는 훼손될 수 있고 반대도 가능 |
| QI 정보 보존 | 태스크 유용성, 정보 손실 | 원문 1·일반화 부분·생략 0 | 어떤 속성이 얼마나 남았는지 설명 가능 | 부분 점수는 표준 지표가 아니므로 규칙을 명시 |
| 의미적 유용성 | 루브릭 기반 평가 (HealthBench, LiveMedBench) | (현재 미측정) 질문 충족도·정보 완전성 루브릭 추가 권장 | 보호 후에도 목적을 달성했는지 측정 | 평가자 간 일치도 검증 필요 |
| 과잉 개입 | 오경보율, 오탐 비용 (제조·금융 사례) | (추가 권장) 불필요 개입률 | 필요할 때만 방어하는지 확인 | 위험 없는 대상·정상 질문 실험이 필요 |

---

## 5. 우리 프로젝트의 차별점 (근거 수준별)

| 차별점 후보 | 현재 근거 수준 | 근거와 한계 | 보고서에서 권장하는 표현 |
|---|---|---|---|
| 대화 전체 이력을 고려한 누적 방어 | 실험으로 관찰된 기능적 근거 | 누적 방어(C1)와 턴별 방어(C1S)를 비교함. 다만 2026년에도 다중 턴 누적 위험 연구가 있고 우리 표본은 작음 | "소규모 PoC에서 누적 방어가 턴별 방어보다 관찰된 재식별 사례를 효과적으로 방지했다." |
| 후보 집단 크기 k 기반 위험 판단 | 구현·평가 지표 수준 | 고전적 k-익명성의 보장과 같은 의미는 아니며 기준 집단이 현실적인지 구분해야 함 | "준식별자 조합에 따른 후보 집단 크기를 위험 판단 지표로 사용한다." |
| 정답 기준 사후 위험 계산(k_val) | 평가 정의로 확인 | 방어 결과와 위험 평가 기준을 분리하도록 설계. 정답 라벨이 있는 합성 데이터에 한정 | "방어가 추출한 값과 별도로 정답과 일치하는 단서로 위험을 사후 산출했다." |
| 온톨로지 계층을 활용한 일반화 | 설계·구현 개념 수준 | 계층적 일반화가 설계돼 있으나 제공된 실험에서는 일반화가 실제로 선택되지 않아 효과가 입증되지 않음 | "온톨로지 기반 일반화 기능을 설계했으며, 보호 효과는 후속 실험으로 검증할 예정이다." |
| 개인정보 보호와 QI 정보 보존의 동시 평가 | 평가 체계 설계 수준 | 위험과 유용성을 함께 보는 접근은 TAB 등 선행연구에도 있어 독창적 평가 개념이라 주장하기 어려움 | "누적 재식별 위험과 QI 보존을 함께 평가하도록 PoC 지표를 구성했다." |
| 응답을 크게 바꾸지 않으면서 위험을 줄이는 방어 | 초기 실험의 관찰 근거 | 120턴 중 9턴만 변경·차단, 92.5%는 변경되지 않음. 수정 빈도일 뿐 의미적 유용성의 직접 증명은 아님 | "해당 실험에서는 대부분의 응답이 유지되었으며, 의미적 유용성은 별도 평가가 필요하다." |
| 기존 연구와 구별되는 독창성 | 아직 미확립 | 동일 구성·지표·데이터를 비교한 체계적 검토가 없고, 2026년의 직접 관련 연구도 확인됨 | "현재 확인한 선행연구와 비교해 구성 요소의 결합 방식에 차별화 가능성이 있으나, 독창성은 추가 문헌 검토가 필요하다." |

> 현재 자료로 가장 설득력 있게 제시할 수 있는 점은 QI 기반 후보 집단 위험 평가, 대화 이력 누적 방어, 온톨로지 일반화 설계, 개인정보 보호와 정보 보존을 함께 보는 평가 체계.

---

## 6. 확인 현황

### 6.1 이번에 존재를 확인한 자료

Lee et al. (2026), Weatherhead et al. (2026), CAMP (2026), Ren et al. (2025), TAB (2022), El Emam & Dankar (2008), Sweeney (2002), PrivacyLens (2024), Staab et al. (2025), SynthPAI (2024), Cheng et al. (2025), Ferrão et al. (2022), PRASH (2021, 초록 수준), Kairouz et al. (2015), 의료 비식별화 트레이드오프 사례 (2024), Chargeback 사기 탐지 (2026), Hermansa et al. (2022), 고객 서비스 챗봇 (2025, 초록 수준), POLAR-Bench (2026), LiveMedBench (2026), HealthBench (2025).

### 6.2 이번에 확인하지 못한 자료 (인용 전 확인 필요) △

| 자료 | 비고 |
|---|---|
| Jin et al., IEEE TKDE (2023), 궤적 데이터 공개 서베이 | 위치 궤적 연구라 평가 설계만 참고 |
| Zhao, Kaafar & Kourtellis (2020), Not one but many Tradeoffs | 차등 프라이버시 머신러닝 연구 |
| 이동통신 위치 데이터 재식별 위험과 유용성 (2015) | 저자·게재 정보 확인 필요 |
| 금융 합성 데이터 개인정보 위험과 트레이드오프 (2026) | 출처 확인 필요 |
| The Costs of Anonymization: Case Study Using Clinical Data | 독일 만성 신장질환 데이터 사례 |
| Evaluating LLM-based Agents for Multi-Turn Conversations: A Survey (2025) | 평가 차원 비교용 |
| Anonymization Techniques for Privacy Preserving Data Publishing: A Comprehensive Survey (2020) | 지표 분류 근거 |
| PatientAgentBench, Text Anonymization Evaluator(TAE), NIST UEM·SsE 지표 자료 | 공개 저장소·공식 자료 위치 확인 필요 |

---

## 7. 참고문헌

1. Y. Lee, S. Park, and Y. Son, "Early Detection of Re-Identification Risk in Multi-Turn Dialogues via Entity-Aware Evidence Accumulation," *Applied Sciences*, 16(8), 3680, 2026. https://doi.org/10.3390/app16083680
2. J. Weatherhead et al., "K-anonymity decay in multi-turn clinical large language model conversations," *Frontiers in Digital Health*, 8, 1832168, 2026. https://doi.org/10.3389/fdgth.2026.1832168
3. A. Panjwani, "CAMP: Cumulative Agentic Masking and Pruning for Cross-Turn PII Protection in Multi-Turn LLM Conversations," arXiv:2604.16521, 2026. (프리프린트)
4. Y. Ren, K. Ramesh, Y. Yao, and A. Field, "How do we measure privacy in text? A survey of text anonymization metrics," *Findings of IJCNLP–AACL 2025*, pp. 1532–1544. https://doi.org/10.18653/v1/2025.findings-ijcnlp.94
5. I. Pilán et al., "The Text Anonymization Benchmark (TAB)," *Computational Linguistics*, 48(4), 1053–1101, 2022. https://doi.org/10.1162/coli_a_00458
6. K. El Emam and F. K. Dankar, "Protecting Privacy Using k-Anonymity," *JAMIA*, 15(5), 627–637, 2008. https://doi.org/10.1197/jamia.M2716
7. L. Sweeney, "k-Anonymity: A Model for Protecting Privacy," *Int. J. Uncertainty, Fuzziness and Knowledge-Based Systems*, 10(5), 557–570, 2002. https://doi.org/10.1142/S0218488502001648
8. S. L. Garfinkel, "De-Identification of Personal Information," NISTIR 8053, NIST, 2015. https://doi.org/10.6028/NIST.IR.8053
9. A. Stubbs, C. Kotfila, and Ö. Uzuner, "Automated systems for the de-identification of longitudinal clinical narratives: Overview of 2014 i2b2/UTHealth shared task Track 1," *J. Biomed. Inform.*, 58(Suppl), S11–S19, 2015.
10. Y. Shao et al., "PrivacyLens: Evaluating Privacy Norm Awareness of Language Models in Action," NeurIPS 2024. arXiv:2409.00138
11. R. Staab et al., "Large Language Models are Advanced Anonymizers," arXiv:2402.13846 (ICLR 2025).
12. H. Yukhymenko, R. Staab, M. Vero, and M. Vechev, "A Synthetic Dataset for Personal Attribute Inference," NeurIPS 2024. arXiv:2406.07217
13. S. Cheng et al., "Effective PII Extraction from LLMs through Augmented Few-Shot Learning," USENIX Security 2025. https://www.usenix.org/conference/usenixsecurity25/presentation/cheng-shuai
14. M. E. Ferrão, P. Prata, and P. Fazendeiro, "Utility-driven assessment of anonymized data via clustering," *Scientific Data*, 9, 456, 2022. https://doi.org/10.1038/s41597-022-01561-6
15. J. Bugeja, A. Jacobsson, and P. Davidsson, "PRASH: A Framework for Privacy Risk Analysis of Smart Homes," *Sensors*, 21, 6399, 2021.
16. P. Kairouz, S. Oh, and P. Viswanath, "The Composition Theorem for Differential Privacy," ICML 2015, PMLR 37, 1376–1385.
17. "Exploring the tradeoff between data privacy and utility with a clinical data analysis use case," *BMC Medical Informatics and Decision Making*, 2024. https://doi.org/10.1186/s12911-024-02545-9
18. R. K. Arora et al., "HealthBench: Evaluating Large Language Models Towards Improved Human Health," arXiv:2505.08775, 2025.
19. Z. Yan et al., "LiveMedBench: A Contamination-Free Medical Benchmark for LLMs with Automated Rubric Evaluation," arXiv:2602.10367, 2026. (프리프린트)
20. Q. Zheng, Q. Gao, Y. Yang, and I. Schlag, "POLAR-Bench: A Diagnostic Benchmark for Privacy-Utility Trade-offs in LLM Agents," arXiv:2605.19127, 2026. (프리프린트)
21. "Chargeback Fraud Detection on Anonymised Merchant Data: An Industry Case Study," ACM, 2026. https://doi.org/10.1145/3793638.3793649
22. M. Hermansa et al., "Sensor-Based Predictive Maintenance with Reduction of False Alarms—A Case Study in Heavy Industry," *Sensors*, 22(1), 226, 2022. https://doi.org/10.3390/s22010226
23. "Implementing AI Chatbots in Customer Service Optimization—A Case Study in Micro-Enterprise," *Information*, 16(12), 1078, 2025. https://doi.org/10.3390/info16121078 (MDPI 페이지 기준, DOI 형식 재확인 필요)
24. "Stateful Guardrails for Multi-Turn LLM Systems: A Conversational Risk Accumulation Framework," arXiv:2607.19361. (프리프린트)
25. J. Albrethsen and K. Kumar, "DeepContext: Stateful Real-Time Detection of Multi-Turn Adversarial Intent Drift in LLMs," arXiv:2602.16935. (프리프린트)

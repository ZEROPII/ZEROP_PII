# 평가 지표와 선행 연구 비교 (수정중)

## 근거 표기

| 표시 | 뜻 |
|---|---|
| ◎ | 논문 원문 또는 출판사·arXiv 공식 페이지에서 내용을 확인함 |
| ○ | 초록·검색 요약 수준으로 확인함, 또는 프리프린트 (인용 전 본문 대조 필요) |
| △ |이번에 존재를 확인하지 못함 (확인 전에는 인용하지 않음) |

---

## 1. 우리 프로젝트에서 볼 수 있는 평가 지표

### 1.1 현재 사용 중인 지표
| 평가지표 | 평가 지표에 대한 설명 | 선행 연구 및 근거 | 우리 연구에서의 의미 |
|---|---|---|---|
| 누적 재식별 위험 위반율 (Cumulative Risk Violation Rate) | 여러 대화 턴에 걸쳐 QI가 누적되면서 재식별 위험 기준을 한 번 이상 위반한 대상자의 비율| Weatherhead et al. (2026)은 다중 턴 임상 LLM 대화에서 QI가 누적될수록 k-anonymity가 감소하는 현상을 분석함.  | 누적 방어가 없는 경우와 있는 경우를 비교해, 위험 기준을 위반하는 대상자가 얼마나 줄어드는지 평가 |
| 위험 억제율 (Risk Suppression Rate) | 방어 적용 전과 비교해 방어 적용 후 위험 위반율이 상대적으로 얼마나 감소했는지 나타내는 지표 | Weatherhead et al. (2026)은 누적 위험을 분석하는 근거를 제공하지만, 아래 산식 자체를 해당 논문에서 그대로 사용했다고 볼 수는 없음. |  본 연구의 방어 효과 비교를 위해 정의하는 지표	턴 단위 방어와 누적 방어 중 어느 방식이 위험을 더 효과적으로 줄이는지 비교 |
| QI 정보 보존율 (QI Retention Rate)| 방어 후 응답에 원래 응답의 QI 정보가 얼마나 유지되었는지 평가하는 지표 |	El Emam & Dankar (2008)은 k-anonymity 적용 시 재식별 위험과 정보 손실을 함께 평가함. **Ferrão et al. (2022)**는 익명화 데이터의 효용을 평가함. 다만 두 연구의 평가법이 본 연구의 QI 보존율 산식과 동일한 것은 아님. |  위험을 억제하면서도 응답에 필요한 정보를 얼마나 보존하는지 평가. 개인정보 보호와 응답 유용성 사이의 균형을 확인. |
| 위험 탐지 누락률 (Risk Miss Rate)) | 사후 평가에서 위험하다고 판정된 응답 중 실행 시점의 방어 시스템이 위험으로 탐지하지 못한 응답의 비율 | Stubbs et al. (2015)는 임상 텍스트 비식별화 시스템을 정밀도·재현율·F1으로 평가함. 누락률은 재현율의 여집합 개념으로 정의할 수 있음. | QI 추출이나 위험 판정 과정에서 방어 시스템이 위험한 응답을 놓치는 문제를 확인 |

---
## 2. 선행연구와 우리 프로젝트의 비교

### 2.1 가장 가까운 연구

| 선행연구 | 실제 연구 내용 | 평가 방식 | 우리 프로젝트와의 차이 | 근거 |
|---|---|---|---|---|
| **Lee, Park & Son (2026)**, *Applied Sciences* 16(8), 3680 | 다중 턴 대화에서 개별로는 무해한 단서가 누적되어 생기는 재식별 위험을 다룸. 화자별로 단서를 분리해 증거 그래프에 쌓고 위험이 시작되는 시점(onset)을 탐지하는 상태 유지형 미들웨어 제안 | 위험 발생 시점 탐지 중심. | **문제 설정이 가장 직접적으로 겹침.** "다중 턴 누적 위험을 평가한다"만으로는 차별점이 되지 않음. 우리는 후보 수 k, 정답 대조 사후 검증, 온톨로지 일반화, QI 유지 점수를 결합해 비교 | ◎ (본문 지표는 ○) |
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

---

---

## 6. 참고문헌

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

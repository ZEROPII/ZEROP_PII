# 선행연구 정리: RAG/LLM 평가에서 정확성(Accuracy) 지표 사용 사례

RAG·LLM 평가에서 정확성(또는 이에 준하는 지표)을 근거 있게 사용한 선행연구 5편을 정리한 문서입니다.
정확성을 직접 지표로 쓴 연구(1, 2, 5)와, 정확성 대신 근거 충실도·관련성을 쓴 자동 평가 프레임워크(3, 4)로 구성했습니다.
---

## 한눈에 보기

| # | 논문 | 분야 | 정확성 관련 지표 | 출처 |
|---|---|---|---|---|
| 1 | Benchmarking Retrieval-Augmented Generation for Medicine (MIRAGE/MedRAG) | 의료 | 정답률(Accuracy) | Findings of ACL 2024 |
| 2 | Med-HALT: Medical Domain Hallucination Test for LLMs | 의료 | 정확도 + 환각 테스트 | CoNLL 2023 |
| 3 | RAGAS: Automated Evaluation of Retrieval Augmented Generation | 범용 | Faithfulness, Answer/Context Relevance | arXiv:2309.15217 |
| 4 | ARES: An Automated Evaluation Framework for RAG Systems | 범용 | Context Relevance, Answer Faithfulness, Answer Relevance | arXiv:2311.09476 |
| 5 | Hallucination-Free? Assessing the Reliability of Leading AI Legal Research Tools | 법률 | 정확 응답률, 환각률 | J. Empirical Legal Studies 2025 |

---

## 1. Benchmarking Retrieval-Augmented Generation for Medicine

- **저자/출처**: Xiong, Jin, Lu, Zhang / Findings of ACL 2024 / arXiv:2402.13178
- **내용**: 의료 QA 5개 데이터셋에서 뽑은 7,663개 문항으로 MIRAGE 벤치마크를 만들고, MedRAG 툴킷으로 41가지 코퍼스·검색기·LLM 조합을 평가했습니다.
- **정확성 사용 방식**: 주 지표가 정답률입니다. MedRAG는 여섯 가지 LLM의 정확도를 chain-of-thought 대비 최대 18% 높였고, GPT-4는 평균 73.44%에서 79.97%로 향상되었습니다.
- **우리 연구와의 관련**: RAG 성능을 "검색 + 답변 정확도"로 보는 가장 직접적인 의료 선행연구입니다.
- 
## 2. Med-HALT: Medical Domain Hallucination Test for Large Language Models

- **저자/출처**: Pal, Umapathi, Sankarasubbu / CoNLL 2023 / arXiv:2307.15343
- **내용**: 의료 분야 환각을 측정하는 벤치마크입니다. 잘못된 의료 정보가 환자 치료에 심각한 결과를 낳을 수 있다는 점을 동기로 합니다. 추론 기반 환각 테스트(False Confidence, None of the Above, Fake Questions)와, 학습된 지식에서 정확한 정보를 꺼내는 능력을 보는 기억 기반 테스트로 구성됩니다.
- **정확성 사용 방식**: Text Davinci, GPT-3.5, LLaMA-2, MPT, Falcon 등을 평가해 모델 간 성능 차이가 크다고 보고합니다.
- **우리 연구와의 관련**: 정확도와 환각을 함께 보고하는 의료 근거로 적합합니다.

## 3. RAGAS: Automated Evaluation of Retrieval Augmented Generation

- **저자/출처**: Es, James, Espinosa-Anke, Schockaert / 2023 / arXiv:2309.15217
- **내용**: 정답 데이터 없이(reference-free) RAG 파이프라인을 평가하는 프레임워크입니다. 핵심 차원은 충실도(faithfulness), 답변 관련성, 컨텍스트 관련성입니다.
- **정확성 사용 방식**: 충실도는 답변의 주장이 검색된 컨텍스트에서 추론 가능한지를 보며, LLM이 답변에서 진술을 추출해 하나씩 확인하는 방식으로 추정합니다. "정답과 일치하는가"가 아니라 "근거에 부합하는가"를 보는 지표입니다.
- **우리 연구와의 관련**: 근거 사실표와 대조하는 우리 환각률과 개념이 가깝습니다.

## 4. ARES: An Automated Evaluation Framework for Retrieval-Augmented Generation Systems

- **저자/출처**: Saad-Falcon, Khattab, Potts / 2023 / arXiv:2311.09476
- **내용**: 컨텍스트 관련성, 답변 충실도, 답변 관련성 세 차원에서 RAG를 평가하는 자동 시스템입니다. 코퍼스 문서와 150개 이상의 사람 선호 검증 세트만 필요하다고 합니다.
- **정확성 사용 방식**: RAGAS 같은 기존 자동 평가보다 컨텍스트 관련성 평가 정확도는 평균 59.3%p, 답변 관련성은 14.4%p 높았다고 주장합니다.
- **우리 연구와의 관련**: 자동 판정기의 신뢰도를 사람 라벨 세트로 검증한다는 논리가, 우리의 설계와 같습니다.

## 5. Hallucination-Free? Assessing the Reliability of Leading AI Legal Research Tools

- **저자/출처**: Magesh, Surani, Dahl, Suzgun, Manning, Ho / J. Empirical Legal Studies 2025 / arXiv:2405.20362
- **내용**: 법률 분야 RAG 도구들이 환각을 없앴다는 업체 주장을 검증한, 사전 등록(preregistered) 방식의 첫 실증 평가입니다.
- **정확성 사용 방식**: Lexis+ AI는 질의의 65%에서 정확(맞고 근거도 있음)했고, Westlaw는 42%, Practical Law AI는 19%였습니다. 제품별 환각률은 약 17~33%로 보고됩니다. 환각은 "틀린 정보이거나 출처가 주장을 뒷받침한다는 거짓 진술을 담은 응답"으로 정의하고 사람이 직접 검토했습니다.
- **우리 연구와의 관련**: 본 연구는 정확성을 단순한 정답 여부로만 판단하지 않고, 답변의 사실적 정확성과 근거의 적절성을 구분하여 평가했다는 점에서 의의가 있다. 또한 응답을 사람이 직접 검토하고, 정확한 응답·환각·불완전한 응답을 구별하여 분석했다.

## 링크

1. https://aclanthology.org/2024.findings-acl.372 (arXiv: https://arxiv.org/abs/2402.13178)
2. https://aclanthology.org/2023.conll-1.21 (arXiv: https://arxiv.org/abs/2307.15343)
3. https://arxiv.org/abs/2309.15217
4. https://arxiv.org/abs/2311.09476
5. https://arxiv.org/abs/2405.20362 (DOI: https://doi.org/10.1111/jels.12413)

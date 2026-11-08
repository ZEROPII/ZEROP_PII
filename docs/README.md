# 문서 안내

저장소 소개와 실행 방법은 [첫 화면 README](../README.md)에 있습니다. 이 폴더에는 설계 근거와 실험 기록을 둡니다.

| 문서 | 내용 |
| --- | --- |
| [adr/](adr/README.md) | 설계 결정 기록(ADR) 39건. 기준 · 구조 · 실험 방식을 바꾼 결정마다 배경, 결정, 대안, 영향을 남겼습니다 |
| [medical.md](medical.md) | 의료 시나리오 실험 코드(`python -m medical`): 한 trial의 흐름, Defender 정책, 기준 집단 사전 점검, 모의 POC |
| [medical/](medical/) | 팀에서 받은 명세: 대상 AI 하네스 · 평가 명세, 추출 · 정규화 명세, 설계 보고서 발췌 |
| [evaluation.md](evaluation.md) | 평가 통합 문서: `evaluation_proto`와 `eval-metrics`의 역할, 데이터 흐름, 지표 정의, 통계 처리 원칙 |
| [rag_remeasure/](rag_remeasure/README.md) | RAG 기준 재측정 도구(R1~R6)와 원본 대조 검증기 사용법 |
| [research_harness.md](research_harness.md) | 연구 하네스(실험 코드) 상세: SynthPAI 단계의 실행 옵션, 정답 대조(k_val), 재실행, 다시 계산, 유용성 지표 |
| [modules.md](modules.md) | 모듈별 상세: Risk/Defender 정책, Threshold 선정 근거, 평가 로그 컬럼 |
| [ontology.md](ontology.md) | SynthPAI 8개 QI 온톨로지 계층과 검토가 필요한 항목 |
| [개발기록_의료전환.md](개발기록_의료전환.md) | SynthPAI에서 의료(Synthea)로 옮긴 과정의 개발 기록 |
| [paper_analysis.md](paper_analysis.md) | 논문용 분석(`python -m analysis`) 설명 |
| [images/](images/) | 첫 화면 README의 그림과 화면 캡처 |

제품 쪽 문서는 코드 옆에 있습니다: 운영 모드 [medicloak/README.md](../medicloak/README.md), 데모 서버 [webdemo/README.md](../webdemo/README.md), 화면 [frontend/README.md](../frontend/README.md), 단서 추출 채점 [medical/scoring/README.md](../medical/scoring/README.md).

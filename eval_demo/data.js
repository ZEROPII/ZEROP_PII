window.DASH = {
 "meta": {
  "title": "비식별화 성능 평가 대시보드",
  "updated": "2026-10-29",
  "source": "poc_summary.json"
 },
 "scenarioLabels": {
  "staged": "staged",
  "full": "full"
 },
 "fuzzerLabels": {
  "uniform": "무작위",
  "feedback": "k 피드백"
 },
 "armLabels": {
  "C0": "방어 없음",
  "C1S": "단일 응답 가드레일",
  "C1": "누적 가드레일 (Ours)"
 },
 "scenarios": {
  "staged_uniform": {
   "config": {
    "budget_B": 10,
    "mode": "efficiency",
    "fuzzer": "uniform",
    "k_req": 5,
    "generalize_threshold": 5,
    "suppress_threshold": 3
   },
   "arms": {
    "C0": {
     "n": 296,
     "outcomes": {
      "RISK_REACHED": 268,
      "RISK_AT_TURN0": 28
     },
     "violTurn7": {
      "k": 283,
      "n": 296,
      "p": 0.9561,
      "ci": [
       0.9263,
       0.9742
      ]
     },
     "violFinal": {
      "k": 296,
      "n": 296,
      "p": 1.0,
      "ci": [
       0.9872,
       1.0
      ]
     },
     "riskAtTurn0": {
      "k": 28,
      "n": 296,
      "p": 0.0946,
      "ci": [
       0.0663,
       0.1333
      ]
     },
     "firstViolationMedian": 3.0,
     "cum": [
      0.0946,
      0.2095,
      0.3547,
      0.6182,
      0.75,
      0.8311,
      0.9257,
      0.9561,
      0.9797,
      0.9899,
      1.0
     ],
     "kMed": [
      75.0,
      31.0,
      11.0,
      3.0,
      2.0,
      2.0,
      2.0,
      2.0,
      2.0,
      2.0,
      2.0
     ],
     "utility": 1.0,
     "release": {
      "RAW": 1270
     },
     "overblock": {
      "k": 0,
      "n": 3400,
      "p": 0.0,
      "ci": [
       0.0,
       0.0011
      ]
     },
     "residualFinalK": {}
    },
    "C1S": {
     "n": 296,
     "outcomes": {
      "RISK_REACHED": 271,
      "BUDGET": 25
     },
     "violTurn7": {
      "k": 246,
      "n": 296,
      "p": 0.8311,
      "ci": [
       0.7842,
       0.8695
      ]
     },
     "violFinal": {
      "k": 271,
      "n": 296,
      "p": 0.9155,
      "ci": [
       0.8783,
       0.9421
      ]
     },
     "riskAtTurn0": {
      "k": 0,
      "n": 296,
      "p": 0.0,
      "ci": [
       0.0,
       0.0128
      ]
     },
     "firstViolationMedian": 3,
     "cum": [
      0.0,
      0.1453,
      0.2804,
      0.4831,
      0.6014,
      0.6959,
      0.7939,
      0.8311,
      0.8649,
      0.8953,
      0.9155
     ],
     "kMed": [
      85.0,
      32.0,
      13.0,
      5.0,
      4.0,
      3.0,
      3.0,
      3.0,
      2.0,
      2.0,
      2.0
     ],
     "utility": 0.9349,
     "release": {
      "RAW": 1361,
      "REWRITTEN": 240
     },
     "overblock": {
      "k": 17,
      "n": 3946,
      "p": 0.0043,
      "ci": [
       0.0027,
       0.0069
      ]
     },
     "residualFinalK": {
      "k=4": 54,
      "k=1": 85,
      "k=2": 76,
      "k=3": 56
     }
    },
    "C1": {
     "n": 296,
     "outcomes": {
      "BUDGET": 296
     },
     "violTurn7": {
      "k": 0,
      "n": 296,
      "p": 0.0,
      "ci": [
       0.0,
       0.0128
      ]
     },
     "violFinal": {
      "k": 0,
      "n": 296,
      "p": 0.0,
      "ci": [
       0.0,
       0.0128
      ]
     },
     "riskAtTurn0": {
      "k": 0,
      "n": 296,
      "p": 0.0,
      "ci": [
       0.0,
       0.0128
      ]
     },
     "firstViolationMedian": null,
     "cum": [
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0
     ],
     "kMed": [
      85.0,
      40.0,
      21.5,
      15.0,
      13.0,
      11.0,
      10.0,
      9.0,
      9.0,
      8.0,
      8.0
     ],
     "utility": 0.5692,
     "release": {
      "RAW": 1346,
      "REWRITTEN": 1910
     },
     "overblock": {
      "k": 376,
      "n": 6450,
      "p": 0.0583,
      "ci": [
       0.0528,
       0.0643
      ]
     },
     "residualFinalK": {}
    }
   }
  },
  "staged_feedback": {
   "config": {
    "budget_B": 10,
    "mode": "efficiency",
    "fuzzer": "feedback",
    "k_req": 5,
    "generalize_threshold": 5,
    "suppress_threshold": 3
   },
   "arms": {
    "C0": {
     "n": 296,
     "outcomes": {
      "RISK_REACHED": 268,
      "RISK_AT_TURN0": 28
     },
     "violTurn7": {
      "k": 294,
      "n": 296,
      "p": 0.9932,
      "ci": [
       0.9757,
       0.9981
      ]
     },
     "violFinal": {
      "k": 296,
      "n": 296,
      "p": 1.0,
      "ci": [
       0.9872,
       1.0
      ]
     },
     "riskAtTurn0": {
      "k": 28,
      "n": 296,
      "p": 0.0946,
      "ci": [
       0.0663,
       0.1333
      ]
     },
     "firstViolationMedian": 3.0,
     "cum": [
      0.0946,
      0.2095,
      0.4426,
      0.7095,
      0.8851,
      0.9628,
      0.9797,
      0.9932,
      1.0,
      1.0,
      1.0
     ],
     "kMed": [
      75.0,
      31.0,
      6.0,
      2.0,
      2.0,
      2.0,
      2.0,
      2.0,
      2.0,
      2.0,
      2.0
     ],
     "utility": 1.0,
     "release": {
      "RAW": 1102
     },
     "overblock": {
      "k": 0,
      "n": 2861,
      "p": 0.0,
      "ci": [
       0.0,
       0.0013
      ]
     },
     "residualFinalK": {}
    },
    "C1S": {
     "n": 296,
     "outcomes": {
      "RISK_REACHED": 258,
      "BUDGET": 38
     },
     "violTurn7": {
      "k": 241,
      "n": 296,
      "p": 0.8142,
      "ci": [
       0.766,
       0.8544
      ]
     },
     "violFinal": {
      "k": 258,
      "n": 296,
      "p": 0.8716,
      "ci": [
       0.8287,
       0.905
      ]
     },
     "riskAtTurn0": {
      "k": 0,
      "n": 296,
      "p": 0.0,
      "ci": [
       0.0,
       0.0128
      ]
     },
     "firstViolationMedian": 3.0,
     "cum": [
      0.0,
      0.1453,
      0.3041,
      0.4797,
      0.6216,
      0.6892,
      0.7601,
      0.8142,
      0.8581,
      0.8682,
      0.8716
     ],
     "kMed": [
      85.0,
      32.0,
      12.0,
      5.0,
      4.0,
      3.0,
      3.0,
      3.0,
      3.0,
      3.0,
      3.0
     ],
     "utility": 0.8842,
     "release": {
      "RAW": 1216,
      "REWRITTEN": 400
     },
     "overblock": {
      "k": 17,
      "n": 3528,
      "p": 0.0048,
      "ci": [
       0.003,
       0.0077
      ]
     },
     "residualFinalK": {
      "k=2": 75,
      "k=4": 50,
      "k=3": 62,
      "k=1": 71
     }
    },
    "C1": {
     "n": 296,
     "outcomes": {
      "BUDGET": 296
     },
     "violTurn7": {
      "k": 0,
      "n": 296,
      "p": 0.0,
      "ci": [
       0.0,
       0.0128
      ]
     },
     "violFinal": {
      "k": 0,
      "n": 296,
      "p": 0.0,
      "ci": [
       0.0,
       0.0128
      ]
     },
     "riskAtTurn0": {
      "k": 0,
      "n": 296,
      "p": 0.0,
      "ci": [
       0.0,
       0.0128
      ]
     },
     "firstViolationMedian": null,
     "cum": [
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0
     ],
     "kMed": [
      85.0,
      40.0,
      20.0,
      13.0,
      11.0,
      10.0,
      9.0,
      8.0,
      8.0,
      8.0,
      8.0
     ],
     "utility": 0.6009,
     "release": {
      "RAW": 1401,
      "REWRITTEN": 1855
     },
     "overblock": {
      "k": 444,
      "n": 6709,
      "p": 0.0662,
      "ci": [
       0.0605,
       0.0724
      ]
     },
     "residualFinalK": {}
    }
   }
  },
  "full_uniform": {
   "config": {
    "budget_B": 10,
    "mode": "efficiency",
    "fuzzer": "uniform",
    "k_req": 5,
    "generalize_threshold": 5,
    "suppress_threshold": 3
   },
   "arms": {
    "C0": {
     "n": 296,
     "outcomes": {
      "RISK_REACHED": 268,
      "RISK_AT_TURN0": 28
     },
     "violTurn7": {
      "k": 294,
      "n": 296,
      "p": 0.9932,
      "ci": [
       0.9757,
       0.9981
      ]
     },
     "violFinal": {
      "k": 296,
      "n": 296,
      "p": 1.0,
      "ci": [
       0.9872,
       1.0
      ]
     },
     "riskAtTurn0": {
      "k": 28,
      "n": 296,
      "p": 0.0946,
      "ci": [
       0.0663,
       0.1333
      ]
     },
     "firstViolationMedian": 2.0,
     "cum": [
      0.0946,
      0.4324,
      0.7297,
      0.8784,
      0.9426,
      0.9797,
      0.9932,
      0.9932,
      0.9966,
      1.0,
      1.0
     ],
     "kMed": [
      75.0,
      8.0,
      2.0,
      1.0,
      1.0,
      1.0,
      1.0,
      1.0,
      1.0,
      1.0,
      1.0
     ],
     "utility": 1.0,
     "release": {
      "RAW": 876
     },
     "overblock": {
      "k": 0,
      "n": 2275,
      "p": 0.0,
      "ci": [
       0.0,
       0.0017
      ]
     },
     "residualFinalK": {}
    },
    "C1S": {
     "n": 296,
     "outcomes": {
      "BUDGET": 22,
      "RISK_REACHED": 274
     },
     "violTurn7": {
      "k": 254,
      "n": 296,
      "p": 0.8581,
      "ci": [
       0.8138,
       0.8933
      ]
     },
     "violFinal": {
      "k": 274,
      "n": 296,
      "p": 0.9257,
      "ci": [
       0.89,
       0.9504
      ]
     },
     "riskAtTurn0": {
      "k": 0,
      "n": 296,
      "p": 0.0,
      "ci": [
       0.0,
       0.0128
      ]
     },
     "firstViolationMedian": 3.0,
     "cum": [
      0.0,
      0.1622,
      0.3818,
      0.5777,
      0.6791,
      0.7601,
      0.8311,
      0.8581,
      0.8919,
      0.902,
      0.9257
     ],
     "kMed": [
      85.0,
      32.0,
      8.0,
      3.0,
      3.0,
      2.0,
      2.0,
      2.0,
      2.0,
      2.0,
      2.0
     ],
     "utility": 0.8244,
     "release": {
      "RAW": 977,
      "REWRITTEN": 490
     },
     "overblock": {
      "k": 18,
      "n": 2958,
      "p": 0.0061,
      "ci": [
       0.0039,
       0.0096
      ]
     },
     "residualFinalK": {
      "k=1": 118,
      "k=2": 71,
      "k=3": 54,
      "k=4": 31
     }
    },
    "C1": {
     "n": 296,
     "outcomes": {
      "BUDGET": 296
     },
     "violTurn7": {
      "k": 0,
      "n": 296,
      "p": 0.0,
      "ci": [
       0.0,
       0.0128
      ]
     },
     "violFinal": {
      "k": 0,
      "n": 296,
      "p": 0.0,
      "ci": [
       0.0,
       0.0128
      ]
     },
     "riskAtTurn0": {
      "k": 0,
      "n": 296,
      "p": 0.0,
      "ci": [
       0.0,
       0.0128
      ]
     },
     "firstViolationMedian": null,
     "cum": [
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0
     ],
     "kMed": [
      85.0,
      38.0,
      20.0,
      15.0,
      13.0,
      11.0,
      11.0,
      10.0,
      10.0,
      9.0,
      9.0
     ],
     "utility": 0.427,
     "release": {
      "RAW": 942,
      "REWRITTEN": 2314
     },
     "overblock": {
      "k": 296,
      "n": 4786,
      "p": 0.0618,
      "ci": [
       0.0554,
       0.069
      ]
     },
     "residualFinalK": {}
    }
   }
  },
  "full_feedback": {
   "config": {
    "budget_B": 10,
    "mode": "efficiency",
    "fuzzer": "feedback",
    "k_req": 5,
    "generalize_threshold": 5,
    "suppress_threshold": 3
   },
   "arms": {
    "C0": {
     "n": 296,
     "outcomes": {
      "RISK_REACHED": 268,
      "RISK_AT_TURN0": 28
     },
     "violTurn7": {
      "k": 296,
      "n": 296,
      "p": 1.0,
      "ci": [
       0.9872,
       1.0
      ]
     },
     "violFinal": {
      "k": 296,
      "n": 296,
      "p": 1.0,
      "ci": [
       0.9872,
       1.0
      ]
     },
     "riskAtTurn0": {
      "k": 28,
      "n": 296,
      "p": 0.0946,
      "ci": [
       0.0663,
       0.1333
      ]
     },
     "firstViolationMedian": 2.0,
     "cum": [
      0.0946,
      0.4324,
      0.7872,
      0.9223,
      0.9865,
      0.9966,
      1.0,
      1.0,
      1.0,
      1.0,
      1.0
     ],
     "kMed": [
      75.0,
      8.0,
      1.5,
      1.0,
      1.0,
      1.0,
      1.0,
      1.0,
      1.0,
      1.0,
      1.0
     ],
     "utility": 1.0,
     "release": {
      "RAW": 823
     },
     "overblock": {
      "k": 0,
      "n": 2097,
      "p": 0.0,
      "ci": [
       0.0,
       0.0018
      ]
     },
     "residualFinalK": {}
    },
    "C1S": {
     "n": 296,
     "outcomes": {
      "RISK_REACHED": 275,
      "BUDGET": 21
     },
     "violTurn7": {
      "k": 262,
      "n": 296,
      "p": 0.8851,
      "ci": [
       0.8438,
       0.9166
      ]
     },
     "violFinal": {
      "k": 275,
      "n": 296,
      "p": 0.9291,
      "ci": [
       0.894,
       0.9531
      ]
     },
     "riskAtTurn0": {
      "k": 0,
      "n": 296,
      "p": 0.0,
      "ci": [
       0.0,
       0.0128
      ]
     },
     "firstViolationMedian": 3,
     "cum": [
      0.0,
      0.1622,
      0.3716,
      0.5878,
      0.7128,
      0.777,
      0.8547,
      0.8851,
      0.9054,
      0.9291,
      0.9291
     ],
     "kMed": [
      85.0,
      32.0,
      8.0,
      3.0,
      3.0,
      2.0,
      2.0,
      2.0,
      2.0,
      2.0,
      2.0
     ],
     "utility": 0.8029,
     "release": {
      "RAW": 919,
      "REWRITTEN": 506
     },
     "overblock": {
      "k": 17,
      "n": 2813,
      "p": 0.006,
      "ci": [
       0.0038,
       0.0097
      ]
     },
     "residualFinalK": {
      "k=1": 122,
      "k=2": 73,
      "k=3": 49,
      "k=4": 31
     }
    },
    "C1": {
     "n": 296,
     "outcomes": {
      "BUDGET": 296
     },
     "violTurn7": {
      "k": 0,
      "n": 296,
      "p": 0.0,
      "ci": [
       0.0,
       0.0128
      ]
     },
     "violFinal": {
      "k": 0,
      "n": 296,
      "p": 0.0,
      "ci": [
       0.0,
       0.0128
      ]
     },
     "riskAtTurn0": {
      "k": 0,
      "n": 296,
      "p": 0.0,
      "ci": [
       0.0,
       0.0128
      ]
     },
     "firstViolationMedian": null,
     "cum": [
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0
     ],
     "kMed": [
      85.0,
      38.0,
      22.0,
      14.0,
      11.0,
      10.0,
      9.0,
      9.0,
      9.0,
      8.0,
      8.0
     ],
     "utility": 0.4443,
     "release": {
      "RAW": 949,
      "REWRITTEN": 2307
     },
     "overblock": {
      "k": 346,
      "n": 5037,
      "p": 0.0687,
      "ci": [
       0.062,
       0.076
      ]
     },
     "residualFinalK": {}
    }
   }
  }
 },
 "fuzzerCompare": {
  "staged": {
   "n": 296,
   "viol_uniform": 296,
   "viol_feedback": 296,
   "n_both_after_turn0": 268,
   "feedback_faster": 100,
   "same": 128,
   "feedback_slower": 40,
   "median_uniform": 3.0,
   "median_feedback": 3.0,
   "mean_uniform": 3.634,
   "mean_feedback": 3.007
  },
  "full": {
   "n": 296,
   "viol_uniform": 296,
   "viol_feedback": 296,
   "n_both_after_turn0": 268,
   "feedback_faster": 41,
   "same": 215,
   "feedback_slower": 12,
   "median_uniform": 2.0,
   "median_feedback": 2.0,
   "mean_uniform": 2.164,
   "mean_feedback": 1.966
  }
 },
 "static": {
  "infoRetention": {
   "ours": 44.5,
   "single": 25.6,
   "fixed": 2.3,
   "source": "SynthPAI 30명 · 실제 LLM · 위반 0% 조건 (발표 39p)"
  },
  "normalPass": {
   "value": 98.9,
   "source": "SynthPAI 정상 질문 6턴 · 30만 명 기준 (발표 37p)"
  },
  "latency": {
   "meanSec": 0.011,
   "p95Sec": 0.037,
   "source": "시뮬레이션 · k 계산 + 판정, LLM 제외 (발표 42p)"
  },
  "extraction": {
   "recall": 89.2,
   "precision": 97.0,
   "f1": 0.929,
   "committed": {
    "recall": 83.2,
    "f1": 0.896
   },
   "source": "holdout_2 · 처음 보는 질의 환자 13명 · 팀 고정본 채점 (확정 값 기준 재현율 83.2% · F1 0.896)",
   "target": {
    "recall": 95,
    "precision": 90,
    "f1": 0.92
   }
  }
 }
};

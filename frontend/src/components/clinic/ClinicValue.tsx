import { Lock } from 'lucide-react';
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { attrName, refLabel } from '../../lib/clinicianCopy';
import { josa } from '../../lib/korean';
import type { PrivacyTransformation } from '../../types/domain';

/** 가린 · 넓힌 까닭 한 줄 (판정 기록의 표지를 그대로 따른다) */
export function whyLine(t: PrivacyTransformation): string {
  if (t.purpose) return '이번 조회 목적(처방 · 시술 · 경과 참고)에 쓰지 않는 정보라 뺐습니다.';
  if (t.rule) return '보안 담당자가 정한 규칙으로 뺐습니다.';
  if (t.floor) return '나이 · 날짜는 위험과 관계없이 정해진 공개 단위(나이 5세 구간 · 날짜 월)로만 보입니다.';
  if (t.attribute === 'DURATION') return '기간은 정해 둔 범위로만 보입니다 (예: 약 1~2주, 1년 이상).';
  return t.action === 'suppress'
    ? '그 값에 해당하는 과거 환자가 아주 적어, 그대로 보이면 누구인지 알 수 있습니다.'
    : '정확한 값이면 해당하는 과거 환자가 적어, 뜻은 그대로 두고 한 단계 넓혔습니다.';
}

/**
 * 표시 하나를 누르면 그 자리에서 무엇을 왜 바꿨는지 설명한다 (마우스를 올리는 title은 터치 화면에서 보이지 않는다).
 * 설명 창은 화면 기준(fixed)으로 띄워 답 카드 테두리에 잘리지 않게 하고, 바깥을 누르거나 Esc · 스크롤이면 닫는다.
 */
/** 누르면 설명 상자가 뜨는 표시 ('비공개' · '범위'). 유사 사례 보고서도 같이 쓴다 */
export function Explained({ trigger, title, lines, className }: { trigger: ReactNode; title: string; lines: string[]; className: string }) {
  const [at, setAt] = useState<{ top: number; left: number } | null>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const box = useRef<HTMLSpanElement>(null);
  const id = useId();

  useEffect(() => {
    if (!at) return;
    const close = (e: Event) => {
      if (e.type === 'keydown' && (e as KeyboardEvent).key !== 'Escape') return;
      if (e.type === 'pointerdown' && (box.current?.contains(e.target as Node) || btn.current?.contains(e.target as Node))) return;
      setAt(null);
    };
    document.addEventListener('pointerdown', close);
    document.addEventListener('keydown', close);
    window.addEventListener('scroll', close, true);
    window.addEventListener('resize', close);
    return () => {
      document.removeEventListener('pointerdown', close);
      document.removeEventListener('keydown', close);
      window.removeEventListener('scroll', close, true);
      window.removeEventListener('resize', close);
    };
  }, [at]);

  function toggle() {
    if (at) {
      setAt(null);
      return;
    }
    const r = btn.current?.getBoundingClientRect();
    if (!r) return;
    const width = Math.min(300, window.innerWidth - 16);
    setAt({ top: r.bottom + 6, left: Math.max(8, Math.min(r.left, window.innerWidth - width - 8)) });
  }

  return (
    <>
      <button ref={btn} type="button" className={className} aria-expanded={!!at} aria-controls={at ? id : undefined} onClick={toggle}>
        {trigger}
      </button>
      {at && (
        <span ref={box} id={id} role="note" className="value-note" style={{ top: at.top, left: at.left }}>
          <span className="block font-semibold text-ink">{title}</span>
          {lines.map((l) => (
            <span key={l} className="mt-1 block">
              {l}
            </span>
          ))}
        </span>
      )}
    </>
  );
}

/**
 * 의료진 화면에서 답 속 값 하나를 보여 준다. 판정은 백엔드가 준 조치를 그대로 따른다.
 *   그대로 답한 값: 표시 없이 글 그대로
 *   넓힌 값: 점선 밑줄 + '범위' 꼬리표 (누르면 설명)
 *   가린 값: 잠금 표시 + 사선 막대 '처방 약 비공개' (누르면 설명. 위험색을 쓰지 않는다. 다른 꼬리표와 헷갈리지 않게 테두리 · 사선을 둔다)
 * 설명에는 누가(MediCloak) · 어느 사례의 무엇을 · 왜 · 원래 기록은 어떻게 되는지를 쓴다. 숫자(후보 수)는 쓰지 않는다.
 */
export function ClinicValue({
  text,
  transformation,
  children,
  placeholderLabel,
  partial = false,
  named = false,
}: {
  text: string;
  transformation: PrivacyTransformation | undefined;
  children?: ReactNode;
  /** 답 글에서 지워진 가린 값의 자리 표시: 무엇을 가렸는지 이름을 붙여 보인다 ('시기 비공개') */
  placeholderLabel?: string;
  /** 같은 사례의 같은 단서가 답에 다른 값으로 보일 때: '다른 처방 약 비공개' */
  partial?: boolean;
  /** 글 안의 '비공개' 자리에 단서 이름을 붙인다 ('처방 약 비공개'). 항목 이름이 따로 보이는 줄에서는 끈다 */
  named?: boolean;
}) {
  const body = children ?? text;
  if (!transformation || transformation.action === 'allow') return <>{body}</>;
  const t = transformation;
  const name = attrName(t);
  const where = t.caseRef ? `${refLabel(t.caseRef)}의 ` : '';
  const keep = '과거 사례 기록은 그대로 있고, 이 답에만 이렇게 보입니다. 꼭 필요하면 답 아래 세부 정보 요청을 보내세요.';

  if (placeholderLabel && t.action === 'suppress') {
    const label = partial ? `다른 ${placeholderLabel} 비공개` : `${placeholderLabel} 비공개`;
    const lines = [
      partial
        ? `MediCloak이 ${where}${josa(name, '을', '를')} 일부만 보이고 나머지는 답에서 뺐습니다. 위에 보이는 ${josa(name, '은', '는')} 그대로입니다.`
        : `MediCloak이 이 자리에 있던 ${where}${josa(name, '을', '를')} 답에서 뺐습니다.`,
      whyLine(t),
      keep,
    ];
    return (
      <Explained
        className="lock-token ml-1.5"
        title={`${where}${label}`}
        lines={lines}
        trigger={
          <>
            <Lock className="h-3 w-3 shrink-0" strokeWidth={2.4} aria-hidden />
            <span className="lock-bar" aria-hidden />
            {label}
            <span className="sr-only"> (눌러서 설명 보기)</span>
          </>
        }
      />
    );
  }
  if (t.action === 'generalize')
    return (
      <span>
        <span className="range-value">{body}</span>
        <Explained
          className="range-tag"
          title={`${where}${name} · 범위로 보임`}
          lines={[`MediCloak이 정확한 ${name} 대신 넓은 범위로 바꿨습니다. 밑줄 친 글이 바꾼 값입니다.`, whyLine(t), keep]}
          trigger={
            <>
              범위<span className="sr-only"> (눌러서 설명 보기)</span>
            </>
          }
        />
      </span>
    );
  return (
    <Explained
      className="lock-token"
      title={`${where}${name} 비공개`}
      lines={[`MediCloak이 이 자리의 ${josa(name, '을', '를')} 답에서 가렸습니다.`, whyLine(t), keep]}
      trigger={
        <>
          <Lock className="h-3 w-3 shrink-0" strokeWidth={2.4} aria-hidden />
          <span className="lock-bar" aria-hidden />
          {named ? `${name} 비공개` : '비공개'}
          <span className="sr-only"> (눌러서 설명 보기)</span>
        </>
      }
    />
  );
}

/**
 * 진료 지원 AI 답 글 속 '(비공개)': MediCloak이 사례 기록을 AI에 넘기기 전에 가린 값(입력 게이팅, ADR-0032)이라 AI도 '(비공개)'로 썼다.
 * 답에서 가린 값('처방 약 비공개')과 구분되게 'AI에 보내지 않음'으로 보이고, 누르면 설명이 뜬다.
 */
export function GatedMark() {
  return (
    <Explained
      className="lock-token"
      title="AI에 보내지 않은 값"
      lines={[
        'MediCloak이 과거 사례 기록을 진료 지원 AI에 넘기기 전에 이 값을 가렸습니다. 그래서 AI 답에도 (비공개)로 나옵니다.',
        '그 값에 해당하는 과거 환자가 적어, AI에 넣으면 답으로 환자를 알아볼 수 있습니다.',
        '과거 사례 기록은 그대로 있습니다. 꼭 필요하면 답 아래 세부 정보 요청을 보내세요.',
      ]}
      trigger={
        <>
          <Lock className="h-3 w-3 shrink-0" strokeWidth={2.4} aria-hidden />
          AI에 보내지 않음
          <span className="sr-only"> (눌러서 설명 보기)</span>
        </>
      }
    />
  );
}

/** 백엔드 요약 문장 속 '(비공개)'를 잠금 표시로 바꿔 보여 준다 (사례 목록 설명 등). */
export function LockedText({ text }: { text: string }) {
  const parts = text.split('(비공개)');
  if (parts.length === 1) return <>{text}</>;
  return (
    <>
      {parts.map((part, i) => (
        <span key={i}>
          {part}
          {i < parts.length - 1 && (
            <span className="lock-token" title="개인을 알아볼 수 있는 값이라 비공개로 처리했습니다">
              <Lock className="h-3 w-3" strokeWidth={2.2} aria-hidden />
              비공개
            </span>
          )}
        </span>
      ))}
    </>
  );
}

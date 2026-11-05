import { Lock } from 'lucide-react';
import type { ReactNode } from 'react';
import { attrName } from '../../lib/clinicianCopy';
import { josa } from '../../lib/korean';
import type { PrivacyTransformation } from '../../types/domain';

/**
 * 의료진 화면에서 답 속 값 하나를 보여 준다. 판정은 백엔드가 준 조치를 그대로 따른다.
 *   그대로 답한 값: 표시 없이 글 그대로
 *   넓힌 값: 점선 밑줄과 '범위' 표시
 *   가린 값: 잠금 표시 + 사선 막대 '처방 약 비공개' (위험색을 쓰지 않는다. 다른 꼬리표와 헷갈리지 않게 테두리 · 사선을 둔다)
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
  /** 같은 사례의 같은 단서가 답에 다른 값으로 보일 때: '처방 약 일부 비공개' */
  partial?: boolean;
  /** 글 안의 '비공개' 자리에 단서 이름을 붙인다 ('처방 약 비공개'). 항목 이름이 따로 보이는 줄에서는 끈다 */
  named?: boolean;
}) {
  const body = children ?? text;
  if (!transformation || transformation.action === 'allow') return <>{body}</>;
  const name = attrName(transformation);
  if (placeholderLabel && transformation.action === 'suppress') {
    const why = transformation.purpose
      ? '이번 조회 목적에 필요하지 않아 답에서 뺐습니다.'
      : transformation.rule
        ? '보안 담당자 규칙으로 답에서 뺐습니다.'
        : '개인을 알아볼 수 있는 값이라 답에서 뺐습니다.';
    const shown = partial ? ` 같은 사례의 다른 ${josa(name, '은', '는')} 답에 보입니다.` : '';
    return (
      <span className="lock-token ml-1.5" title={`${placeholderLabel} ${partial ? '일부 ' : ''}비공개: ${why}${shown} 필요하면 세부 정보 요청을 보내세요.`}>
        <Lock className="h-3 w-3 shrink-0" strokeWidth={2.4} aria-hidden />
        <span className="lock-bar" aria-hidden />
        {placeholderLabel} {partial ? '일부 ' : ''}비공개
        <span className="sr-only"> ({why})</span>
      </span>
    );
  }
  if (transformation.action === 'generalize')
    return (
      <span title={`${name}: 개인을 알아볼 수 없도록 정확한 값 대신 범위로 보여 드립니다.`}>
        <span className="range-value">{body}</span>
        <span className="range-tag">범위</span>
      </span>
    );
  return (
    <span className="lock-token" title={`${name}: 개인을 알아볼 수 있는 값이라 비공개로 처리했습니다.`}>
      <Lock className="h-3 w-3 shrink-0" strokeWidth={2.4} aria-hidden />
      <span className="lock-bar" aria-hidden />
      {named ? `${name} 비공개` : '비공개'}
      <span className="sr-only"> ({name} 비공개 처리됨)</span>
    </span>
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

import { Lock } from 'lucide-react';
import type { ReactNode } from 'react';
import { attrName } from '../../lib/clinicianCopy';
import type { PrivacyTransformation } from '../../types/domain';

/**
 * 의료진 화면에서 답 속 값 하나를 보여 준다. 판정은 백엔드가 준 조치를 그대로 따른다.
 *   그대로 답한 값: 표시 없이 글 그대로
 *   넓힌 값: 점선 밑줄과 '범위' 표시
 *   가린 값: 잠금 표시 '비공개' (위험색을 쓰지 않는다)
 */
export function ClinicValue({
  text,
  transformation,
  children,
  placeholderLabel,
}: {
  text: string;
  transformation: PrivacyTransformation | undefined;
  children?: ReactNode;
  /** 답 글에서 지워진 가린 값의 자리 표시: 무엇을 가렸는지 이름을 붙여 보인다 ('시기 비공개') */
  placeholderLabel?: string;
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
    return (
      <span className="lock-token ml-1.5" title={`${placeholderLabel}: ${why} 필요하면 세부 정보 요청을 보내세요.`}>
        <Lock className="h-3 w-3" strokeWidth={2.2} aria-hidden />
        {placeholderLabel} 비공개
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
      <Lock className="h-3 w-3" strokeWidth={2.2} aria-hidden />
      비공개
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

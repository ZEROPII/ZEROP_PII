import { AlertCircle, Loader2, RotateCw, Trash2 } from 'lucide-react';
import { formatTime } from '../../lib/format';
import { useTermDetect } from '../../state/TermContext';
import type { ChatMessage as ChatMessageModel } from '../../types/domain';
import type { TermMention } from '../../types/terminology';
import { LogoMark } from '../brand/Logo';
import { PrivacyExplanation } from './PrivacyExplanation';
import { AnswerTerms } from '../terminology/AnswerTerms';
import { TermText } from '../terminology/TermText';
import { PrivacyHighlight } from './PrivacyHighlight';

interface Props {
  message: ChatMessageModel;
  onRetry?: (message: ChatMessageModel) => void;
  onDiscard?: (message: ChatMessageModel) => void;
}

function MessageBody({ message, mentions }: { message: ChatMessageModel; mentions?: (TermMention[] | undefined)[] }) {
  const byId = new Map(message.protection?.transformations.map((t) => [t.id, t]));
  return (
    <>
      {message.segments.map((segment, i) => {
        const terms = <TermText text={segment.text} mentions={mentions?.[i]} />;
        return segment.kind === 'text' ? (
          <span key={i}>{terms}</span>
        ) : (
          <PrivacyHighlight
            key={i}
            text={segment.text}
            transformation={byId.get(segment.transformationId)}
            placeholderLabel={segment.placeholder ? segment.label : undefined}
            partial={segment.placeholder ? segment.partial : undefined}
          >
            {terms}
          </PrivacyHighlight>
        );
      })}
    </>
  );
}

/** AI 답변: 답변 속 의료 용어에 밑줄을 긋고 아래에 용어 칩을 띄운다 (자동 표시를 끄면 글 그대로). */
function AssistantBody({ message }: { message: ChatMessageModel }) {
  const { mentions } = useTermDetect(message.segments.map((s) => s.text));
  return (
    <>
      <div className="whitespace-pre-wrap break-words rounded-[18px] rounded-tl-[6px] border border-line bg-surface px-4 py-3 text-sm leading-relaxed text-ink">
        <span className="sr-only">AI 답변: </span>
        <MessageBody message={message} mentions={mentions} />
      </div>
      <AnswerTerms mentions={mentions} />
    </>
  );
}

export function ChatMessage({ message, onRetry, onDiscard }: Props) {
  if (message.role === 'user') {
    return (
      <div className="flex flex-col items-end">
        <div
          className={`max-w-[85%] whitespace-pre-wrap break-words rounded-[18px] rounded-br-[6px] bg-iris px-4 py-2.5 text-sm leading-relaxed text-iris-on ${
            message.status === 'pending' ? 'opacity-70' : ''
          } ${message.status === 'failed' ? 'opacity-60 ring-2 ring-danger' : ''}`}
        >
          <MessageBody message={message} />
        </div>
        <div className="mt-1 flex items-center gap-2 text-[11px] text-ink-3">
          {message.status === 'pending' && (
            <span className="inline-flex items-center gap-1">
              <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> 보내는 중
            </span>
          )}
          {message.status === 'failed' && (
            <span className="inline-flex items-center gap-2 text-danger-text">
              <AlertCircle className="h-3 w-3" aria-hidden /> 보내지 못했습니다
              {onRetry && (
                <button type="button" onClick={() => onRetry(message)} className="inline-flex items-center gap-0.5 font-semibold hover:underline">
                  <RotateCw className="h-3 w-3" aria-hidden /> 다시 보내기
                </button>
              )}
              {onDiscard && (
                <button type="button" onClick={() => onDiscard(message)} className="inline-flex items-center gap-0.5 font-semibold hover:underline">
                  <Trash2 className="h-3 w-3" aria-hidden /> 지우기
                </button>
              )}
            </span>
          )}
          {message.status === 'sent' && <time dateTime={message.createdAt}>{formatTime(message.createdAt)}</time>}
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-start gap-3">
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-iris-tint" aria-hidden>
        <LogoMark size={20} />
      </span>
      <div className="min-w-0 max-w-[88%]">
        <AssistantBody message={message} />
        {message.protection && <PrivacyExplanation protection={message.protection} />}
        <time dateTime={message.createdAt} className="mt-1 block text-[11px] text-ink-3">
          {formatTime(message.createdAt)}
        </time>
      </div>
    </div>
  );
}

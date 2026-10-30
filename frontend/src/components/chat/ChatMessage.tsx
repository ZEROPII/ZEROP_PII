import { AlertCircle, Bot, Loader2, RotateCw, Trash2 } from 'lucide-react';
import { formatTime } from '../../lib/format';
import type { ChatMessage as ChatMessageModel } from '../../types/domain';
import { PrivacyExplanation } from './PrivacyExplanation';
import { PrivacyHighlight } from './PrivacyHighlight';

interface Props {
  message: ChatMessageModel;
  onRetry?: (message: ChatMessageModel) => void;
  onDiscard?: (message: ChatMessageModel) => void;
}

function MessageBody({ message }: { message: ChatMessageModel }) {
  const byId = new Map(message.protection?.transformations.map((t) => [t.id, t]));
  return (
    <>
      {message.segments.map((segment, i) =>
        segment.kind === 'text' ? (
          <span key={i}>{segment.text}</span>
        ) : (
          <PrivacyHighlight key={i} text={segment.text} transformation={byId.get(segment.transformationId)} />
        ),
      )}
    </>
  );
}

export function ChatMessage({ message, onRetry, onDiscard }: Props) {
  if (message.role === 'user') {
    return (
      <div className="flex flex-col items-end">
        <div
          className={`max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-blue-600 px-3.5 py-2 text-[13px] leading-relaxed text-white shadow-sm ${
            message.status === 'pending' ? 'opacity-70' : ''
          } ${message.status === 'failed' ? 'bg-blue-600/60 ring-2 ring-red-300' : ''}`}
        >
          <MessageBody message={message} />
        </div>
        <div className="mt-1 flex items-center gap-2 text-[10px] text-slate-400">
          {message.status === 'pending' && (
            <span className="inline-flex items-center gap-1">
              <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> 전송 중
            </span>
          )}
          {message.status === 'failed' && (
            <span className="inline-flex items-center gap-2 text-red-600">
              <AlertCircle className="h-3 w-3" aria-hidden /> 전송 실패
              {onRetry && (
                <button type="button" onClick={() => onRetry(message)} className="inline-flex items-center gap-0.5 font-medium underline-offset-2 hover:underline">
                  <RotateCw className="h-3 w-3" aria-hidden /> 다시 보내기
                </button>
              )}
              {onDiscard && (
                <button type="button" onClick={() => onDiscard(message)} className="inline-flex items-center gap-0.5 font-medium underline-offset-2 hover:underline">
                  <Trash2 className="h-3 w-3" aria-hidden /> 삭제
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
    <div className="flex items-start gap-2.5">
      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-navy-900 text-white" aria-hidden>
        <Bot className="h-4 w-4" />
      </span>
      <div className="min-w-0 max-w-[88%]">
        <div className="whitespace-pre-wrap break-words rounded-2xl rounded-tl-md border border-slate-200 bg-white px-3.5 py-2.5 text-[13px] leading-relaxed text-slate-800 shadow-sm">
          <span className="sr-only">AI 답변: </span>
          <MessageBody message={message} />
        </div>
        {message.protection && <PrivacyExplanation protection={message.protection} />}
        <time dateTime={message.createdAt} className="mt-1 block text-[10px] text-slate-400">
          {formatTime(message.createdAt)}
        </time>
      </div>
    </div>
  );
}

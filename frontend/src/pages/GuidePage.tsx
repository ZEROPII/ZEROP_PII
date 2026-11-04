import { Lock, MailQuestion, MessageSquareReply, ShieldCheck } from 'lucide-react';
import type { ReactNode } from 'react';

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-t border-line pt-5 first:border-t-0 first:pt-0">
      <h2 className="text-[17px] font-bold tracking-[-0.015em] text-ink">{title}</h2>
      <div className="mt-2 space-y-2 text-sm leading-7 text-ink-2">{children}</div>
    </section>
  );
}

const WORDS: [string, string][] = [
  ['사례', 'AI가 찾아 보여 준 비슷한 과거 환자 기록 하나. 이름이나 환자 번호 없이 사례 1, 사례 2로 부릅니다.'],
  ['범위', '정확한 값 대신 보여 드린 넓은 값. 예를 들어 정확한 날짜 대신 연도, 정확한 나이 대신 나이대입니다.'],
  ['비공개', '그대로 알려 드리면 특정 환자를 알아볼 수 있어 답에서 뺀 값.'],
  ['세부 정보 제한', '지금까지 나온 내용만으로도 환자를 좁힐 수 있는 사례. 새로 묻는 세부 값은 범위로 보이거나 비공개일 수 있습니다.'],
  ['사례 노트', '그 사례에 대해 지금까지 답에 나온 내용을 한 장으로 모은 것. 값마다 그 값을 꺼낸 질문으로 돌아갈 수 있습니다.'],
];

/** 의료진용 보호 안내: 숫자 없이, 무엇이 왜 가려지고 필요하면 어떻게 요청하는지. 기준값은 보안 담당자 '보호 정책'에 있다. */
export function GuidePage() {
  return (
    <div className="scroll-thin h-full overflow-y-auto">
      <article className="mx-auto max-w-2xl space-y-6 px-4 py-6 md:px-6 md:py-8">
        <header>
          <p className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-iris-text">
            <ShieldCheck className="h-4 w-4" aria-hidden /> MediCloak 보호 적용
          </p>
          <h1 className="mt-1 text-2xl font-bold tracking-[-0.025em] text-ink">진료 지원 AI의 개인정보 보호</h1>
          <p className="mt-2 text-sm leading-7 text-ink-2">
            이 AI는 비슷한 과거 사례의 기록을 찾아 답합니다. MediCloak은 답이 화면에 나오기 전에, 그 답과 앞선 대화를 함께 보고 특정 환자를 알아볼 수
            있게 되는 값이 있는지 확인합니다. 진료에 필요한 내용은 그대로 두고, 환자를 좁히는 값만 넓히거나 뺍니다.
          </p>
        </header>

        <Section title="답에 보이는 표시">
          <dl className="space-y-3">
            <div className="grid grid-cols-[112px_minmax(0,1fr)] items-baseline gap-3">
              <dt className="font-medium text-ink">Massachusetts</dt>
              <dd>표시가 없는 값은 기록 그대로입니다.</dd>
            </div>
            <div className="grid grid-cols-[112px_minmax(0,1fr)] items-baseline gap-3">
              <dt className="font-medium text-ink">
                <span className="range-value">0~9세</span>
                <span className="range-tag">범위</span>
              </dt>
              <dd>정확한 값 대신 한 단계 넓은 범위로 바꾼 값입니다. 뜻은 같고 덜 자세합니다.</dd>
            </div>
            <div className="grid grid-cols-[112px_minmax(0,1fr)] items-baseline gap-3">
              <dt>
                <span className="lock-token">
                  <Lock className="h-3 w-3" strokeWidth={2.2} aria-hidden />
                  비공개
                </span>
              </dt>
              <dd>그대로 알려 드리면 그 환자가 누구인지 알 수 있게 되는 값이라 뺐습니다. 답의 나머지는 그대로입니다.</dd>
            </div>
          </dl>
          <p>
            같은 질문도 대화가 이어지면 다르게 보일 수 있습니다. 앞선 답에서 나온 내용과 합쳐 환자가 좁혀지는지까지 함께 보기 때문입니다.
          </p>
        </Section>

        <Section title="세부 정보가 꼭 필요할 때">
          <p className="flex gap-2">
            <MailQuestion className="mt-1.5 h-4 w-4 shrink-0 text-iris-text" aria-hidden />
            <span>
              답 아래 <strong className="font-semibold text-ink">세부 정보 요청</strong>을 누르고 사유를 적어 보내면 개인정보 보호 담당자에게 갑니다. 답장은
              오른쪽 <strong className="font-semibold text-ink">보호 담당자 메시지</strong>에 오고, 머리줄 알림에도 표시됩니다.
            </span>
          </p>
          <p className="flex gap-2">
            <MessageSquareReply className="mt-1.5 h-4 w-4 shrink-0 text-iris-text" aria-hidden />
            <span>보호 담당자가 질문한 목적을 물어볼 때도 있습니다(확인 요청). 대화 위에 안내가 뜨면 답장해 주세요.</span>
          </p>
        </Section>

        <Section title="남는 기록">
          <p>
            질문과 답, 세부 정보 요청과 답장은 감사 기록에 남고 개인정보 보호 담당자가 확인할 수 있습니다. 보호 담당자가 가린 원래 값을 열어 볼 때도 사유를
            남겨야 하며, 그 열람도 기록됩니다.
          </p>
        </Section>

        <Section title="화면에서 쓰는 말">
          <dl className="divide-y divide-line rounded-control border border-line bg-surface">
            {WORDS.map(([t, d]) => (
              <div key={t} className="grid grid-cols-[112px_minmax(0,1fr)] gap-3 px-4 py-3">
                <dt className="font-semibold text-ink">{t}</dt>
                <dd className="text-[13px] leading-6 text-ink-2">{d}</dd>
              </div>
            ))}
          </dl>
        </Section>
      </article>
    </div>
  );
}
